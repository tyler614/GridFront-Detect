"""Merge all downloaded datasets into a single YOLO training folder.

Remaps all labels to the GridFront Detect canonical taxonomy and creates
a unified train/valid/test split ready for YOLOv11 training.

Usage:
    python merge_datasets.py
"""

import os
import shutil
import yaml
from pathlib import Path
from collections import defaultdict

# ---------------------------------------------------------------------------
# GridFront Detect canonical classes (must match import_datasets.py)
# ---------------------------------------------------------------------------
CANONICAL_CLASSES = [
    "person",        # 0
    "hardhat",       # 1
    "no-hardhat",    # 2
    "safety-vest",   # 3
    "no-safety-vest",# 4
    "excavator",     # 5
    "wheel-loader",  # 6
    "dozer",         # 7
    "roller",        # 8
    "crane",         # 9
    "dump-truck",    # 10
    "cement-truck",  # 11
    "water-truck",   # 12
    "grader",        # 13
    "compactor",     # 14
    "car",           # 15
    "truck",         # 16
    "pickup",        # 17
    "cone",          # 18
    "drum",          # 19
    "barrier",       # 20
    "forklift",      # 21
    "skid-steer",    # 22
    "scissor-lift",  # 23
    "boom-lift",     # 24
    "telehandler",   # 25
]

CLASS_TO_ID = {name: i for i, name in enumerate(CANONICAL_CLASSES)}

# ---------------------------------------------------------------------------
# Label maps per dataset (same as import_datasets.py)
# ---------------------------------------------------------------------------
DATASET_LABEL_MAPS = {
    "acid-dataset": {
        "excavator": "excavator", "backhoe_loader": "excavator",
        "cement_truck": "cement-truck", "compactor": "compactor",
        "dozer": "dozer", "dump_truck": "dump-truck", "grader": "grader",
        "mobile_crane": "crane", "tower_crane": "crane", "wheel_loader": "wheel-loader",
    },
    "hard-hat-universe-0dy7t": {
        "Hard Hats": "hardhat", "hard-hat": "hardhat", "hardhat": "hardhat",
        "Hard-Hats": "hardhat", "helmet": "hardhat",
        "NO-Hard-Hats": "no-hardhat", "no-hard-hat": "no-hardhat",
        "no-hardhat": "no-hardhat", "No-Hard-Hats": "no-hardhat",
        "head": "no-hardhat", "Head": "no-hardhat",
        "person": "person", "Person": "person",
    },
    "safety-vests": {
        "vest": "safety-vest", "safety-vest": "safety-vest",
        "Vest": "safety-vest", "Safety Vest": "safety-vest",
        "no-vest": "no-safety-vest", "no-safety-vest": "no-safety-vest",
        "No-Vest": "no-safety-vest", "No-Safety-Vest": "no-safety-vest",
        "NO-Safety Vest": "no-safety-vest", "No-Safety Vest": "no-safety-vest",
        "person": "person", "Person": "person",
    },
    "construction-site-safety": {
        "Hardhat": "hardhat", "hardhat": "hardhat",
        "NO-Hardhat": "no-hardhat", "no-hardhat": "no-hardhat",
        "Safety Vest": "safety-vest", "safety-vest": "safety-vest",
        "NO-Safety Vest": "no-safety-vest", "no-safety-vest": "no-safety-vest",
        "Person": "person", "person": "person",
        "Mask": None, "NO-Mask": None,
        "machinery": "excavator", "vehicle": "truck",
        "Safety Cone": "cone",
    },
    "safety-cones-vfrj2": {
        "cone": "cone", "cones": "cone", "Cone": "cone",
        "safety-cone": "cone", "Safety Cone": "cone",
        "barrel": "drum", "Barrel": "drum", "drum": "drum",
        "channelizer": "cone",
    },
    "apoce-aerial-photographs-for-object-detection-of-construction-equipment-6raie-ryqq": {
        "excavator": "excavator", "Excavator": "excavator",
        "bulldozer": "dozer", "Bulldozer": "dozer",
        "roller": "roller", "Roller": "roller",
        "forklift": "forklift", "Forklift": "forklift",
        "tower-crane": "crane", "Tower-Crane": "crane",
        "lifting-equipment": "crane", "Lifting-Equipment": "crane",
        "concrete-mixer": "cement-truck", "Concrete-Mixer": "cement-truck",
        "concrete-pump": "cement-truck", "Concrete-Pump": "cement-truck",
        "dump-truck": "dump-truck", "Dump-Truck": "dump-truck",
        "piling-machine": None, "Piling-Machine": None,
    },
    "excavators-czvg9": {
        "EXCAVATORS": "excavator", "excavator": "excavator", "Excavator": "excavator",
        "dump truck": "dump-truck", "dump_truck": "dump-truck", "Dump Truck": "dump-truck",
        "wheel loader": "wheel-loader", "wheel_loader": "wheel-loader", "Wheel Loader": "wheel-loader",
    },
    "construction-site-annotations-v2": {
        "car": "car", "Car": "car", "truck": "truck", "Truck": "truck",
        "cone": "cone", "Cone": "cone", "traffic cone": "cone", "Safety-cone": "cone",
        "barricades": "barrier", "Barricades": "barrier", "safety-barrier": "barrier",
        "Type3Barricade": "barrier", "Drum": "drum", "drum": "drum",
        "TCP Tube": "cone", "worker": "person", "Worker": "person",
        "person": "person", "Person": "person",
        "hardhat": "hardhat", "Hardhat": "hardhat",
        "no-hardhat": "no-hardhat", "safety-vest": "safety-vest",
        "Safety-Vest": "safety-vest", "no-safety-vest": "no-safety-vest",
    },
    "iht-lab-con-v2-mrezf": {
        "excavator": "excavator", "Excavator": "excavator",
        "compactor": "compactor", "Compactor": "compactor",
        "dozer": "dozer", "Dozer": "dozer",
        "grader": "grader", "Grader": "grader",
        "dump_truck": "dump-truck", "dump truck": "dump-truck", "Dump Truck": "dump-truck",
        "cement_truck": "cement-truck", "cement truck": "cement-truck",
        "wheel_loader": "wheel-loader", "wheel loader": "wheel-loader",
        "backhoe_loader": "excavator", "tower_crane": "crane",
        "mobile_crane": "crane", "crane": "crane",
    },
    "construction-equipment-6r96y": {
        "Dump Truck": "dump-truck", "Excavator": "excavator",
        "Front End Loader": "wheel-loader", "Skid Steer": "skid-steer",
        "Tractor Trailer": "truck", "Trailer": "truck", "Vehicle": "truck",
        "Worker": "person",
        "Hard Hat ON": "hardhat", "Hard Hat OFF": "no-hardhat",
        "Safety Vest ON": "safety-vest", "Safety Vest OFF": "no-safety-vest",
        "Gloves ON": None, "Gloves-OFF": None, "Ladder": None,
    },
    "jersey-barrier": {
        "jersey-barrier": "barrier", "Jersey-Barrier": "barrier",
        "jersey_barrier": "barrier", "barrier": "barrier", "Barrier": "barrier",
    },
    "situational_awareness": {
        "Excavator": "excavator", "Dozer": "dozer", "Compactor": "compactor",
        "Motor-Grader": "grader", "Wheel-Loader": "wheel-loader",
        "Water-Truck": "water-truck", "Telehandler": "telehandler",
        "Skid-Steer": "skid-steer", "Articulated-Truck": "dump-truck",
        "Backhoe-Loader": "excavator", "Truck-Belly-Dump": "dump-truck",
        "Scraper": None,
    },
    "haul-truck-scissor-lift-new": {
        "Haul Truck": "dump-truck", "Haul-Truck": "dump-truck",
        "haul truck": "dump-truck",
        "Scissor-lifts": "scissor-lift", "Scissor Lift": "scissor-lift",
        "scissor-lift": "scissor-lift", "scissor lift": "scissor-lift",
    },
    "forklift-u2ivk": {
        "forklift": "forklift", "Forklift": "forklift",
    },
    "crowdhuman-nur7g": {
        "person": "person", "Person": "person",
        "head": None, "Head": None,
    },
    "people-detection-thermal": {
        "people": "person", "People": "person",
        "person": "person", "Person": "person",
    },
    "flir-data-set": {
        "Person": "person", "person": "person",
        "Car": "car", "car": "car",
        "Bicycle": None, "Dog": None,
    },
    "person-vehicle-cu6xf": {
        "Person": "person", "person": "person",
        "Vehicle": "truck", "vehicle": "truck",
    },
}


def read_class_names(dataset_dir: Path) -> list[str]:
    """Read class names from data.yaml."""
    for yaml_name in ["data.yaml", "dataset.yaml"]:
        yaml_path = dataset_dir / yaml_name
        if yaml_path.exists():
            break
    else:
        for p in dataset_dir.rglob("data.yaml"):
            yaml_path = p
            break
        else:
            return []

    with open(yaml_path) as f:
        data = yaml.safe_load(f)
    names = data.get("names", [])
    if isinstance(names, dict):
        max_id = max(names.keys()) if names else -1
        result = [""] * (max_id + 1)
        for k, v in names.items():
            result[int(k)] = v
        return result
    return list(names)


def remap_label_line(parts: list[str], source_names: list[str], label_map: dict) -> str | None:
    """Remap a single YOLO annotation line. Returns None to drop."""
    src_id = int(parts[0])
    if src_id >= len(source_names):
        return None
    src_label = source_names[src_id]

    # Try exact match, then case-insensitive
    canonical = label_map.get(src_label)
    if canonical is None and src_label not in label_map:
        for k, v in label_map.items():
            if k.lower() == src_label.lower():
                canonical = v
                break
    if canonical is None:
        return None

    new_id = CLASS_TO_ID[canonical]
    return f"{new_id} {' '.join(parts[1:])}"


def main():
    downloads_dir = Path("training/downloads")
    output_dir = Path("training/merged")

    # Clean output
    if output_dir.exists():
        shutil.rmtree(output_dir)

    for split in ["train", "valid", "test"]:
        (output_dir / split / "images").mkdir(parents=True)
        (output_dir / split / "labels").mkdir(parents=True)

    stats = defaultdict(int)
    class_counts = defaultdict(int)
    file_idx = 0

    for ds_name, label_map in DATASET_LABEL_MAPS.items():
        ds_dir = downloads_dir / ds_name
        if not ds_dir.exists():
            print(f"  SKIP {ds_name} — not downloaded")
            continue

        source_names = read_class_names(ds_dir)
        if not source_names:
            print(f"  SKIP {ds_name} — no data.yaml")
            continue

        print(f"\n  Merging: {ds_name} ({len(source_names)} source classes)")
        ds_count = 0

        for split in ["train", "valid", "test"]:
            img_dir = ds_dir / split / "images"
            lbl_dir = ds_dir / split / "labels"
            if not img_dir.exists():
                continue

            out_split = split  # keep original splits

            for img_path in img_dir.iterdir():
                if img_path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".bmp"):
                    continue

                lbl_path = lbl_dir / (img_path.stem + ".txt")
                if not lbl_path.exists():
                    stats["no_label"] += 1
                    continue

                # Remap labels
                lines = lbl_path.read_text().strip().splitlines()
                remapped = []
                for line in lines:
                    parts = line.strip().split()
                    if len(parts) < 5:
                        continue
                    new_line = remap_label_line(parts, source_names, label_map)
                    if new_line:
                        remapped.append(new_line)
                        # Count class
                        cls_id = int(new_line.split()[0])
                        class_counts[CANONICAL_CLASSES[cls_id]] += 1

                if not remapped:
                    stats["empty_remap"] += 1
                    continue

                # Copy image + write remapped label with unique name
                file_idx += 1
                ext = img_path.suffix
                new_name = f"{file_idx:06d}"

                shutil.copy2(img_path, output_dir / out_split / "images" / f"{new_name}{ext}")
                (output_dir / out_split / "labels" / f"{new_name}.txt").write_text(
                    "\n".join(remapped) + "\n"
                )
                ds_count += 1
                stats["merged"] += 1

        print(f"    -> {ds_count} images merged")

    # Write data.yaml
    data_yaml = {
        "path": str(output_dir.resolve()),
        "train": "train/images",
        "val": "valid/images",
        "test": "test/images",
        "nc": len(CANONICAL_CLASSES),
        "names": CANONICAL_CLASSES,
    }
    yaml_path = output_dir / "data.yaml"
    with open(yaml_path, "w") as f:
        yaml.dump(data_yaml, f, default_flow_style=False)

    # Summary
    print(f"\n{'='*60}")
    print(f"MERGE COMPLETE")
    print(f"{'='*60}")
    print(f"  Total images merged: {stats['merged']}")
    print(f"  Skipped (no label):  {stats['no_label']}")
    print(f"  Skipped (no match):  {stats['empty_remap']}")
    print(f"\n  Output: {output_dir.resolve()}")
    print(f"  Config: {yaml_path.resolve()}")

    # Count images per split
    for split in ["train", "valid", "test"]:
        n = len(list((output_dir / split / "images").glob("*")))
        print(f"  {split}: {n} images")

    print(f"\n  Class distribution ({len(CANONICAL_CLASSES)} classes):")
    for name in CANONICAL_CLASSES:
        count = class_counts.get(name, 0)
        bar = "#" * min(50, count // 200)
        print(f"    {CLASS_TO_ID[name]:2d} {name:20s} {count:>8,}  {bar}")


if __name__ == "__main__":
    main()
