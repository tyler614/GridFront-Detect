# Radius training runner

The daemon on the GPU PC that turns platform-queued training jobs into
`models/radius-*.blob`. It polls `platform.gridfront.io`, claims a job,
runs the `training/radius` pipeline stages as subprocesses, streams
progress + log tails back, uploads the blob/sidecar/eval artifacts, and
reports completion. `runner.py` is stdlib-only (Python 3.11+) — the
pipeline stages carry the heavy deps, not the runner.

## Install (on the gaming PC)

Prereqs: the HANDOVER.md Setup block (venv + torch + requirements) and the
Step-1 manual dataset downloads — jobs assume `data/raw/` is populated.

```powershell
cd scout\training\radius\runner
copy runner.toml.example runner.toml     # then EDIT: platform_url, token, runner_id
.\install_runner.ps1                     # from an elevated PowerShell
```

`install_runner.ps1` validates the config, disables sleep/hibernate on AC,
registers a Task Scheduler task (runs at logon + boot, restarts on failure),
and starts it. To run in the foreground instead (first supervised run):

```powershell
..\.venv\Scripts\python.exe runner.py --once
```

## runner.toml

| key | required | meaning |
|---|---|---|
| `platform_url` | yes | e.g. `https://platform.gridfront.io`, no trailing slash |
| `token` | yes | `RADIUS_RUNNER_TOKEN` — sent as `Authorization: Bearer` |
| `runner_id` | yes | stable machine id, e.g. `gaming-pc-3060` |
| `repo_root` | no | scout checkout root (default: auto-detected from this file) |
| `python_exe` | no | python for the stages (default: the one running runner.py — use the training venv) |
| `poll_interval` | no | seconds between claim polls (default 30) |
| `data_root` | no | `training/radius/data` real location if junctioned elsewhere |

`runner.toml` is gitignored — it holds the token. Never commit it.

## What a job looks like

Claim returns `{job: {id, kind, model_id, spec}}`. Spec fields the runner
understands (all optional):

```jsonc
{
  "stages": ["remap", "complete_labels", "augment",
             "train_s1", "train_s2", "eval", "export"],  // default: all, in this order
  "version": "v1",                    // export_blob.py --version; default v1
  "display_name": "GridFront Radius v1",
  "augment_frac": 0.4,                // augment_fisheye.py --frac
  "checkpoint": "runs/.../best_ckpt.pt",  // eval/export ckpt override
  "stage_args": {"complete_labels": ["--min-score", "0.5"]}  // extra argv per stage
}
```

## Stages

Each stage runs as a subprocess with cwd `training/radius` and the config's
`python_exe`. Child stdout/stderr streams line-by-line into
`logs/{job_id}.log` (tqdm redraw spam collapsed to ~1 line per percent);
the last 40 lines ride along on every progress post.

| stage | command(s) | re-runnable after a crash? |
|---|---|---|
| `remap` | `datasets.py remap` | yes — rebuilds `data/radius` from scratch |
| `complete_labels` | `complete_labels.py --split train`, then `--split val` | yes — a re-run's duplicate teacher boxes land on the previous run's boxes and are dropped by the IoU>0.6 rule |
| `augment` | `augment_fisheye.py --frac <f>` | yes — the runner deletes stale `*_fe` copies first |
| `train_s1` | `train_radius.py stage1` | restartable, not resumable — a re-run starts from epoch 0 |
| `train_s2` | `train_radius.py stage2` | same |
| `eval` | see below | yes |
| `export` | `export_blob.py <ckpt> --version <v>` | yes — recompiles the blob |

**eval is currently an honest SKIP.** `eval/eval_radius.py` consumes a
predictions JSONL, and the producer script does not exist yet. Until
`eval/predict_radius.py` lands (convention: `predict_radius.py <ckpt> --out
<preds.jsonl>`, deployed 640x384 stretch preprocessing) — or if
`data/eval/bench/labels` is absent — the stage posts `SKIPPED: ...` and the
skip reason is recorded in `training_meta.skipped_stages`. No fake gate is
invented; gate the model manually per HANDOVER.md Step 4 before flashing.

## Progress + heartbeat

Progress posts fire on stage transitions, and a heartbeat thread repeats the
last known stage every 60s during long stages. Stage percentages come from
`PROGRESS {json}` marker lines that `train_radius.py` (per epoch) and
`complete_labels.py` (per 25 images) print; the runner parses
`stage_pct` / `message` / `metrics` from them.

A `409` on any progress post means the platform cancelled/reassigned the
job: the runner kills the stage's whole process tree and goes back to
polling. No `complete` is sent for a cancelled job.

## Resume

`state/{job_id}.json` records completed stages + timings. If the runner
crashes or the machine reboots mid-job and the platform offers the same job
id again, completed stages are skipped and execution continues from the
first unfinished one (see the re-runnable column above for what a
mid-stage crash costs). Delete the state file to force a full re-run.

Ctrl-c is graceful: the child tree is killed, a final progress message is
posted, state is saved, and the runner exits without completing the job.

## Completion

After `export`, the runner sha256s the blob, uploads blob (`kind=blob`) +
sidecar (`kind=sidecar`) + eval JSON (`kind=eval`, when eval ran) via
artifact-url/PUT, then posts `complete` with the model payload — classes and
input size read from the `export_blob.py` sidecar, `training_meta` carrying
`dataset_manifest_hash` (sha256 of `data/MANIFEST.json`), `git_rev`,
`stages_run`, `timings`, and any skipped-stage reasons.

Any stage failure posts `complete{status:'failed'}` with the stage, the
exception, and the log tail. A claimed job is never left silent — the only
exceptions are platform-initiated cancellation and operator ctrl-c, and if
the platform itself is unreachable for the entire complete retry ladder
(logged loudly in `logs/runner.log`; state is kept so a re-claim resumes).

## Tests

```powershell
python -m unittest discover -s tests -v      # from training/radius/runner
```

Pure-logic only (stage planning, resume decisions, log-tail caps, marker
parsing, client behavior with a mocked transport) — nothing talks to the
network or spawns the pipeline.
