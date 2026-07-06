"""GridFront Radius training runner — the daemon on the GPU PC.

Polls the platform for queued Radius training jobs, executes the
training/radius pipeline stages as subprocesses (same python env), streams
progress + log tails back, uploads the exported blob + sidecar + eval JSON,
and reports completion. Stdlib-only on purpose: a fresh Windows box with
Python 3.11+ needs zero extra packages to run the runner itself (the
pipeline stages have their own deps — see ../requirements.txt).

API contract (the platform side is built to exactly this):
  POST {base}/api/agent/runner/claim                  -> 200 {job} | 204 none
  POST {base}/api/agent/runner/jobs/{id}/progress     -> 200 | 409 = cancelled
  POST {base}/api/agent/runner/jobs/{id}/artifact-url -> {upload_url, storage_path}
  POST {base}/api/agent/runner/jobs/{id}/complete
All requests carry `Authorization: Bearer <token>` from runner.toml.

Usage:
    python runner.py                    # config from ./runner.toml
    python runner.py --config <path>
    python runner.py --once             # process at most one job, then exit
    python runner.py --check-config     # validate runner.toml and exit

Install/operate: README.md in this directory. Tests: tests/test_runner.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent            # training/radius/runner
LOG_DIR = HERE / "logs"
STATE_DIR = HERE / "state"

CAPABILITIES = ["radius_base"]
DEFAULT_STAGES = ["remap", "complete_labels", "augment",
                  "train_s1", "train_s2", "eval", "export"]
KNOWN_STAGES = set(DEFAULT_STAGES)

HEARTBEAT_SECONDS = 60
TAIL_LINES = 40
TAIL_LINE_CHARS = 400
MARKER_PREFIX = "PROGRESS "
COMPLETE_RETRY_DELAYS = [0, 5, 10, 20, 40, 60]    # never leave a job silent


class Cancelled(Exception):
    """Platform answered 409 — job cancelled/reassigned. Stop, don't complete."""


class StageFailed(Exception):
    """A pipeline stage subprocess exited nonzero (or its output is missing)."""


class JobSpecError(Exception):
    """The claimed job's spec asks for something this runner can't do."""


# ── config ───────────────────────────────────────────────────────────────

@dataclass
class Config:
    platform_url: str
    token: str
    runner_id: str
    repo_root: Path
    python_exe: str
    poll_interval: float
    data_root: Path


def load_config(path: Path) -> Config:
    if sys.version_info < (3, 11):
        raise SystemExit("runner requires Python 3.11+ (tomllib is stdlib there)")
    import tomllib
    if not path.exists():
        raise SystemExit(f"config not found: {path} (copy runner.toml.example "
                         f"to runner.toml and fill it in)")
    doc = tomllib.loads(path.read_text(encoding="utf-8"))
    missing = [k for k in ("platform_url", "token", "runner_id") if not doc.get(k)]
    if missing:
        raise SystemExit(f"runner.toml is missing required keys: {missing}")
    repo_root = Path(doc.get("repo_root") or HERE.parents[2]).resolve()
    if not (repo_root / "training" / "radius").is_dir():
        raise SystemExit(f"repo_root {repo_root} has no training/radius — wrong path?")
    return Config(
        platform_url=str(doc["platform_url"]).rstrip("/"),
        token=str(doc["token"]),
        runner_id=str(doc["runner_id"]),
        repo_root=repo_root,
        python_exe=str(doc.get("python_exe") or sys.executable),
        poll_interval=float(doc.get("poll_interval") or 30),
        data_root=Path(doc.get("data_root")
                       or repo_root / "training" / "radius" / "data"),
    )


# ── small pure helpers (unit-tested) ─────────────────────────────────────

def plan_stages(spec: dict, completed: list[str]) -> tuple[list[str], list[str]]:
    """(requested, remaining) stage lists for a job spec + resume state."""
    requested = list(spec.get("stages") or DEFAULT_STAGES)
    unknown = [s for s in requested if s not in KNOWN_STAGES]
    if unknown:
        raise JobSpecError(f"spec.stages has unknown stages {unknown}; "
                           f"known: {DEFAULT_STAGES}")
    done = set(completed)
    return requested, [s for s in requested if s not in done]


def stage_commands(stage: str, spec: dict, python_exe: str,
                   radius_dir: Path) -> list[list[str]]:
    """Argv lists for one stage (run sequentially, cwd=training/radius).

    spec.stage_args = {stage: [extra argv]} appends per-stage arguments
    (argparse last-wins, so extras can override the defaults below).
    """
    extra = [str(a) for a in (spec.get("stage_args") or {}).get(stage, [])]
    py = python_exe
    if stage == "remap":
        return [[py, "datasets.py", "remap", *extra]]
    if stage == "complete_labels":
        return [[py, "complete_labels.py", "--split", "train", *extra],
                [py, "complete_labels.py", "--split", "val", *extra]]
    if stage == "augment":
        frac = spec.get("augment_frac", 0.4)
        return [[py, "augment_fisheye.py", "--frac", str(frac), *extra]]
    if stage == "train_s1":
        return [[py, "train_radius.py", "stage1", *extra]]
    if stage == "train_s2":
        return [[py, "train_radius.py", "stage2", *extra]]
    if stage == "export":
        version = str(spec.get("version") or "v1")
        ckpt = str(spec.get("checkpoint")
                   or radius_dir / "runs" / "radius_s2" / "weights" / "best_ckpt.pt")
        return [[py, "export_blob.py", ckpt, "--version", version, *extra]]
    if stage == "eval":
        raise ValueError("eval is handled by JobRunner._run_eval_stage")
    raise JobSpecError(f"unknown stage: {stage!r}")


def parse_progress_marker(line: str) -> dict | None:
    """Parse a `PROGRESS {json}` line from a child. None if not a marker.

    Recognized keys: stage_pct (clamped 0..100), message, metrics.
    """
    s = line.strip()
    if not s.startswith(MARKER_PREFIX):
        return None
    try:
        doc = json.loads(s[len(MARKER_PREFIX):])
    except ValueError:
        return None
    if not isinstance(doc, dict):
        return None
    pct = doc.get("stage_pct")
    if isinstance(pct, (int, float)) and not isinstance(pct, bool):
        doc["stage_pct"] = max(0.0, min(100.0, float(pct)))
    else:
        doc.pop("stage_pct", None)
    return doc


class LogTail:
    """Rolling tail of output lines for progress.log_tail (line + char caps)."""

    def __init__(self, max_lines: int = TAIL_LINES,
                 max_line_chars: int = TAIL_LINE_CHARS):
        self._lines: deque[str] = deque(maxlen=max_lines)
        self._max_line_chars = max_line_chars
        self._lock = threading.Lock()

    def add(self, line: str) -> None:
        line = line.rstrip("\r\n")
        if len(line) > self._max_line_chars:
            line = line[:self._max_line_chars] + " ...[truncated]"
        with self._lock:
            self._lines.append(line)

    def get(self) -> str:
        with self._lock:
            return "\n".join(self._lines)


_BAR_PCT = re.compile(r"(\d+)%\|")


class BarDeduper:
    """Collapse tqdm redraw spam to ~one line per integer percent.

    tqdm redraws with \\r; universal-newline decoding turns each redraw into
    its own line, which would bloat a 40h training log into hundreds of MB.
    """

    def __init__(self) -> None:
        self._last: str | None = None

    def should_log(self, line: str) -> bool:
        m = _BAR_PCT.search(line)
        if not m:
            self._last = None
            return True
        if m.group(1) == self._last:
            return False
        self._last = m.group(1)
        return True


def parse_trailing_json(lines: list[str]) -> dict | None:
    """First JSON object found in captured child output (eval prints one)."""
    text = "\n".join(lines)
    i = text.find("{")
    dec = json.JSONDecoder()
    while i != -1:
        try:
            doc, _ = dec.raw_decode(text[i:])
            if isinstance(doc, dict):
                return doc
        except ValueError:
            pass
        i = text.find("{", i + 1)
    return None


# ── job state (resume support) ───────────────────────────────────────────

def load_state(job_id: str, state_dir: Path = STATE_DIR) -> dict:
    p = state_dir / f"{job_id}.json"
    if p.exists():
        state = json.loads(p.read_text(encoding="utf-8"))
    else:
        state = {"job_id": job_id}
    state.setdefault("completed_stages", [])
    state.setdefault("timings", {})
    state.setdefault("skipped", {})
    return state


def save_state(state: dict, state_dir: Path = STATE_DIR) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    p = state_dir / f"{state['job_id']}.json"
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, p)


# ── misc helpers ─────────────────────────────────────────────────────────

def ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def safe_print(line: str) -> None:
    try:
        print(line, flush=True)
    except UnicodeEncodeError:  # legacy console codepages
        enc = sys.stdout.encoding or "utf-8"
        print(line.encode(enc, "replace").decode(enc), flush=True)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_rev(repo_root: Path) -> str:
    try:
        r = subprocess.run(["git", "-C", str(repo_root), "rev-parse", "HEAD"],
                           capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return "unknown"


def detect_gpu() -> str:
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().splitlines()[0].strip()
    except Exception:
        pass
    return "unknown"


def kill_tree(proc: subprocess.Popen | None) -> None:
    """Terminate a child and its whole process tree (train spawns YOLOv6)."""
    if proc is None or proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       capture_output=True)
    else:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def purge_fisheye_copies(data_root: Path) -> int:
    """Delete baked *_fe images/labels so the augment stage is re-entrant
    (a naive re-run would warp the previous run's copies into *_fe_fe)."""
    n = 0
    for sub in ("images", "labels"):
        d = data_root / "radius" / "train" / sub
        if not d.is_dir():
            continue
        for p in list(d.iterdir()):
            if p.stem.endswith("_fe"):
                p.unlink()
                n += 1
    return n


class RunnerLog:
    """Timestamped daemon log — console + logs/runner.log (a scheduled task
    has no console; the file is the source of truth)."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._lock = threading.Lock()

    def __call__(self, msg: str) -> None:
        line = f"[{ts()}] {msg}"
        with self._lock:
            safe_print(line)
            with self._path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")


# ── platform client ──────────────────────────────────────────────────────

class PlatformClient:
    """Thin JSON-over-HTTP client. `transport` is injectable for tests:
    transport(method, url, body_bytes, headers, timeout) -> (status, body)."""

    def __init__(self, cfg: Config, transport=None):
        self.base = cfg.platform_url
        self._token = cfg.token
        self._transport = transport or self._urllib_transport

    @staticmethod
    def _urllib_transport(method, url, body, headers, timeout):
        req = urllib.request.Request(url, data=body, method=method)
        for k, v in headers.items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            data = e.read()
            e.close()
            return e.code, data

    def _post_json(self, path: str, payload: dict, timeout: float = 30):
        headers = {"Authorization": f"Bearer {self._token}",
                   "Content-Type": "application/json"}
        return self._transport("POST", self.base + path,
                               json.dumps(payload).encode("utf-8"),
                               headers, timeout)

    def claim(self, runner_id: str, hostname: str, gpu: str) -> dict | None:
        status, body = self._post_json("/api/agent/runner/claim", {
            "runner_id": runner_id, "hostname": hostname,
            "gpu": gpu, "capabilities": CAPABILITIES})
        if status == 204:
            return None
        if status == 200:
            return json.loads(body).get("job") or None
        raise RuntimeError(f"claim -> HTTP {status}: {body[:300]!r}")

    def progress(self, job_id: str, payload: dict) -> bool:
        status, body = self._post_json(
            f"/api/agent/runner/jobs/{job_id}/progress", payload)
        if status == 409:
            raise Cancelled(f"job {job_id} cancelled/reassigned (progress -> 409)")
        return 200 <= status < 300

    def artifact_url(self, job_id: str, filename: str,
                     content_type: str, kind: str) -> dict:
        status, body = self._post_json(
            f"/api/agent/runner/jobs/{job_id}/artifact-url",
            {"filename": filename, "content_type": content_type, "kind": kind})
        if not (200 <= status < 300):
            raise RuntimeError(f"artifact-url({filename}) -> HTTP {status}: "
                               f"{body[:300]!r}")
        return json.loads(body)

    def upload(self, upload_url: str, file_path: Path, content_type: str) -> None:
        data = file_path.read_bytes()
        headers = {"Content-Type": content_type}
        # Bearer only when uploading back to the platform host — never leak
        # the token to external (presigned) storage endpoints.
        if urlsplit(upload_url).netloc == urlsplit(self.base).netloc:
            headers["Authorization"] = f"Bearer {self._token}"
        status, body = self._transport("PUT", upload_url, data, headers, 900)
        if not (200 <= status < 300):
            raise RuntimeError(f"upload {file_path.name} -> HTTP {status}: "
                               f"{body[:300]!r}")

    def complete(self, job_id: str, payload: dict,
                 delays: list[float] | None = None) -> None:
        last = None
        for d in (COMPLETE_RETRY_DELAYS if delays is None else delays):
            if d:
                time.sleep(d)
            try:
                status, body = self._post_json(
                    f"/api/agent/runner/jobs/{job_id}/complete", payload,
                    timeout=60)
                if 200 <= status < 300:
                    return
                last = f"HTTP {status}: {body[:300]!r}"
            except Exception as e:
                last = repr(e)
        raise RuntimeError(f"complete({job_id}) failed after retries: {last}")


# ── job execution ────────────────────────────────────────────────────────

class JobRunner:
    """Executes one claimed job: stages -> artifacts -> complete.

    Guarantees: a claimed job always ends in complete(succeeded|failed),
    except cancellation (409) and operator ctrl-c — both of which save the
    state file so a re-claim resumes past the completed stages.
    """

    def __init__(self, cfg: Config, client: PlatformClient, job: dict,
                 runner_log, state_dir: Path = STATE_DIR,
                 log_dir: Path = LOG_DIR):
        self.cfg = cfg
        self.client = client
        self.job = job
        self.job_id = str(job["id"])
        spec = job.get("spec") or {}
        self.spec = json.loads(spec) if isinstance(spec, str) else spec
        self.radius_dir = cfg.repo_root / "training" / "radius"
        self.state_dir = state_dir
        self.state = load_state(self.job_id, state_dir)
        self.eval_result: dict | None = None
        self._rlog = runner_log
        log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = log_dir / f"{self.job_id}.log"
        self._logf = self.log_path.open("a", encoding="utf-8")
        self.tail = LogTail()
        self._snap = {"stage": "claimed", "stage_pct": None,
                      "message": None, "metrics": None}
        self._snap_lock = threading.Lock()
        self._proc_lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self.cancelled = threading.Event()
        self._hb_stop = threading.Event()

    # ── logging ──
    def log(self, msg: str) -> None:
        """Runner-level job event -> console + runner.log + job log + tail."""
        self._rlog(f"job {self.job_id}: {msg}")
        self._logf.write(f"[{ts()}] {msg}\n")
        self._logf.flush()
        self.tail.add(msg)

    # ── progress snapshot ──
    def _set_stage(self, stage: str, pct: float | None = None,
                   message: str | None = None) -> None:
        with self._snap_lock:
            if stage != self._snap["stage"]:
                self._snap["metrics"] = None
            self._snap["stage"] = stage
            self._snap["stage_pct"] = pct
            self._snap["message"] = message

    def _apply_marker(self, m: dict) -> None:
        with self._snap_lock:
            if "stage_pct" in m:
                self._snap["stage_pct"] = m["stage_pct"]
            if m.get("message"):
                self._snap["message"] = str(m["message"])[:300]
            if isinstance(m.get("metrics"), dict):
                self._snap["metrics"] = m["metrics"]

    def post_progress(self) -> None:
        """Send the current snapshot. 409 -> flag cancel + kill children."""
        with self._snap_lock:
            payload: dict = {"stage": self._snap["stage"]}
            if self._snap["stage_pct"] is not None:
                payload["stage_pct"] = self._snap["stage_pct"]
            if self._snap["message"]:
                payload["message"] = self._snap["message"]
            if self._snap["metrics"]:
                payload["metrics"] = self._snap["metrics"]
        tail = self.tail.get()
        if tail:
            payload["log_tail"] = tail
        try:
            self.client.progress(self.job_id, payload)
        except Cancelled as e:
            self.log(f"CANCELLED by platform: {e}")
            self.cancelled.set()
            with self._proc_lock:
                kill_tree(self._proc)
        except Exception as e:
            self._rlog(f"job {self.job_id}: progress post failed "
                       f"(non-fatal, will retry on heartbeat): {e}")

    def _heartbeat(self) -> None:
        while not self._hb_stop.wait(HEARTBEAT_SECONDS):
            if self.cancelled.is_set():
                return
            self.post_progress()

    def _check_cancelled(self) -> None:
        if self.cancelled.is_set():
            raise Cancelled(f"job {self.job_id} cancelled by platform")

    # ── subprocess driving ──
    def _run_child(self, argv: list[str],
                   collect_output: bool = False) -> list[str] | None:
        self._check_cancelled()
        self.log("+ " + " ".join(argv))
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        proc = subprocess.Popen(
            argv, cwd=str(self.radius_dir),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", env=env)
        with self._proc_lock:
            self._proc = proc
        dedupe = BarDeduper()
        collected: list[str] | None = [] if collect_output else None
        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.rstrip("\r\n")
                marker = parse_progress_marker(line)
                if marker is not None:
                    self._apply_marker(marker)
                if collected is not None:
                    collected.append(line)
                if dedupe.should_log(line):
                    self._logf.write(line + "\n")
                    self._logf.flush()
                    self.tail.add(line)
            rc = proc.wait()
        except KeyboardInterrupt:
            kill_tree(proc)
            raise
        finally:
            with self._proc_lock:
                self._proc = None
            self._logf.flush()
        if self.cancelled.is_set():
            raise Cancelled(f"job {self.job_id} cancelled while running "
                            f"{argv[1] if len(argv) > 1 else argv[0]}")
        if rc != 0:
            raise StageFailed(f"`{' '.join(argv[1:])}` exited with code {rc}")
        return collected

    # ── stages ──
    def run_stage(self, stage: str) -> None:
        self._set_stage(stage, pct=0.0, message="starting")
        self.post_progress()
        if stage == "eval":
            self._run_eval_stage()
            return
        if stage == "augment":
            purged = purge_fisheye_copies(self.cfg.data_root)
            if purged:
                self.log(f"augment: purged {purged} stale *_fe files "
                         f"(re-entrancy)")
        for argv in stage_commands(stage, self.spec, self.cfg.python_exe,
                                   self.radius_dir):
            self._run_child(argv)

    def _checkpoint(self) -> str:
        return str(self.spec.get("checkpoint")
                   or self.radius_dir / "runs" / "radius_s2" / "weights"
                   / "best_ckpt.pt")

    def _run_eval_stage(self) -> None:
        """Predictions + eval gate — or an HONEST skip.

        eval_radius.py consumes a predictions JSONL that a producer script
        must build at the deployed preprocessing. Until eval/predict_radius.py
        exists (convention: `predict_radius.py <ckpt> --out <preds.jsonl>`),
        this stage reports SKIPPED rather than inventing a fake gate.
        """
        predict = self.radius_dir / "eval" / "predict_radius.py"
        gt_dir = self.cfg.data_root / "eval" / "bench"
        skip = None
        if not predict.exists():
            skip = ("SKIPPED: predictions producer eval/predict_radius.py "
                    "does not exist yet — no gate was run (do not treat "
                    "this as a pass)")
        elif not (gt_dir / "labels").is_dir():
            skip = f"SKIPPED: no eval ground truth at {gt_dir}"
        if skip:
            self.log(f"eval: {skip}")
            self.state["skipped"]["eval"] = skip
            self._set_stage("eval", pct=100.0, message=skip)
            self.post_progress()
            return
        preds = self.state_dir / f"{self.job_id}_preds.jsonl"
        self._run_child([self.cfg.python_exe, str(predict),
                         self._checkpoint(), "--out", str(preds)])
        out = self._run_child(
            [self.cfg.python_exe, str(self.radius_dir / "eval" / "eval_radius.py"),
             str(preds), "--gt", str(gt_dir)],
            collect_output=True)
        self.eval_result = parse_trailing_json(out or [])
        if self.eval_result is not None:
            (self.state_dir / f"{self.job_id}_eval.json").write_text(
                json.dumps(self.eval_result, indent=2), encoding="utf-8")
        else:
            self.log("eval: WARNING — could not parse eval JSON from output")

    # ── artifacts + completion ──
    def _upload(self, path: Path, content_type: str, kind: str) -> str:
        doc = self.client.artifact_url(self.job_id, path.name,
                                       content_type, kind)
        self.client.upload(doc["upload_url"], path, content_type)
        storage_path = doc.get("storage_path", "")
        self.log(f"upload: {path.name} ({path.stat().st_size} bytes) "
                 f"-> {storage_path}")
        return storage_path

    def _model_payload(self, version: str, sidecar: dict, blob: Path,
                       blob_sha: str, storage_path: str) -> dict:
        size = sidecar.get("nn_config", {}).get("input_size", "640x384")
        w, h = (int(x) for x in size.split("x"))
        manifest = self.cfg.data_root / "MANIFEST.json"
        meta = {
            "dataset_manifest_hash":
                sha256_file(manifest) if manifest.exists() else None,
            "git_rev": git_rev(self.cfg.repo_root),
            "stages_run": list(self.state["completed_stages"]),
            "timings": dict(self.state["timings"]),
            "runner_id": self.cfg.runner_id,
        }
        if self.state.get("skipped"):
            meta["skipped_stages"] = self.state["skipped"]
        return {
            "model_id": (self.job.get("model_id")
                         or self.spec.get("model_id") or f"radius-{version}"),
            "display_name": (self.spec.get("display_name")
                             or f"GridFront Radius {version}"),
            "family": sidecar.get("radius", {}).get("family", "yolov6n"),
            "input_width": w,
            "input_height": h,
            "classes": sidecar.get("mappings", {}).get("labels", []),
            "blob_sha256": blob_sha,
            "size_bytes": blob.stat().st_size,
            "storage_path": storage_path,
            "training_meta": meta,
        }

    def _finish(self, requested: list[str]) -> None:
        payload: dict = {"status": "succeeded"}
        if "export" in requested:
            self._set_stage("upload", pct=0.0, message="uploading artifacts")
            self.post_progress()
            self._check_cancelled()
            version = str(self.spec.get("version") or "v1")
            models = self.cfg.repo_root / "models"
            blob = models / f"radius-{version}.blob"
            sidecar_path = models / f"radius-{version}.json"
            if not blob.exists() or not sidecar_path.exists():
                raise StageFailed(
                    f"export finished but {blob.name} / {sidecar_path.name} "
                    f"not found in {models}")
            blob_sha = sha256_file(blob)
            storage_path = self._upload(blob, "application/octet-stream", "blob")
            self._upload(sidecar_path, "application/json", "sidecar")
            eval_path = self.state_dir / f"{self.job_id}_eval.json"
            if self.eval_result is None and eval_path.exists():
                # resumed past eval this claim — reuse the stored result
                self.eval_result = json.loads(
                    eval_path.read_text(encoding="utf-8"))
            if eval_path.exists():
                self._upload(eval_path, "application/json", "eval")
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            payload["model"] = self._model_payload(
                version, sidecar, blob, blob_sha, storage_path)
        if self.eval_result is not None:
            payload["eval"] = self.eval_result
        self.client.complete(self.job_id, payload)

    def _fail(self, stage: str, exc: Exception) -> None:
        tail = self.tail.get()
        err = f"stage '{stage}': {type(exc).__name__}: {exc}"
        self.log(f"FAILED — {err}")
        payload = {
            "status": "failed",
            "error": (err + ("\n--- log tail ---\n" + tail if tail else ""))[:8000],
        }
        try:
            self.client.complete(self.job_id, payload)
        except Exception as e2:
            self._rlog(f"job {self.job_id}: COULD NOT report failure to the "
                       f"platform ({e2}) — the job will look stalled; see "
                       f"{self.log_path}")

    # ── orchestration ──
    def run(self) -> None:
        hb = threading.Thread(target=self._heartbeat, daemon=True,
                              name=f"heartbeat-{self.job_id}")
        stage = "claim"
        try:
            kind = self.job.get("kind")
            if kind not in (None, *CAPABILITIES):
                raise JobSpecError(f"unsupported job kind {kind!r} "
                                   f"(capabilities: {CAPABILITIES})")
            requested, remaining = plan_stages(
                self.spec, self.state["completed_stages"])
            done = [s for s in requested if s not in remaining]
            self.log(f"claimed: kind={kind or 'radius_base'} "
                     f"model_id={self.job.get('model_id')} stages={requested}"
                     + (f" (resume — already done: {done})" if done else ""))
            self.state["spec"] = self.spec
            save_state(self.state, self.state_dir)
            hb.start()
            self._set_stage(remaining[0] if remaining else "upload",
                            message=f"claimed by {self.cfg.runner_id}; "
                                    f"plan={requested} resume_skip={done}")
            self.post_progress()
            for stage in remaining:
                self._check_cancelled()
                t0 = time.monotonic()
                self.run_stage(stage)
                secs = round(time.monotonic() - t0, 1)
                self.state["timings"][stage] = secs
                self.state["completed_stages"].append(stage)
                save_state(self.state, self.state_dir)
                self._set_stage(stage, pct=100.0, message=f"done in {secs}s")
                self.post_progress()
                self.log(f"stage {stage}: done in {secs}s")
            stage = "upload"
            self._finish(requested)
            self.log("job succeeded")
        except Cancelled as e:
            self.log(f"cancelled: {e} — children killed, state saved in case "
                     f"the platform re-offers the job")
        except KeyboardInterrupt:
            self.log("interrupted by operator (ctrl-c) — state saved; the job "
                     "resumes past completed stages on the next claim")
            with self._snap_lock:
                self._snap["message"] = ("runner interrupted by operator; "
                                         "state saved for resume")
            try:
                self.post_progress()
            except Exception:
                pass
            raise
        except Exception as e:
            self._fail(stage, e)
        finally:
            self._hb_stop.set()
            if hb.is_alive():
                hb.join(timeout=5)
            self._logf.close()


# ── daemon loop ──────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="GridFront Radius training runner daemon")
    ap.add_argument("--config", type=Path, default=HERE / "runner.toml")
    ap.add_argument("--once", action="store_true",
                    help="process at most one job, then exit")
    ap.add_argument("--check-config", action="store_true",
                    help="validate runner.toml and exit")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    if args.check_config:
        print(f"runner.toml OK — runner_id={cfg.runner_id} "
              f"platform={cfg.platform_url} repo_root={cfg.repo_root} "
              f"python={cfg.python_exe} poll={cfg.poll_interval}s")
        return 0

    log = RunnerLog(LOG_DIR / "runner.log")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    hostname = socket.gethostname()
    gpu = detect_gpu()
    client = PlatformClient(cfg)
    log(f"radius runner up — id={cfg.runner_id} host={hostname} gpu={gpu} "
        f"platform={cfg.platform_url} poll={cfg.poll_interval}s "
        f"repo={cfg.repo_root} python={cfg.python_exe}")

    idle_logged = False
    try:
        while True:
            try:
                job = client.claim(cfg.runner_id, hostname, gpu)
            except Exception as e:
                log(f"claim failed ({e}) — retrying in {cfg.poll_interval}s")
                time.sleep(cfg.poll_interval)
                continue
            if job is None:
                if not idle_logged:
                    log("no queued jobs — polling")
                    idle_logged = True
                time.sleep(cfg.poll_interval)
                continue
            idle_logged = False
            JobRunner(cfg, client, job, log).run()
            if args.once:
                return 0
    except KeyboardInterrupt:
        log("ctrl-c — shutting down cleanly (any claimed-job state is saved "
            "for resume)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
