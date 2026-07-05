# ⚠️ Legacy v1 training pipeline — DO NOT USE FOR SHIPPED MODELS

Archived 2026-07-05. This pipeline produced `gridfront-scout-v1`, which was
**deleted from the repo** because it is not commercially shippable:

1. **Ultralytics AGPL-3.0** — Ultralytics states the license covers trained /
   fine-tuned weights (https://www.ultralytics.com/license). Shipping such
   weights in a closed commercial product requires open-sourcing the product
   or an Ultralytics Enterprise License.
2. **Non-commercial training data** — the Roboflow merge included ACID
   (CC BY-NC 4.0), CrowdHuman (non-commercial), FLIR thermal (research
   license), and several Roboflow Universe re-uploads with unverifiable
   ("laundered") license tags.

**Also required:** the Roboflow cloud project (`gridfront-scout`) still
contains the merged NC images — delete the project or strip the NC sources
there too (needs the Roboflow account).

The replacement is **GridFront Radius** — see `training/radius/README.md`:
YOLOv6-N (weights are ours, trained from scratch / clean data), verified
commercial-use datasets only, teacher pseudo-label completion, fisheye
augmentation, and a miss-rate/FPPI eval gate.

These scripts stay archived for reference (the dataset download / remap
plumbing patterns are reusable), but nothing here may feed a shipped model.
