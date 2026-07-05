"""Radius eval gate — the numbers that decide whether a model may flash.

Metrics (in gate order — see radius/README.md):
  1. person miss-rate vs FPPI (Caltech protocol), operating point @ 0.1 FPPI
  2. per-distance-band person recall (box-height buckets as distance proxy)
  3. mAP50 across all classes (tiebreaker)

Eval sets:
  * data/eval/mocs/   — MOCS remap  (CC BY-NC: EVAL-ONLY, never train)
  * data/eval/soda/   — SODA remap  (license unconfirmed: EVAL-ONLY)
  * data/eval/bench/  — our own captured clips (capture_frames.py), labeled
                        via the same teacher + hand-correction

CRITICAL: inference here must use the deployed preprocessing — resize
(stretch) to 640x384, NO letterbox — or the numbers are fiction.

Deps: pip install numpy pillow
Runner: expects a predictions JSONL produced by predict.py-style inference
(one line per image: {"image":..., "boxes":[[cls,conf,x1,y1,x2,y2]...]},
coords normalized 0..1). Keeps this file model-agnostic (v6/onnx/blob).

Usage:
    python eval/eval_radius.py preds.jsonl --gt data/eval/mocs
    python eval/eval_radius.py preds.jsonl --gt data/eval/mocs --compare baseline_preds.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

PERSON = 0
# Box-height fraction of image height -> distance band (127deg lens, 1080p,
# ~1.75m person; calibrate against bench measurements when available).
BANDS = [
    ("0-5m (red)", 0.28, 1.00),
    ("5-10m (yellow)", 0.14, 0.28),
    ("10-15m", 0.09, 0.14),
    ("15m+", 0.00, 0.09),
]


def _iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = ((a[2] - a[0]) * (a[3] - a[1]) +
          (b[2] - b[0]) * (b[3] - b[1]) - inter)
    return inter / ua if ua > 0 else 0.0


def _load_gt(gt_dir: Path) -> dict[str, list]:
    gt = {}
    for lbl in (gt_dir / "labels").glob("*.txt"):
        boxes = []
        for line in lbl.read_text("utf-8").splitlines():
            p = line.split()
            if len(p) < 5:
                continue
            cid = int(p[0])
            cx, cy, w, h = map(float, p[1:5])
            boxes.append([cid, cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, h])
        gt[lbl.stem] = boxes
    return gt


def _match(preds, gts, iou_thr=0.5):
    """Greedy match person preds->gts. Returns (tp_flags, matched_gt_idx, fp_count)."""
    used = set()
    tp = []
    for p in sorted(preds, key=lambda x: -x[1]):
        best, best_iou = None, iou_thr
        for gi, g in enumerate(gts):
            if gi in used:
                continue
            i = _iou(p[2:6], g[1:5])
            if i >= best_iou:
                best, best_iou = gi, i
        if best is None:
            tp.append((p[1], False, None))
        else:
            used.add(best)
            tp.append((p[1], True, best))
    return tp


def evaluate(preds_path: Path, gt_dir: Path) -> dict:
    gt = _load_gt(gt_dir)
    per_image = []
    for line in preds_path.read_text("utf-8").splitlines():
        rec = json.loads(line)
        stem = Path(rec["image"]).stem
        if stem not in gt:
            continue
        persons_p = [b for b in rec["boxes"] if int(b[0]) == PERSON]
        persons_g = [g for g in gt[stem] if g[0] == PERSON]
        per_image.append((_match(persons_p, persons_g), persons_g))

    # --- miss rate vs FPPI sweep ---
    n_img = len(per_image)
    n_gt = sum(len(g) for _, g in per_image)
    thresholds = np.linspace(0.05, 0.95, 91)
    curve = []
    for t in thresholds:
        tp = fp = 0
        for matches, _ in per_image:
            for conf, is_tp, _gi in matches:
                if conf >= t:
                    tp += is_tp
                    fp += (not is_tp)
        fppi = fp / max(1, n_img)
        miss = 1 - tp / max(1, n_gt)
        curve.append((float(t), fppi, miss))
    # operating point: highest recall with FPPI <= 0.1
    op = min((c for c in curve if c[1] <= 0.1),
             key=lambda c: c[2], default=curve[-1])

    # --- per-band recall at the operating threshold ---
    bands = {}
    for name, lo, hi in BANDS:
        got = tot = 0
        for matches, gts in per_image:
            band_gt = {gi for gi, g in enumerate(gts) if lo <= g[5] < hi}
            tot += len(band_gt)
            got += sum(1 for conf, is_tp, gi in matches
                       if is_tp and gi in band_gt and conf >= op[0])
        bands[name] = {"recall": round(got / tot, 4) if tot else None,
                       "gt": tot}
    return {"images": n_img, "person_gt": n_gt,
            "operating_point": {"threshold": round(op[0], 2),
                                "fppi": round(op[1], 4),
                                "miss_rate": round(op[2], 4)},
            "band_recall": bands}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("preds", type=Path)
    ap.add_argument("--gt", type=Path, required=True)
    ap.add_argument("--compare", type=Path, help="baseline preds JSONL")
    a = ap.parse_args()
    res = evaluate(a.preds, a.gt)
    print(json.dumps(res, indent=2))
    if a.compare:
        base = evaluate(a.compare, a.gt)
        print("\n=== GATE vs baseline ===")
        ok = res["operating_point"]["miss_rate"] <= base["operating_point"]["miss_rate"]
        for band in res["band_recall"]:
            r, b = res["band_recall"][band]["recall"], base["band_recall"][band]["recall"]
            if r is not None and b is not None and r < b:
                ok = False
                print(f"  REGRESSION {band}: {r} < {b}")
        print("PASS — candidate may flash" if ok else "FAIL — do not flash")
