# GridFront Radius — model training pipeline

Radius v1 replaces the deleted `gridfront-scout-v1` (AGPL + NC-data
encumbered — `../legacy_v1/DO-NOT-USE.md`). Target: **YOLOv6-N 3.0 @
640×384**, license-clean data, deployed on OAK-D Pro W PoE (RVC2) via
`pipeline/standalone/build_standalone_v2.py`.

Full program doc (diagnosis, evidence, sources): the Perception Roadmap
artifact + research reports referenced in memory `scout-perception-v2-program`.

## Why these choices (one paragraph)

YOLO11n's ops run ~half speed on Myriad X (Luxonis-confirmed); YOLOv6-N is
the fastest well-supported architecture on RVC2 (63.6 FPS @512×288, ~30-40
@640×384) with a turnkey export path. 640×384 puts ~56% more pixels on a
person at 10-15 m — the current 512×288 leaves them below the stride-8
detectability floor. The v1 merge's fatal flaw was systematic missing labels
(equipment datasets with unlabeled people taught "person near excavator =
background"); step 2 fixes that with teacher pseudo-label completion.

## Taxonomy (9 classes, index order matters)

`person, excavator, wheel-loader, dozer, crane, dump-truck, grader,
compactor, cone` — must match `pipeline/model_registry.py::RADIUS_LABELS`.

## Runbook

```
0. pip install -r requirements.txt          # per-step extras noted in each script
1. python datasets.py download              # fetch license-clean sources → data/raw/
   python datasets.py remap                 # remap to Radius taxonomy → data/radius/
2. python complete_labels.py                # teacher pseudo-label completion (GPU)
3. python augment_fisheye.py                # bake fisheye-warped copies (30-50%)
4. python train_radius.py                   # YOLOv6-N + self-distillation (GPU)
5. python eval/eval_radius.py runs/<exp>/weights/best_ckpt.pt
                                            # miss-rate/FPPI + distance bands — THE GATE
6. python export_blob.py runs/<exp>/weights/best_ckpt.pt --version v1
                                            # → models/radius-v1.blob + .json sidecar
7. Register in pipeline/model_registry.py (uncomment radius-v1 block),
   flash via: python -m pipeline.standalone.build_standalone_v2 --confirm-flash
```

## Data sources (verified commercial-use only)

| Source | License | Role | Get it |
|---|---|---|---|
| Mendeley "Object Detection at Construction Sites" (87,766 imgs) | CC BY 4.0 | core machines | data.mendeley.com/datasets/rz8723t6d7/2 |
| Hard Hat Workers (7,035) | Public Domain | person/PPE | public.roboflow.com/object-detection/hard-hat-workers |
| SHEL5K (5,000) | verify on IEEE DataPort page before use | person/helmet | via paper 10.1080/23311916.2024.2333209 |
| Open Images V7 person, box area <1% | CC BY 4.0 (annotations) | far/small persons | via `fiftyone.zoo` |
| CC-BY cone sets + css-data | **verify per-project provenance** | cones | Roboflow Universe — beware laundered NC re-uploads |
| Synthetic (VCVW-3D; own Unity/Omniverse later) | verify VCVW-3D | distance-controlled persons | — |

**Never train on:** ACID, MOCS, CIS, CrowdHuman, FSOCO, VisDrone, FLIR
(all non-commercial). MOCS + SODA are **eval-only** (internal benchmark,
never shipped in weights — counsel-reviewed position).

**Base weights policy:** train from scratch or from checkpoints trained on
our clean data. Do **not** fine-tune Meituan's COCO-pretrained checkpoints
for shipped models (keeps the weights provenance 100% ours). The YOLOv6
*code* is GPL-3.0 — internal use only, we ship a compiled blob (no Meituan
code ships). Counsel should bless this position once.

## The gate (step 5)

A candidate may flash only if, at the exact deployed preprocessing
(640×384 stretch, no letterbox):

1. **Person miss-rate @ 0.1 FPPI** improves vs incumbent (Caltech protocol)
2. **Per-distance-band person recall** (box-height buckets; red-band ≥ all)
   does not regress in any band
3. mAP50 on frozen MOCS/SODA remaps — secondary tiebreaker

## Deployment geometry (must match training)

1080p → `setPreviewSize(640,384)`, `setPreviewKeepAspectRatio(False)`
(16:9→~16:9.6 stretch, no letterbox), RGB, FP16. Fisheye: do NOT undistort
on device (breaks YoloSpatialDetectionNetwork depth-ROI geometry) — the
model must tolerate the 127° lens via augmentation (step 3), using the real
EEPROM k1-k4 from `calib_oak.json`.

Export: legacy tools.luxonis.com path, OpenVINO **2021.4**, **6 shaves**,
superblob **off** (superblobs break DepthAI 2.x — `BlobReader error`).
