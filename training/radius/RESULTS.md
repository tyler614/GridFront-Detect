# Radius v1 — run log & results

Live log of the first supervised end-to-end run **through the runner**
(2026-07-05 → 06 overnight; laptop-Claude driving the gaming PC over SSH,
Tyler asleep — his order: deliver v1 by morning). Updated as stages complete.

## Run shape (deliberately scaled to an overnight budget)

Full-recipe training (16h teacher + 40h train on the full 87k+ merge) does not
fit one night on the 3060. This run trains a REAL, useful v1 at reduced scale;
v1.1 re-runs the full recipe with Tyler's logins + field data later.

- Data (all license-clean, no logins available tonight):
  - `mendeley87k` — CC BY 4.0, fetched via Mendeley public API (no login);
    fixed-camera redundancy → capped ~12k train images after dedupe+subset
  - `hardhat_hf` — Hard Hats (roboflow-universe-projects, CC BY 4.0 per the
    export's own README; **Tyler: morning-confirm the universe page** before
    promoting past draft); 19.7k construction scenes used as TEACHER CANVASES
    (source head-boxes dropped; person boxes drawn by the teacher)
  - `openimages_person` — CC BY 4.0 annotations; far/small-person subset,
    --max 12000
  - SHEL5K skipped (IEEE login unavailable); cones have no dedicated source
    tonight → `cone` class will be weak in v1 (documented gap, v1.1 fix)
- Teacher completion on the subset (GroundedSAM2 → fallback grounding-dino)
- Train: YOLOv6-N from scratch, stage1 60 epochs @640 batch 28 (env-scaled),
  stage2 12 epochs; self-distillation off for from-scratch overnight run
- Eval: predict_radius.py over held-out val @ exact 640x384 stretch →
  eval_radius.py (miss-rate/FPPI + distance bands). MOCS/SODA benches need
  registrations — deferred to v1.1.
- Export: tools CLI, OpenVINO 2021.4, 6 shaves, superblob off
- Registration: auto via runner → scout_models as DRAFT

## Timeline

- 23:35 phase2 env build done (torch 2.5.1+cu121 on RTX 3060 confirmed)
- 23:43 Mendeley 9.4GB download started (public API, no login — win)
- 23:48 hardhat_hf + Open Images downloads started
- 23:52 runner daemon polling the laptop dispatcher (:9003) — toml escape bug
  fixed (literal strings)
- 00:07 Mendeley conn-reset; discovered D: is a FLAKY THUMB DRIVE → re-pointed
  the data junction to C:\RadiusData (internal disk); resume-loop script v2
- 00:20 v2 downloaded all 9.4GB in ~6 min (26 MB/s link!) BUT PowerShell 5.1
  Expand-Archive can't read Zip64 (>4GB) archives → silent fail → script
  deleted the zip after the failed unzip (twice). Lessons: tar.exe for
  extraction, verify-extracted-count BEFORE deleting, never trust stale log
  markers across script generations (two ghost "done" signals), never
  taskkill stale PIDs (PID reuse).
- 00:41 Open Images copy complete: 3,449 far-person images kept (of 12k
  candidates)
- ~01:00 Mendeley v3 (tar-based, verified delete) + hardhat v3 relaunched
- (updating as events land)

## Stage results

(pending)

## Deviations from the full recipe (for v1.1)

1. Epoch budget 60+12 vs 120+25; batch 28 vs 32.
2. Mendeley capped at ~12k of 87k (redundancy dedupe + time budget).
3. No SHEL5K, no dedicated cone data, no MOCS/SODA external benches.
4. Teacher completion single-pass (no expand/contract iterations).
5. Fisheye augmentation frac 0.4 as planned.
6. Self-distillation deferred (needs a first checkpoint to distill from).
