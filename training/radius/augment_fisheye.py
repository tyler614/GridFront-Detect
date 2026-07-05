"""Fisheye augmentation — make training match the 127-degree lens.

We deliberately do NOT undistort on the camera (it breaks
YoloSpatialDetectionNetwork's depth-ROI geometry on RVC2). Instead the model
learns the lens: warp 30-50% of training images with distortion bracketing
the real OAK optics, transforming boxes with the pixels.

The real coefficients come from the camera EEPROM (calib_oak.json at repo
root — CameraModel + distortionCoeff k1..k4 for the RGB socket). Random
strengths around them cover unit-to-unit lens variance.

Deps: pip install opencv-python numpy
Usage:
    python augment_fisheye.py --frac 0.4          # bakes *_fe copies in-place
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "radius"
REPO = HERE.parents[1]


def _load_k_from_eeprom() -> list[float]:
    calib = REPO / "calib_oak.json"
    if calib.exists():
        doc = json.loads(calib.read_text("utf-8"))
        for cam in doc.get("cameraData", []):
            # cameraData is [[socket, {..}], ...]; RGB socket == 0
            if isinstance(cam, list) and cam[0] == 0:
                d = cam[1].get("distortionCoeff", [])
                if len(d) >= 4:
                    return [float(x) for x in d[:4]]
    # Fallback: plausible wide-lens coefficients; still bracket randomly
    return [0.18, -0.02, 0.0, 0.0]


def _warp(img: np.ndarray, boxes: list[list[float]], k_scale: float,
          k: list[float]) -> tuple[np.ndarray, list[list[float]]]:
    h, w = img.shape[:2]
    K = np.array([[w * 0.7, 0, w / 2], [0, w * 0.7, h / 2], [0, 0, 1]])
    D = np.array(k) * k_scale
    # distort = inverse of undistort: build remap grid by projecting the
    # target grid through the fisheye model
    newK = K.copy()
    map1, map2 = cv2.fisheye.initUndistortRectifyMap(
        K, D, np.eye(3), newK, (w, h), cv2.CV_32FC1)
    warped = cv2.remap(img, map1, map2, cv2.INTER_LINEAR,
                       borderMode=cv2.BORDER_REPLICATE)

    def px(cx, cy):
        # distort a point: normalize, apply fisheye model, re-project
        pts = np.array([[[cx, cy]]], dtype=np.float64)
        und = cv2.fisheye.undistortPoints(pts, K, D, P=newK)
        return float(und[0, 0, 0]), float(und[0, 0, 1])

    out_boxes = []
    for cid, cx, cy, bw, bh in boxes:
        x1, y1 = px((cx - bw / 2) * w, (cy - bh / 2) * h)
        x2, y2 = px((cx + bw / 2) * w, (cy + bh / 2) * h)
        x1, x2 = sorted((max(0, min(w, x1)), max(0, min(w, x2))))
        y1, y2 = sorted((max(0, min(h, y1)), max(0, min(h, y2))))
        if (x2 - x1) < 2 or (y2 - y1) < 2:
            continue
        out_boxes.append([cid, (x1 + x2) / 2 / w, (y1 + y2) / 2 / h,
                          (x2 - x1) / w, (y2 - y1) / h])
    return warped, out_boxes


def main(frac: float) -> None:
    k = _load_k_from_eeprom()
    print(f"EEPROM k1..k4 = {k}")
    imgs = sorted((DATA / "train" / "images").glob("*"))
    todo = random.sample(imgs, int(len(imgs) * frac))
    made = 0
    for img_p in todo:
        lbl_p = DATA / "train" / "labels" / (img_p.stem + ".txt")
        if not lbl_p.exists():
            continue
        boxes = [[float(v) for v in l.split()[:5]]
                 for l in lbl_p.read_text("utf-8").splitlines() if l.strip()]
        boxes = [[int(b[0])] + b[1:] for b in boxes]
        img = cv2.imread(str(img_p))
        if img is None:
            continue
        # bracket the real lens: 0.6x..1.3x strength
        warped, wboxes = _warp(img, boxes, random.uniform(0.6, 1.3), k)
        if not wboxes:
            continue
        cv2.imwrite(str(img_p.with_name(img_p.stem + "_fe" + img_p.suffix)),
                    warped)
        (lbl_p.with_name(lbl_p.stem + "_fe.txt")).write_text(
            "\n".join(f"{b[0]} " + " ".join(f"{v:.6f}" for v in b[1:])
                      for b in wboxes), encoding="utf-8")
        made += 1
    print(f"baked {made} fisheye-warped copies")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--frac", type=float, default=0.4)
    main(ap.parse_args().frac)
