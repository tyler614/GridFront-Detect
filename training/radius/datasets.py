"""Radius dataset builder — download + remap license-clean sources.

Usage:
    python datasets.py download   # fetch sources into data/raw/<source>/
    python datasets.py remap      # unify into data/radius/{train,val}/ (YOLO txt)
    python datasets.py stats      # per-class instance counts + license manifest

Every source carries an explicit license record; `remap` refuses sources
whose license is not in ALLOWED_LICENSES. This file is the provenance
manifest for Radius weights — keep it accurate.

Deps: pip install requests tqdm fiftyone pillow
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = HERE / "data" / "raw"
OUT = HERE / "data" / "radius"

RADIUS_CLASSES = [
    "person", "excavator", "wheel-loader", "dozer", "crane",
    "dump-truck", "grader", "compactor", "cone",
]
CLASS_TO_ID = {c: i for i, c in enumerate(RADIUS_CLASSES)}

ALLOWED_LICENSES = {"CC BY 4.0", "Public Domain", "CC0"}


@dataclass
class Source:
    key: str
    name: str
    license: str            # must be in ALLOWED_LICENSES to be merged
    license_verified: bool  # True only after a human checked the ORIGIN page
    url: str
    label_map: dict[str, str | None]  # source label -> radius label (None = drop)
    notes: str = ""
    # Classes present in imagery but NOT labeled by this source. These are
    # exactly what complete_labels.py must pseudo-label before training —
    # merging without completion recreates the v1 missing-label poisoning.
    missing_classes: list[str] = field(default_factory=list)


SOURCES: list[Source] = [
    Source(
        key="mendeley87k",
        name="AI Dataset for Object Detection at Construction Sites (2024)",
        license="CC BY 4.0",
        license_verified=True,  # stated on the Mendeley record page
        url="https://data.mendeley.com/datasets/rz8723t6d7/2",
        label_map={
            # NOTE: fill from the dataset's classes.txt after download —
            # 12 machinery types; map cranes->crane, dump/haul truck->
            # dump-truck, roller->compactor, etc.
            "excavator": "excavator",
            "wheel_loader": "wheel-loader",
            "dozer": "dozer",
            "crane": "crane",
            "dump_truck": "dump-truck",
            "grader": "grader",
            "roller": "compactor",
        },
        missing_classes=["person", "cone"],
        notes="Fixed elevated camera, 6 months, one Korean site. DEDUPE "
              "near-identical video frames (see remap --dedupe).",
    ),
    Source(
        key="hardhat",
        name="Hard Hat Workers (Northeastern China / Roboflow public)",
        license="Public Domain",
        license_verified=True,
        url="https://public.roboflow.com/object-detection/hard-hat-workers",
        label_map={"person": "person", "head": "person", "helmet": "person"},
        missing_classes=["excavator", "wheel-loader", "dozer", "crane",
                         "dump-truck", "grader", "compactor", "cone"],
        notes="head/helmet boxes are heads, not full bodies — complete_labels "
              "replaces them with teacher person boxes (keep as fallback).",
    ),
    Source(
        key="shel5k",
        name="SHEL5K",
        license="CC BY 4.0",
        license_verified=False,  # VERIFY on IEEE DataPort before merging
        url="https://ieee-dataport.org/",
        label_map={"person": "person", "head": "person",
                   "helmet": "person", "person_with_helmet": "person",
                   "person_no_helmet": "person"},
        missing_classes=["excavator", "wheel-loader", "dozer", "crane",
                         "dump-truck", "grader", "compactor", "cone"],
    ),
    Source(
        key="openimages_person",
        name="Open Images V7 — small persons (box area < 1%)",
        license="CC BY 4.0",
        license_verified=True,  # annotations CC BY 4.0; images CC BY 2.0
        url="fiftyone.zoo:open-images-v7",
        label_map={"Person": "person"},
        missing_classes=[],  # non-construction imagery; machines genuinely absent
        notes="Downloaded via fiftyone with label filter; keeps only images "
              "whose person boxes are small (far-person regime).",
    ),
]


def _manifest() -> dict:
    return {
        "radius_classes": RADIUS_CLASSES,
        "sources": [
            {"key": s.key, "name": s.name, "license": s.license,
             "verified": s.license_verified, "url": s.url, "notes": s.notes}
            for s in SOURCES
        ],
    }


def cmd_download() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    (HERE / "data").mkdir(exist_ok=True)
    print("Manual/scripted downloads — sources land in data/raw/<key>/ :\n")
    for s in SOURCES:
        dest = RAW / s.key
        status = "PRESENT" if dest.exists() else "MISSING"
        print(f"  [{status}] {s.key:<18} {s.license:<14} {s.url}")
    print("\nmendeley87k: download the zip from the record page (free login), "
          "unzip into data/raw/mendeley87k/")
    print("hardhat:     roboflow public page -> Download -> YOLOv8 txt -> "
          "unzip into data/raw/hardhat/")
    print("openimages_person: python datasets.py download-openimages "
          "(uses fiftyone.zoo, ~few GB filtered)")
    (HERE / "data" / "MANIFEST.json").write_text(
        json.dumps(_manifest(), indent=2), encoding="utf-8")


def cmd_download_openimages(max_samples: int = 30000) -> None:
    import fiftyone.zoo as foz  # heavy import, keep local
    ds = foz.load_zoo_dataset(
        "open-images-v7", split="train",
        label_types=["detections"], classes=["Person"],
        max_samples=max_samples, dataset_name="radius-oi-person",
    )
    out = RAW / "openimages_person"
    out.mkdir(parents=True, exist_ok=True)
    kept = 0
    for sample in ds:
        dets = [d for d in (sample.ground_truth.detections or [])
                if d.label == "Person"
                and (d.bounding_box[2] * d.bounding_box[3]) < 0.01]
        if not dets:
            continue
        img_src = Path(sample.filepath)
        (out / "images").mkdir(exist_ok=True)
        (out / "labels").mkdir(exist_ok=True)
        shutil.copy2(img_src, out / "images" / img_src.name)
        lines = []
        for d in dets:
            x, y, bw, bh = d.bounding_box  # top-left normalized
            lines.append(f"0 {x + bw / 2:.6f} {y + bh / 2:.6f} {bw:.6f} {bh:.6f}")
        (out / "labels" / (img_src.stem + ".txt")).write_text(
            "\n".join(lines), encoding="utf-8")
        kept += 1
    print(f"kept {kept} far-person images -> {out}")


def _remap_source(s: Source, dedupe: bool) -> tuple[int, int]:
    """Copy data/raw/<key> (YOLO layout) into data/radius with remapped ids.

    Expects raw layout <key>/{images,labels} or <key>/{train,valid}/{images,labels}.
    Returns (images, instances). Every image gets a source-prefixed name so
    complete_labels.py can apply per-source missing-class prompts later.
    """
    src_root = RAW / s.key
    if not src_root.exists():
        print(f"  skip {s.key}: not downloaded")
        return (0, 0)
    if s.license not in ALLOWED_LICENSES:
        raise SystemExit(f"REFUSING {s.key}: license '{s.license}' not allowed")
    if not s.license_verified:
        print(f"  !! {s.key}: license NOT human-verified yet — refusing. "
              f"Verify on the origin page, then set license_verified=True.")
        return (0, 0)

    # Build source-label -> id map from a classes/data yaml if present, else
    # assume label ids already match label_map key order (document per source).
    n_img = n_inst = 0
    pairs = list(src_root.rglob("labels/*.txt"))
    last_img_hash = None
    for lbl in pairs:
        img = _find_image(lbl)
        if img is None:
            continue
        classes_file = _nearest_classes_file(lbl)
        id_to_name = _load_class_names(classes_file)
        out_lines = []
        for line in lbl.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            src_name = id_to_name.get(int(parts[0]), None)
            tgt = s.label_map.get(src_name) if src_name else None
            if tgt is None:
                continue
            out_lines.append(" ".join([str(CLASS_TO_ID[tgt])] + parts[1:5]))
        if not out_lines:
            continue
        if dedupe:
            h = _cheap_hash(img)
            if h == last_img_hash:  # consecutive video-frame dupes
                continue
            last_img_hash = h
        split = "val" if (hash(img.stem) % 20 == 0) else "train"  # 5% val
        for kind in ("images", "labels"):
            (OUT / split / kind).mkdir(parents=True, exist_ok=True)
        new_stem = f"{s.key}__{img.stem}"
        shutil.copy2(img, OUT / split / "images" / (new_stem + img.suffix))
        (OUT / split / "labels" / (new_stem + ".txt")).write_text(
            "\n".join(out_lines), encoding="utf-8")
        n_img += 1
        n_inst += len(out_lines)
    return (n_img, n_inst)


def _find_image(lbl: Path) -> Path | None:
    img_dir = lbl.parent.parent / "images"
    for ext in (".jpg", ".jpeg", ".png"):
        p = img_dir / (lbl.stem + ext)
        if p.exists():
            return p
    return None


def _nearest_classes_file(lbl: Path) -> Path | None:
    for up in [lbl.parent.parent, lbl.parent.parent.parent]:
        for name in ("classes.txt", "data.yaml", "obj.names"):
            p = up / name
            if p.exists():
                return p
    return None


def _load_class_names(p: Path | None) -> dict[int, str]:
    if p is None:
        return {}
    txt = p.read_text(encoding="utf-8", errors="replace")
    if p.suffix == ".yaml":
        import re
        m = re.search(r"names:\s*\[(.*?)\]", txt, re.S)
        if m:
            names = [n.strip().strip("'\"") for n in m.group(1).split(",")]
            return dict(enumerate(names))
        return {}
    return dict(enumerate([l.strip() for l in txt.splitlines() if l.strip()]))


def _cheap_hash(img: Path) -> str:
    import hashlib
    return hashlib.md5(img.read_bytes()[:65536]).hexdigest()


def cmd_remap(dedupe: bool = True) -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    totals = {}
    for s in SOURCES:
        totals[s.key] = _remap_source(s, dedupe)
        print(f"  {s.key}: {totals[s.key][0]} imgs, {totals[s.key][1]} boxes")
    (OUT / "data.yaml").write_text(
        "train: train/images\nval: val/images\n"
        f"nc: {len(RADIUS_CLASSES)}\nnames: {RADIUS_CLASSES}\n",
        encoding="utf-8")
    # Record which images still need pseudo-label completion per class
    todo = {s.key: s.missing_classes for s in SOURCES if s.missing_classes}
    (OUT / "completion_todo.json").write_text(
        json.dumps(todo, indent=2), encoding="utf-8")
    print(f"\nWrote {OUT} — NOW RUN complete_labels.py (mandatory: merging "
          f"without completion recreates the v1 missing-label poisoning).")


def cmd_stats() -> None:
    counts = {c: 0 for c in RADIUS_CLASSES}
    for lbl in (OUT).rglob("labels/*.txt"):
        for line in lbl.read_text(encoding="utf-8").splitlines():
            cid = int(line.split()[0])
            counts[RADIUS_CLASSES[cid]] += 1
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["download", "download-openimages",
                                    "remap", "stats"])
    ap.add_argument("--no-dedupe", action="store_true")
    a = ap.parse_args()
    if a.cmd == "download":
        cmd_download()
    elif a.cmd == "download-openimages":
        cmd_download_openimages()
    elif a.cmd == "remap":
        cmd_remap(dedupe=not a.no_dedupe)
    else:
        cmd_stats()
