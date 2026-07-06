# Radius v1 training — handover for Claude on the gaming PC

**Audience:** a Claude Code session on Tyler's gaming PC (Windows, RTX 3060 12GB).
**Mission:** produce `models/radius-v1.blob` — GridFront's first shippable detection
model for the Scout OAK-D cameras — by running the pipeline in this folder
end-to-end: download license-clean datasets → fix missing labels with a teacher
model → augment → train YOLOv6-N → evaluate → export.
**Written:** 2026-07-05 by the laptop session that built this pipeline.

---

## Context in 60 seconds

GridFront Scout = OAK-D Pro W PoE cameras on construction machines detecting
people/equipment for proximity safety. The old model (`gridfront-scout-v1`) was
deleted: Ultralytics-AGPL weights + non-commercial training data = legally
unshippable, and it performed poorly outdoors anyway (label-poisoned merge,
512×288 input, wrong architecture for the Myriad X chip). Radius v1 is the
license-clean rebuild: **YOLOv6-N 3.0 @ 640×384**, 9 classes
(`person, excavator, wheel-loader, dozer, crane, dump-truck, grader,
compactor, cone`). Full rationale: `README.md` in this folder; program doc:
https://claude.ai/code/artifact/be15870c-9c71-4491-9f84-c58b1b50b9a8

**Hard rules (do not bend):**
1. NEVER train on: ACID, MOCS, CIS, CrowdHuman, FSOCO, VisDrone, FLIR
   (non-commercial licenses). MOCS/SODA are eval-only if obtainable.
2. NEVER use Ultralytics code to train the shipped model (AGPL weights claim).
3. NEVER fine-tune from Meituan's COCO-pretrained checkpoints (weights
   provenance must be 100% ours). Train from scratch.
4. A dataset source merges ONLY if its `license_verified=True` in
   `datasets.py` — flipping that flag requires a human (Tyler) confirming the
   license on the ORIGIN page.

## Setup (once)

```powershell
git clone -b feat/radius https://github.com/tyler614/GridFront-Scout scout
cd scout\training\radius
python -m venv .venv ; .venv\Scripts\activate     # Python 3.11–3.12 (runner needs 3.11+)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements.txt
python -c "import torch; print(torch.cuda.get_device_name(0))"  # expect RTX 3060
```

Disk: need ~100 GB free. Check with Tyler where to put `data/` if C: is tight
(the scripts use `training/radius/data/` — a junction to another drive is fine).

## Runner mode (v1 goes through this)

Production training is TRIGGERED FROM THE PLATFORM, not by hand: a daemon on
this PC polls platform.gridfront.io for queued jobs and drives the exact
pipeline below as subprocesses, streaming progress/logs back and uploading
the blob when done. After the Setup block above and the Step-1 manual
downloads (still required — jobs assume `data/raw/` is populated):

```powershell
cd scout\training\radius\runner
copy runner.toml.example runner.toml     # fill platform_url, token, runner_id
.\install_runner.ps1                     # elevated PowerShell — registers + starts the daemon
```

Watch it: `Get-Content -Wait runner\logs\runner.log` (daemon) and
`runner\logs\<job_id>.log` (per-job pipeline output). A crashed/rebooted
runner resumes a claimed job past its completed stages via
`runner\state\<job_id>.json`. Full operating manual: `runner/README.md`.

The manual step-by-step below remains the fallback/debug path — and is how
you should diagnose any stage the runner reports as failed.

## Step 1 — Downloads (~overnight; Tyler needed for logins)

Ask Tyler to do the three manual downloads (browser logins), landing each in
`training/radius/data/raw/<key>/`:

| key | What Tyler does |
|---|---|
| `mendeley87k` | data.mendeley.com/datasets/rz8723t6d7/2 → free Mendeley/Elsevier login → download all files → unzip here. **This is the backbone (87,766 imgs, CC BY 4.0).** |
| `hardhat` | public.roboflow.com/object-detection/hard-hat-workers → download dataset in **YOLO (txt)** format → unzip here. (Public Domain.) |
| `shel5k` | IEEE DataPort SHEL5K page → free IEEE account → **READ THE LICENSE LINE — must say CC BY**. If yes: download, unzip here, then set `license_verified=True` for shel5k in `datasets.py`. If not CC BY: skip the source entirely. |

Scripted (no login): `python datasets.py download-openimages` (~30k far-person
images via fiftyone, several GB).

**Known scaffold gap you must close:** after mendeley87k unzips, open its
classes/annotation format and complete the `label_map` for the `mendeley87k`
Source in `datasets.py` — the map committed there is a best-guess of the class
names; align it to the real ones (12 machinery types → our taxonomy; unmapped
→ None). Same check for hardhat/shel5k label names. The raw layouts vary —
`_remap_source()` expects `images/` + `labels/` YOLO-txt; adapt the code if a
source unzips differently (that's expected scaffold work, commit your fixes).

Then: `python datasets.py remap` → builds `data/radius/{train,val}` +
`completion_todo.json`. Run `python datasets.py stats` and sanity-check class
counts (person should be tens of thousands; cone will be small — that's a
known gap, see "Optional cones" below).

## Step 2 — Teacher label completion (GPU, overnight)

The single most important step: the equipment datasets have unlabeled people
(and vice versa), which is what poisoned the old model.

```powershell
pip install autodistill autodistill-grounded-sam-2
python complete_labels.py --split train    # ~2-4 img/s on the 3060 → 8-16h
python complete_labels.py --split val
python complete_labels.py --audit          # renders 200 samples to data/radius/audit_render/
```

Have Tyler (or judge yourself, conservatively) flip through the audit renders:
teacher person-boxes should be tight; machine-class pseudo-labels
(grader vs dozer especially) are the error-prone ones — if a class looks >10%
wrong in the audit, raise `--min-score` for a re-run of that source or drop
that pseudo-class. VRAM note: GroundedSAM2 fits in 12 GB; if OOM, use the
`autodistill-grounding-dino` backend instead (boxes only — fine, we don't need
masks).

## Step 3 — Augment + train (GPU, ~a weekend)

```powershell
python augment_fisheye.py --frac 0.4       # CPU ~1h; uses repo calib_oak.json k1-k4
git clone https://github.com/meituan/YOLOv6 third_party/YOLOv6   # GPL — internal use only
pip install -r third_party/YOLOv6/requirements.txt
python train_radius.py stage1              # 120 epochs @640, batch 32 → ~20-40h on the 3060
python train_radius.py stage2              # 25-epoch fine-tune → few hours
```

Expect YOLOv6-repo CLI/arg drift vs `train_radius.py` — fix the driver script
as needed and commit. If batch 32 OOMs at 640, drop to 24. Background
negatives: if any empty construction/gravel/road images are available, add
5-10% with empty label files before stage1 (improves false-positive rate; skip
if none on hand).

## Step 4 — Eval gate (before any flash)

Build predictions JSONL for candidate AND for the current baseline
(`models/yolov6nr1-coco.blob` behavior ≈ run its .pt equivalent, or at minimum
gate the candidate's absolute numbers), then:

```powershell
python eval\eval_radius.py candidate_preds.jsonl --gt data\eval\bench --compare baseline_preds.jsonl
```

Eval data reality check: MOCS/SODA require registration/request forms — get
them if easy, but do NOT block on them. Minimum viable gate = the `bench` set:
have Tyler capture a few hundred frames around real equipment with
`training/capture_frames.py` (or pull frames from any Scout footage he has),
teacher-label + hand-correct, and evaluate at the EXACT deployed preprocessing
(stretch-resize to 640×384, no letterbox — `eval_radius.py` docstring).
Person recall per distance band is THE metric; mAP is the tiebreaker.

## Step 5 — Export + deliver

```powershell
python export_blob.py runs\radius_s2\weights\best_ckpt.pt --version v1
# If the tools CLI fights you: upload the .pt at https://tools.luxonis.com
#   → YOLOv6, shape 640 384, RVC2, 6 shaves, OpenVINO 2021.4, superblob OFF
#   → drop the blob at models\radius-v1.blob and let export_blob.py's sidecar
#     block be your reference for models\radius-v1.json
```

Deliverables — commit ALL of this to `feat/radius` and push:
1. `models/radius-v1.blob` + `models/radius-v1.json` (blob is gitignored —
   put it on the G: drive at `GridFront Software/Radius/` AND keep a local copy)
2. Uncomment + fill the `radius-v1` registration in `pipeline/model_registry.py`
3. `training/radius/RESULTS.md`: eval JSON (bands table), dataset stats,
   audit notes, timings, every deviation you made from this handover
4. Any script fixes you made along the way

Flashing the cameras happens back on the laptop/bench (needs the OAK on PoE) —
do NOT attempt from the gaming PC.

## Optional (only if time/appetite)

- **Cones:** the clean merge is cone-light. Verified-CC-BY cone sets from
  Roboflow Universe (provenance-check!) or 30 minutes of synthetic cones
  (paste cone renders into site backgrounds) would help the class.
- **MOCS/SODA eval registration** for the fuller benchmark.

## If something is ambiguous

Prefer: (1) the hard rules above, (2) `README.md` here, (3) ask Tyler.
Progress-log as you go into `training/radius/RESULTS.md` — timings, blockers,
choices. The laptop session's memory tracks this program as
`scout-perception-v2-program`; keep branch `feat/radius` the single source of
truth so it can pick up where you leave off.
