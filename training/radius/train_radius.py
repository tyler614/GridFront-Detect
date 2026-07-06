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
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
Y6 = HERE / "third_party" / "YOLOv6"
DATA_YAML = HERE / "data" / "radius" / "data.yaml"

# Env-overridable so a platform job spec can scale a run to a time budget
# (e.g. the supervised overnight v1 run) without a code change.
EPOCHS_S1 = int(os.environ.get("RADIUS_EPOCHS_S1", "120"))
EPOCHS_S2 = int(os.environ.get("RADIUS_EPOCHS_S2", "25"))
BATCH = int(os.environ.get("RADIUS_BATCH", "32"))

# Augmentation intent (applied via YOLOv6 config file):
#   mosaic 1.0 (off last 15 epochs), mixup 0.1, hsv strong, degrees 8,
#   scale biased to zoom-OUT (people at deployment pixel sizes),
#   copy-paste small persons if using the seg-aug fork.
# Background negatives: include 5-10% empty site/gravel/road images in
# data/radius/train with empty label files.


def run(args: list[str], total_epochs: int | None = None) -> None:
    """Run a YOLOv6 tool, echoing its output. With total_epochs set, also
    emit `PROGRESS {json}` lines (parsed by runner/runner.py) as the
    `<epoch>/<last>` counters in the training log advance."""
    print("+", " ".join(args), flush=True)
    proc = subprocess.Popen(
        args, cwd=Y6, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        env=dict(os.environ, PYTHONUNBUFFERED="1"))
    epoch_re = re.compile(r"(\d+)/(\d+)")
    last_epoch = -1
    assert proc.stdout is not None
    for line in proc.stdout:
        sys.stdout.write(line)
        if not total_epochs:
            continue
        m = epoch_re.search(line)
        if m and int(m.group(2)) == total_epochs - 1:
            ep = int(m.group(1))
            if last_epoch < ep < total_epochs:
                last_epoch = ep
                print("PROGRESS " + json.dumps({
                    "stage_pct": round(100.0 * ep / total_epochs, 1),
                    "metrics": {"epoch": ep, "total_epochs": total_epochs},
                }), flush=True)
    rc = proc.wait()
    if rc != 0:
        sys.exit(rc)


def stage1() -> None:
    if not Y6.exists():
        sys.exit(f"clone meituan/YOLOv6 into {Y6} first (see docstring)")
    run([sys.executable, "tools/train.py",
         "--conf-file", "configs/yolov6n_finetune.py",
         "--data-path", str(DATA_YAML),
         "--img-size", "640",
         "--batch-size", str(BATCH),
         "--epochs", str(EPOCHS_S1),
         "--device", "0",
         "--use_syncbn",
         "--output-dir", str(HERE / "runs"),
         "--name", "radius_s1",
         "--distill",              # v6 self-distillation
         "--teacher_model_path", "",  # from-scratch: fill after 1st run to
                                      # self-distill from your own best ckpt
         ], total_epochs=EPOCHS_S1)


def stage2(ckpt: str) -> None:
    # Deployed geometry: 640x384. YOLOv6 trains square by default; rectangular
    # via --img-size 640 + letterbox off in the dataloader — patch or accept
    # 640 square with eval at 640x384 (validate BOTH; the eval gate uses the
    # deployed transform either way).
    run([sys.executable, "tools/train.py",
         "--conf-file", "configs/yolov6n_finetune.py",
         "--data-path", str(DATA_YAML),
         "--img-size", "640",
         "--batch-size", str(BATCH),
         "--epochs", str(EPOCHS_S2),
         "--device", "0",
         "--check-images", "--check-labels",
         "--output-dir", str(HERE / "runs"),
         "--name", "radius_s2",
         "--pretrained", ckpt,
         ], total_epochs=EPOCHS_S2)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["stage1", "stage2"])
    ap.add_argument("--ckpt", default=str(HERE / "runs" / "radius_s1" /
                                          "weights" / "best_ckpt.pt"))
    a = ap.parse_args()
    stage1() if a.stage == "stage1" else stage2(a.ckpt)
