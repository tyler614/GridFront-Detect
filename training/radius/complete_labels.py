"""Teacher pseudo-label completion — fix the missing-label problem.

The single biggest accuracy lever (see radius/README.md). For every merged
image, run an open-vocabulary teacher ONLY for the classes its source
dataset does not annotate (data/radius/completion_todo.json), then merge
high-confidence teacher boxes into the YOLO label files.

Rules (BigDetection-style):
  * keep teacher boxes with score >= --min-score (default 0.45)
  * drop any teacher box with IoU > 0.6 against an existing GT box
  * write an audit JSONL so a human can spot-check ~200 images per source

Teacher: Grounded-SAM-2 / MM-Grounding-DINO via autodistill (self-hosted,
GPU; ~<$1 per 1k images on a rented card).
  pip install autodistill autodistill-grounded-sam-2 autodistill-yolov8

Usage:
    python complete_labels.py --split train
    python complete_labels.py --split train --source hardhat   # one source
    python complete_labels.py --audit    # sample audit grid images
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "radius"

RADIUS_CLASSES = [
    "person", "excavator", "wheel-loader", "dozer", "crane",
    "dump-truck", "grader", "compactor", "cone",
]
CLASS_TO_ID = {c: i for i, c in enumerate(RADIUS_CLASSES)}

# Text prompts per Radius class — tuned for open-vocab teachers. Machine
# classes get multi-phrase prompts (grader vs dozer confuse text teachers;
# audit these hardest).
PROMPTS = {
    "person": ["person", "construction worker"],
    "excavator": ["excavator", "digger with bucket arm"],
    "wheel-loader": ["wheel loader", "front end loader"],
    "dozer": ["bulldozer with blade"],
    "crane": ["mobile crane", "tower crane"],
    "dump-truck": ["dump truck", "haul truck"],
    "grader": ["motor grader"],
    "compactor": ["road roller", "compactor"],
    "cone": ["traffic cone"],
}


def _iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    iy = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = ix * iy
    ua = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / ua if ua > 0 else 0.0


def _yolo_to_xyxy(line: str) -> tuple[int, tuple]:
    cid, cx, cy, w, h = line.split()[:5]
    cx, cy, w, h = map(float, (cx, cy, w, h))
    return int(cid), (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def _xyxy_to_yolo(cid: int, box: tuple) -> str:
    x1, y1, x2, y2 = box
    return (f"{cid} {(x1 + x2) / 2:.6f} {(y1 + y2) / 2:.6f} "
            f"{x2 - x1:.6f} {y2 - y1:.6f}")


def complete(split: str, only_source: str | None, min_score: float,
             iou_drop: float) -> None:
    todo = json.loads((DATA / "completion_todo.json").read_text("utf-8"))
    img_dir = DATA / split / "images"
    lbl_dir = DATA / split / "labels"
    audit = (DATA / f"completion_audit_{split}.jsonl").open(
        "a", encoding="utf-8")

    # Lazy teacher init — one ontology per source (its missing classes only)
    from autodistill.detection import CaptionOntology
    from autodistill_grounded_sam_2 import GroundedSAM2

    for source_key, missing in todo.items():
        if only_source and source_key != only_source:
            continue
        if not missing:
            continue
        ontology = {}
        for cls in missing:
            for phrase in PROMPTS[cls]:
                ontology[phrase] = cls
        teacher = GroundedSAM2(ontology=CaptionOntology(ontology))
        images = sorted(img_dir.glob(f"{source_key}__*"))
        print(f"{source_key}: completing {missing} over {len(images)} images")
        added_total = 0
        for img in images:
            lbl = lbl_dir / (img.stem + ".txt")
            existing = []
            if lbl.exists():
                existing = [_yolo_to_xyxy(l) for l in
                            lbl.read_text("utf-8").splitlines() if l.strip()]
            preds = teacher.predict(str(img))  # supervision.Detections
            new_lines = []
            for xyxy, score, class_id in zip(
                    preds.xyxy, preds.confidence, preds.class_id):
                if score < min_score:
                    continue
                cls = teacher.ontology.classes()[class_id]
                # normalize teacher xyxy (pixels) -> 0..1
                import PIL.Image
                with PIL.Image.open(img) as im:
                    W, H = im.size
                box = (xyxy[0] / W, xyxy[1] / H, xyxy[2] / W, xyxy[3] / H)
                if any(_iou(box, gt_box) > iou_drop for _, gt_box in existing):
                    continue
                new_lines.append(_xyxy_to_yolo(CLASS_TO_ID[cls], box))
            if new_lines:
                with lbl.open("a", encoding="utf-8") as f:
                    f.write("\n" + "\n".join(new_lines))
                audit.write(json.dumps({
                    "image": img.name, "source": source_key,
                    "added": len(new_lines)}) + "\n")
                added_total += len(new_lines)
        print(f"  +{added_total} pseudo-boxes")
    audit.close()
    print("Done. Spot-check ~200 images/source: python complete_labels.py --audit")


def audit_sample(n: int = 200) -> None:
    """Render a random sample of completed images with boxes for review."""
    import random
    import PIL.Image
    import PIL.ImageDraw
    out = DATA / "audit_render"
    out.mkdir(exist_ok=True)
    lines = (DATA / "completion_audit_train.jsonl").read_text("utf-8").splitlines()
    for rec in random.sample(lines, min(n, len(lines))):
        name = json.loads(rec)["image"]
        img_p = DATA / "train" / "images" / name
        lbl_p = DATA / "train" / "labels" / (Path(name).stem + ".txt")
        with PIL.Image.open(img_p) as im:
            d = PIL.ImageDraw.Draw(im)
            W, H = im.size
            for line in lbl_p.read_text("utf-8").splitlines():
                cid, (x1, y1, x2, y2) = _yolo_to_xyxy(line)
                d.rectangle([x1 * W, y1 * H, x2 * W, y2 * H], outline="red",
                            width=2)
                d.text((x1 * W, y1 * H - 12), RADIUS_CLASSES[cid], fill="red")
            im.save(out / name)
    print(f"rendered -> {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="train")
    ap.add_argument("--source", default=None)
    ap.add_argument("--min-score", type=float, default=0.45)
    ap.add_argument("--iou-drop", type=float, default=0.6)
    ap.add_argument("--audit", action="store_true")
    a = ap.parse_args()
    if a.audit:
        audit_sample()
    else:
        complete(a.split, a.source, a.min_score, a.iou_drop)
