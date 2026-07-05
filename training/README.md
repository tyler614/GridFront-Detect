# Training — GridFront Radius

**Radius** is GridFront's detection model line for Scout (OAK-D Pro W PoE,
RVC2). Everything lives in [`radius/`](radius/README.md) — dataset build,
pseudo-label completion, fisheye augmentation, YOLOv6-N training,
miss-rate/FPPI evaluation, and RVC2 blob export.

- `radius/` — the current pipeline (license-clean; produces `radius-v*`)
- `legacy_v1/` — archived v1 pipeline. **Do not use** — AGPL weights +
  non-commercial data (see `legacy_v1/DO-NOT-USE.md`)
- `capture_frames.py` — ad-hoc frame capture from an OAK by IP (still useful
  for building bench/eval sets)
