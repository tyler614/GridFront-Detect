"""Train Radius on YOLOv6-N 3.0 (meituan/YOLOv6 — GPL code, INTERNAL USE
ONLY; we ship a compiled blob, never this code or Meituan checkpoints).

Two stages (see README "Resolution discipline"):
  1. main:      multi-scale around 640, from scratch (no COCO checkpoint —
                weights provenance stays ours), self-distillation on
  2. finetune:  last 25 epochs at the exact deployed 640x384 geometry

Prereq (once):
    git clone https://github.com/meituan/YOLOv6 third_party/YOLOv6
    pip install -r third_party/YOLOv6/requirements.txt

Usage:
    python train_radius.py stage1
    python train_radius.py stage2 --ckpt runs/radius_s1/weights/best_ckpt.pt
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
Y6 = HERE / "third_party" / "YOLOv6"
DATA_YAML = HERE / "data" / "radius" / "data.yaml"

# Augmentation intent (applied via YOLOv6 config file):
#   mosaic 1.0 (off last 15 epochs), mixup 0.1, hsv strong, degrees 8,
#   scale biased to zoom-OUT (people at deployment pixel sizes),
#   copy-paste small persons if using the seg-aug fork.
# Background negatives: include 5-10% empty site/gravel/road images in
# data/radius/train with empty label files.


def run(args: list[str]) -> None:
    print("+", " ".join(args))
    r = subprocess.run(args, cwd=Y6)
    if r.returncode != 0:
        sys.exit(r.returncode)


def stage1() -> None:
    if not Y6.exists():
        sys.exit(f"clone meituan/YOLOv6 into {Y6} first (see docstring)")
    run([sys.executable, "tools/train.py",
         "--conf-file", "configs/yolov6n_finetune.py",
         "--data-path", str(DATA_YAML),
         "--img-size", "640",
         "--batch-size", "32",
         "--epochs", "120",
         "--device", "0",
         "--use_syncbn",
         "--output-dir", str(HERE / "runs"),
         "--name", "radius_s1",
         "--distill",              # v6 self-distillation
         "--teacher_model_path", "",  # from-scratch: fill after 1st run to
                                      # self-distill from your own best ckpt
         ])


def stage2(ckpt: str) -> None:
    # Deployed geometry: 640x384. YOLOv6 trains square by default; rectangular
    # via --img-size 640 + letterbox off in the dataloader — patch or accept
    # 640 square with eval at 640x384 (validate BOTH; the eval gate uses the
    # deployed transform either way).
    run([sys.executable, "tools/train.py",
         "--conf-file", "configs/yolov6n_finetune.py",
         "--data-path", str(DATA_YAML),
         "--img-size", "640",
         "--batch-size", "32",
         "--epochs", "25",
         "--device", "0",
         "--check-images", "--check-labels",
         "--output-dir", str(HERE / "runs"),
         "--name", "radius_s2",
         "--pretrained", ckpt,
         ])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["stage1", "stage2"])
    ap.add_argument("--ckpt", default=str(HERE / "runs" / "radius_s1" /
                                          "weights" / "best_ckpt.pt"))
    a = ap.parse_args()
    stage1() if a.stage == "stage1" else stage2(a.ckpt)
