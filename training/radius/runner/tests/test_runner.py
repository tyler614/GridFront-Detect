"""Unit tests for runner.py — pure logic only, HTTP mocked, no subprocesses.

Run from training/radius/runner:
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import runner  # noqa: E402


# ── stage sequencing ─────────────────────────────────────────────────────

class PlanStagesTest(unittest.TestCase):
    def test_default_full_sequence(self):
        requested, remaining = runner.plan_stages({}, [])
        self.assertEqual(requested, runner.DEFAULT_STAGES)
        self.assertEqual(remaining, runner.DEFAULT_STAGES)

    def test_spec_subset_order_preserved(self):
        spec = {"stages": ["train_s2", "eval", "export"]}
        requested, remaining = runner.plan_stages(spec, [])
        self.assertEqual(requested, ["train_s2", "eval", "export"])
        self.assertEqual(remaining, requested)

    def test_unknown_stage_rejected(self):
        with self.assertRaises(runner.JobSpecError):
            runner.plan_stages({"stages": ["remap", "train_s3"]}, [])

    def test_resume_skips_completed(self):
        _, remaining = runner.plan_stages(
            {}, ["remap", "complete_labels", "augment"])
        self.assertEqual(remaining, ["train_s1", "train_s2", "eval", "export"])

    def test_resume_all_done_leaves_nothing(self):
        _, remaining = runner.plan_stages({}, list(runner.DEFAULT_STAGES))
        self.assertEqual(remaining, [])

    def test_completed_stage_not_in_plan_is_ignored(self):
        spec = {"stages": ["export"]}
        requested, remaining = runner.plan_stages(spec, ["remap"])
        self.assertEqual(remaining, ["export"])


class StageCommandsTest(unittest.TestCase):
    RADIUS = Path("C:/repo/training/radius")

    def cmds(self, stage, spec=None):
        return runner.stage_commands(stage, spec or {}, "py", self.RADIUS)

    def test_remap(self):
        self.assertEqual(self.cmds("remap"), [["py", "datasets.py", "remap"]])

    def test_complete_labels_runs_both_splits(self):
        cmds = self.cmds("complete_labels")
        self.assertEqual(len(cmds), 2)
        self.assertIn("train", cmds[0])
        self.assertIn("val", cmds[1])

    def test_augment_frac_from_spec(self):
        cmds = self.cmds("augment", {"augment_frac": 0.5})
        self.assertEqual(cmds, [["py", "augment_fisheye.py", "--frac", "0.5"]])

    def test_export_version_and_checkpoint_from_spec(self):
        cmds = self.cmds("export", {"version": "v2", "checkpoint": "x/best.pt"})
        self.assertEqual(
            cmds, [["py", "export_blob.py", "x/best.pt", "--version", "v2"]])

    def test_export_defaults(self):
        cmds = self.cmds("export")
        self.assertEqual(cmds[0][-1], "v1")
        self.assertIn("best_ckpt.pt", cmds[0][2])

    def test_stage_args_appended(self):
        spec = {"stage_args": {"complete_labels": ["--min-score", 0.5]}}
        cmds = self.cmds("complete_labels", spec)
        self.assertEqual(cmds[0][-2:], ["--min-score", "0.5"])

    def test_eval_not_a_command_stage(self):
        with self.assertRaises(ValueError):
            self.cmds("eval")

    def test_unknown_stage(self):
        with self.assertRaises(runner.JobSpecError):
            self.cmds("frobnicate")


# ── progress markers ─────────────────────────────────────────────────────

class MarkerTest(unittest.TestCase):
    def test_valid_marker(self):
        m = runner.parse_progress_marker(
            'PROGRESS {"stage_pct": 42.5, "message": "ep 51", '
            '"metrics": {"epoch": 51}}')
        self.assertEqual(m["stage_pct"], 42.5)
        self.assertEqual(m["metrics"], {"epoch": 51})

    def test_pct_clamped(self):
        self.assertEqual(
            runner.parse_progress_marker('PROGRESS {"stage_pct": 140}')["stage_pct"],
            100.0)
        self.assertEqual(
            runner.parse_progress_marker('PROGRESS {"stage_pct": -3}')["stage_pct"],
            0.0)

    def test_non_numeric_pct_dropped(self):
        m = runner.parse_progress_marker(
            'PROGRESS {"stage_pct": "half", "message": "x"}')
        self.assertNotIn("stage_pct", m)
        self.assertEqual(m["message"], "x")

    def test_plain_line_is_not_marker(self):
        self.assertIsNone(runner.parse_progress_marker("Epoch 3/119 done"))

    def test_invalid_json_ignored(self):
        self.assertIsNone(runner.parse_progress_marker("PROGRESS {oops"))

    def test_non_dict_json_ignored(self):
        self.assertIsNone(runner.parse_progress_marker("PROGRESS [1, 2]"))


class TrailingJsonTest(unittest.TestCase):
    def test_finds_eval_json_after_noise(self):
        lines = ["loading preds...", "some { not json", "{",
                 '  "images": 10,', '  "band_recall": {"0-5m (red)": 1.0}',
                 "}", "PASS"]
        doc = runner.parse_trailing_json(lines)
        self.assertEqual(doc["images"], 10)

    def test_none_when_absent(self):
        self.assertIsNone(runner.parse_trailing_json(["no json here"]))


# ── log tail ─────────────────────────────────────────────────────────────

class LogTailTest(unittest.TestCase):
    def test_caps_line_count(self):
        t = runner.LogTail(max_lines=40)
        for i in range(100):
            t.add(f"line {i}")
        lines = t.get().splitlines()
        self.assertEqual(len(lines), 40)
        self.assertEqual(lines[0], "line 60")
        self.assertEqual(lines[-1], "line 99")

    def test_caps_line_length(self):
        t = runner.LogTail(max_line_chars=10)
        t.add("x" * 50)
        self.assertEqual(t.get(), "x" * 10 + " ...[truncated]")

    def test_strips_newlines(self):
        t = runner.LogTail()
        t.add("hello\r\n")
        self.assertEqual(t.get(), "hello")


class BarDeduperTest(unittest.TestCase):
    def test_same_percent_suppressed(self):
        d = runner.BarDeduper()
        self.assertTrue(d.should_log(" 12%|##        | 120/1000"))
        self.assertFalse(d.should_log(" 12%|##        | 121/1000"))
        self.assertTrue(d.should_log(" 13%|##        | 130/1000"))

    def test_normal_lines_always_logged(self):
        d = runner.BarDeduper()
        self.assertTrue(d.should_log("epoch summary"))
        self.assertTrue(d.should_log("epoch summary"))


# ── state file / resume ──────────────────────────────────────────────────

class StateTest(unittest.TestCase):
    def test_fresh_state_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = runner.load_state("job-1", Path(tmp))
        self.assertEqual(s["completed_stages"], [])
        self.assertEqual(s["timings"], {})
        self.assertEqual(s["skipped"], {})

    def test_roundtrip_and_resume_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            s = runner.load_state("job-2", state_dir)
            s["completed_stages"] += ["remap", "complete_labels"]
            s["timings"]["remap"] = 12.3
            runner.save_state(s, state_dir)
            s2 = runner.load_state("job-2", state_dir)
            self.assertEqual(s2["completed_stages"], ["remap", "complete_labels"])
            self.assertEqual(s2["timings"]["remap"], 12.3)
            _, remaining = runner.plan_stages({}, s2["completed_stages"])
            self.assertEqual(remaining[0], "augment")

    def test_legacy_state_gets_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "job-3.json"
            p.write_text('{"job_id": "job-3"}', encoding="utf-8")
            s = runner.load_state("job-3", Path(tmp))
            self.assertEqual(s["completed_stages"], [])


# ── platform client (transport mocked) ───────────────────────────────────

def make_cfg(tmp: Path) -> runner.Config:
    return runner.Config(
        platform_url="https://plat.test", token="tok-123", runner_id="r1",
        repo_root=tmp, python_exe="py", poll_interval=1, data_root=tmp)


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, body, headers, timeout):
        self.calls.append((method, url, body, headers))
        return self.responses.pop(0)


class ClientTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = make_cfg(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def client(self, *responses):
        t = FakeTransport(responses)
        return runner.PlatformClient(self.cfg, transport=t), t

    def test_claim_204_means_no_job(self):
        c, t = self.client((204, b""))
        self.assertIsNone(c.claim("r1", "host", "gpu"))
        method, url, body, headers = t.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://plat.test/api/agent/runner/claim")
        self.assertEqual(headers["Authorization"], "Bearer tok-123")
        doc = json.loads(body)
        self.assertEqual(doc["capabilities"], ["radius_base"])

    def test_claim_200_returns_job(self):
        job = {"id": "j1", "kind": "radius_base", "model_id": "radius-v1",
               "spec": {}}
        c, _ = self.client((200, json.dumps({"job": job}).encode()))
        self.assertEqual(c.claim("r1", "h", "g"), job)

    def test_claim_5xx_raises(self):
        c, _ = self.client((500, b"boom"))
        with self.assertRaises(RuntimeError):
            c.claim("r1", "h", "g")

    def test_progress_409_raises_cancelled(self):
        c, _ = self.client((409, b""))
        with self.assertRaises(runner.Cancelled):
            c.progress("j1", {"stage": "train_s1"})

    def test_progress_200_ok(self):
        c, t = self.client((200, b"{}"))
        self.assertTrue(c.progress("j1", {"stage": "remap", "stage_pct": 5}))
        self.assertIn("/jobs/j1/progress", t.calls[0][1])

    def test_artifact_url(self):
        doc = {"upload_url": "https://s3.test/x", "storage_path": "a/b.blob"}
        c, t = self.client((200, json.dumps(doc).encode()))
        got = c.artifact_url("j1", "radius-v1.blob",
                             "application/octet-stream", "blob")
        self.assertEqual(got, doc)
        body = json.loads(t.calls[0][2])
        self.assertEqual(body["kind"], "blob")

    def test_upload_no_bearer_to_foreign_host(self):
        c, t = self.client((200, b""))
        f = Path(self.tmp.name) / "a.bin"
        f.write_bytes(b"data")
        c.upload("https://s3.other.test/bucket/a.bin", f,
                 "application/octet-stream")
        method, url, body, headers = t.calls[0]
        self.assertEqual(method, "PUT")
        self.assertEqual(body, b"data")
        self.assertNotIn("Authorization", headers)

    def test_upload_bearer_kept_for_platform_host(self):
        c, t = self.client((200, b""))
        f = Path(self.tmp.name) / "a.bin"
        f.write_bytes(b"data")
        c.upload("https://plat.test/upload/a.bin", f, "application/json")
        self.assertEqual(t.calls[0][3]["Authorization"], "Bearer tok-123")

    def test_complete_retries_then_succeeds(self):
        c, t = self.client((500, b"err"), (200, b"{}"))
        c.complete("j1", {"status": "succeeded"}, delays=[0, 0])
        self.assertEqual(len(t.calls), 2)

    def test_complete_exhausted_raises(self):
        c, _ = self.client((500, b"e"), (500, b"e"))
        with self.assertRaises(RuntimeError):
            c.complete("j1", {"status": "failed"}, delays=[0, 0])


# ── fisheye purge (re-entrancy helper) ───────────────────────────────────

class PurgeFisheyeTest(unittest.TestCase):
    def test_only_fe_copies_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            imgs = root / "radius" / "train" / "images"
            lbls = root / "radius" / "train" / "labels"
            imgs.mkdir(parents=True)
            lbls.mkdir(parents=True)
            (imgs / "a.jpg").write_bytes(b"x")
            (imgs / "a_fe.jpg").write_bytes(b"x")
            (lbls / "a.txt").write_text("0 .5 .5 .1 .1")
            (lbls / "a_fe.txt").write_text("0 .5 .5 .1 .1")
            n = runner.purge_fisheye_copies(root)
            self.assertEqual(n, 2)
            self.assertTrue((imgs / "a.jpg").exists())
            self.assertFalse((imgs / "a_fe.jpg").exists())
            self.assertTrue((lbls / "a.txt").exists())

    def test_missing_dirs_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(runner.purge_fisheye_copies(Path(tmp)), 0)


if __name__ == "__main__":
    unittest.main()
