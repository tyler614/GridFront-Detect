"""Produce the predictions JSONL that eval_radius.py consumes.

Runs a trained YOLOv6 checkpoint over an image directory at the EXACT
deployed preprocessing — stretch-resize to 640x384, NO letterbox (matches
setPreviewKeepAspectRatio(False) on the camera) — and writes one line per
image: {"image": name, "boxes": [[cls, conf, x1, y1, x2, y2], ...]} with
coords normalized 0..1. Normalized coords are invariant under stretch, so
they compare directly against YOLO-format GT of the original images.

Runner convention (training/radius/runner/README.md): this script existing
at eval/predict_radius.py makes the runner's eval stage run automatically:
    python eval/predict_radius.py <ckpt> --out preds.jsonl [--images DIR]

Deps: the training venv (torch + the cloned third_party/YOLOv6).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RADIUS = HERE.parent
Y6 = RADIUS / "third_party" / "YOLOv6"
sys.path.insert(0, str(Y6))

import numpy as np  # noqa: E402
import torch  # noqa: E402

W, H = 640, 384
CONF_FLOOR = 0.05  # keep low: eval sweeps thresholds itself


def _load_model(ckpt: Path, device: torch.device):
    from yolov6.layers.common import DetectBackend
    model = DetectBackend(str(ckpt), device=device)
    model.model.float().eval()
    return model


def _nms(pred, conf_thres=CONF_FLOOR, iou_thres=0.65):
    from yolov6.utils.nms import non_max_suppression
    return non_max_suppression(pred, conf_thres, iou_thres,
                               classes=None, agnostic=False, max_det=300)


def main(ckpt: Path, images: Path, out: Path, batch: int) -> None:
    import cv2
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    model = _load_model(ckpt, device)
    paths = sorted(p for p in images.iterdir()
                   if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    print(f"predicting {len(paths)} images @ {W}x{H} stretch on {device}")
    n = 0
    with out.open("w", encoding="utf-8") as f:
        for i in range(0, len(paths), batch):
            chunk = paths[i:i + batch]
            ims, ok_paths = [], []
            for p in chunk:
                im = cv2.imread(str(p))
                if im is None:
                    continue
                im = cv2.resize(im, (W, H), interpolation=cv2.INTER_LINEAR)
                im = im[:, :, ::-1].transpose(2, 0, 1)  # BGR->RGB, HWC->CHW
                ims.append(np.ascontiguousarray(im, dtype=np.float32) / 255.0)
                ok_paths.append(p)
            if not ims:
                continue
            t = torch.from_numpy(np.stack(ims)).to(device)
            with torch.no_grad():
                pred = model(t)
            dets = _nms(pred)
            for p, d in zip(ok_paths, dets):
                boxes = []
                if d is not None and len(d):
                    for *xyxy, conf, cls in d.cpu().numpy():
                        x1, y1, x2, y2 = xyxy
                        boxes.append([int(cls), round(float(conf), 4),
                                      round(x1 / W, 6), round(y1 / H, 6),
                                      round(x2 / W, 6), round(y2 / H, 6)])
                f.write(json.dumps({"image": p.name, "boxes": boxes}) + "\n")
                n += 1
            if (i // batch) % 20 == 0:
                print(f"PROGRESS {json.dumps({'stage_pct': round(100.0 * i / max(1, len(paths)), 1)})}",
                      flush=True)
    print(f"wrote {n} lines -> {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("ckpt", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--images", type=Path,
                    default=RADIUS / "data" / "radius" / "val" / "images")
    ap.add_argument("--batch", type=int, default=16)
    a = ap.parse_args()
    main(a.ckpt, a.images, a.out, a.batch)
