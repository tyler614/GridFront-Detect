"""Download public Roboflow Universe datasets and upload to GridFront Detect project.

Handles label remapping so all datasets use a unified class taxonomy.
Uploads images + YOLO annotations via the Roboflow REST API.

Usage:
    python import_datasets.py --api-key YOUR_KEY --project gridfront-detect
"""

import argparse
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# GridFront Detect unified class taxonomy
# ---------------------------------------------------------------------------
# Each source dataset maps its labels → these canonical names.
# Labels mapped to None are dropped (irrelevant classes).
CANONICAL_CLASSES = [
    "person",
    "hardhat",
    "no-hardhat",
    "safety-vest",
    "no-safety-vest",
    "excavator",
    "wheel-loader",
    "dozer",
    "roller",
    "crane",
    "dump-truck",
    "cement-truck",
    "water-truck",
    "grader",
    "compactor",
    "car",
    "truck",
    "pickup",
    "cone",
    "drum",
    "barrier",
    "forklift",
    "skid-steer",
    "scissor-lift",
    "boom-lift",
    "telehandler",
]

CLASS_TO_ID = {name: i for i, name in enumerate(CANONICAL_CLASSES)}

# ---------------------------------------------------------------------------
# Source dataset definitions
# ---------------------------------------------------------------------------
# Each entry: (workspace, project, version, label_map)
# label_map: {source_label: canonical_label_or_None}

DATASETS = [
    # ACID — 9917 images of construction equipment
    {
        "name": "ACID Dataset (construction equipment)",
        "workspace": "test-blhxw",
        "project": "acid-dataset",
        "version": 1,
        "label_map": {
            "excavator": "excavator",
            "backhoe_loader": "excavator",      # close enough
            "cement_truck": "cement-truck",
            "compactor": "compactor",
            "dozer": "dozer",
            "dump_truck": "dump-truck",
            "grader": "grader",
            "mobile_crane": "crane",
            "tower_crane": "crane",
            "wheel_loader": "wheel-loader",
        },
    },
    # Hard Hat Universe — 7036 images
    {
        "name": "Hard Hat Universe",
        "workspace": "universe-datasets",
        "project": "hard-hat-universe-0dy7t",
        "version": 1,
        "label_map": {
            "Hard Hats": "hardhat",
            "hard-hat": "hardhat",
            "hardhat": "hardhat",
            "Hard-Hats": "hardhat",
            "NO-Hard-Hats": "no-hardhat",
            "no-hard-hat": "no-hardhat",
            "no-hardhat": "no-hardhat",
            "No-Hard-Hats": "no-hardhat",
            "person": "person",
            "Person": "person",
            "head": "no-hardhat",  # bare head = no hardhat (6,677 annotations!)
            "Head": "no-hardhat",
        },
    },
    # Safety Vests — 3897 images
    {
        "name": "Safety Vests",
        "workspace": "roboflow-universe-projects",
        "project": "safety-vests",
        "version": 1,
        "label_map": {
            "vest": "safety-vest",
            "safety-vest": "safety-vest",
            "Vest": "safety-vest",
            "Safety Vest": "safety-vest",
            "no-vest": "no-safety-vest",
            "no-safety-vest": "no-safety-vest",
            "No-Vest": "no-safety-vest",
            "No-Safety-Vest": "no-safety-vest",
            "NO-Safety Vest": "no-safety-vest",
            "No-Safety Vest": "no-safety-vest",
            "person": "person",
            "Person": "person",
        },
    },
    # Construction Site Safety (Roboflow official) — 2801 images
    {
        "name": "Construction Site Safety",
        "workspace": "roboflow-universe-projects",
        "project": "construction-site-safety",
        "version": 28,
        "label_map": {
            "Hardhat": "hardhat",
            "hardhat": "hardhat",
            "NO-Hardhat": "no-hardhat",
            "no-hardhat": "no-hardhat",
            "Safety Vest": "safety-vest",
            "safety-vest": "safety-vest",
            "NO-Safety Vest": "no-safety-vest",
            "no-safety-vest": "no-safety-vest",
            "Person": "person",
            "person": "person",
            "Mask": None,
            "NO-Mask": None,
            "machinery": "excavator",           # generic machinery → excavator
            "vehicle": "truck",
            "Safety Cone": "cone",
        },
    },
    # Safety Cones — 1703 images
    {
        "name": "Safety Cones",
        "workspace": "roboflow-universe-projects",
        "project": "safety-cones-vfrj2",
        "version": 1,
        "label_map": {
            "cone": "cone",
            "cones": "cone",
            "Cone": "cone",
            "safety-cone": "cone",
            "Safety Cone": "cone",
            "barrel": "drum",
            "Barrel": "drum",
            "drum": "drum",
            "channelizer": "cone",
        },
    },
    # APOCE — 931 aerial construction images
    {
        "name": "APOCE (aerial construction)",
        "workspace": "roboflow100vl-full",
        "project": "apoce-aerial-photographs-for-object-detection-of-construction-equipment-6raie-ryqq",
        "version": 1,
        "label_map": {
            "excavator": "excavator",
            "Excavator": "excavator",
            "bulldozer": "dozer",
            "Bulldozer": "dozer",
            "roller": "roller",
            "Roller": "roller",
            "forklift": "forklift",
            "Forklift": "forklift",
            "tower-crane": "crane",
            "Tower-Crane": "crane",
            "lifting-equipment": "crane",
            "Lifting-Equipment": "crane",
            "concrete-mixer": "cement-truck",
            "Concrete-Mixer": "cement-truck",
            "concrete-pump": "cement-truck",
            "Concrete-Pump": "cement-truck",
            "dump-truck": "dump-truck",
            "Dump-Truck": "dump-truck",
            "piling-machine": None,
            "Piling-Machine": None,
        },
    },

    # ── Wave 2 datasets ─────────────────────────────────────────

    # Excavators RF100 — 2655 images
    {
        "name": "Excavators RF100",
        "workspace": "roboflow-100",
        "project": "excavators-czvg9",
        "version": 1,
        "label_map": {
            "EXCAVATORS": "excavator",
            "excavator": "excavator",
            "Excavator": "excavator",
            "dump truck": "dump-truck",
            "dump_truck": "dump-truck",
            "Dump Truck": "dump-truck",
            "wheel loader": "wheel-loader",
            "wheel_loader": "wheel-loader",
            "Wheel Loader": "wheel-loader",
        },
    },
    # Construction Site Annotations V2 — 4645 images, 46 classes
    {
        "name": "Construction Site Annotations V2",
        "workspace": "michael-batavia",
        "project": "construction-site-annotations-v2",
        "version": 1,
        "label_map": {
            "car": "car",
            "Car": "car",
            "truck": "truck",
            "Truck": "truck",
            "cone": "cone",
            "Cone": "cone",
            "traffic cone": "cone",
            "Safety-cone": "cone",
            "construction_signs": None,  # too generic
            "barricades": "barrier",
            "Barricades": "barrier",
            "safety-barrier": "barrier",
            "Type3Barricade": "barrier",
            "Drum": "drum",
            "drum": "drum",
            "TCP Tube": "cone",
            "worker": "person",
            "Worker": "person",
            "person": "person",
            "Person": "person",
            "hardhat": "hardhat",
            "Hardhat": "hardhat",
            "no-hardhat": "no-hardhat",
            "safety-vest": "safety-vest",
            "Safety-Vest": "safety-vest",
            "no-safety-vest": "no-safety-vest",
            "scaffolding": None,
            "rebar": None,
        },
    },
    # IHT LAB CON+ V2 — 5471 images
    {
        "name": "IHT LAB CON+ V2",
        "workspace": "admin-f6ks4",
        "project": "iht-lab-con-v2-mrezf",
        "version": 1,
        "label_map": {
            "excavator": "excavator",
            "Excavator": "excavator",
            "compactor": "compactor",
            "Compactor": "compactor",
            "dozer": "dozer",
            "Dozer": "dozer",
            "grader": "grader",
            "Grader": "grader",
            "dump_truck": "dump-truck",
            "dump truck": "dump-truck",
            "Dump Truck": "dump-truck",
            "cement_truck": "cement-truck",
            "cement truck": "cement-truck",
            "wheel_loader": "wheel-loader",
            "wheel loader": "wheel-loader",
            "backhoe_loader": "excavator",
            "tower_crane": "crane",
            "mobile_crane": "crane",
            "crane": "crane",
        },
    },
    # CSR Construction Equipment — 1520 images (has skid steer!)
    {
        "name": "CSR Construction Equipment",
        "workspace": "csr-4br13",
        "project": "construction-equipment-6r96y",
        "version": 1,
        "label_map": {
            "Dump Truck": "dump-truck",
            "Excavator": "excavator",
            "Front End Loader": "wheel-loader",
            "Skid Steer": "skid-steer",
            "Tractor Trailer": "truck",
            "Trailer": "truck",
            "Vehicle": "truck",
            "Worker": "person",
            "Hard Hat ON": "hardhat",
            "Hard Hat OFF": "no-hardhat",
            "Safety Vest ON": "safety-vest",
            "Safety Vest OFF": "no-safety-vest",
            "Gloves ON": None,
            "Gloves-OFF": None,
            "Ladder": None,
        },
    },
    # Jersey Barrier — 1028 images
    {
        "name": "Jersey Barrier",
        "workspace": "jersey-barrier",
        "project": "jersey-barrier",
        "version": 1,
        "label_map": {
            "jersey-barrier": "barrier",
            "Jersey-Barrier": "barrier",
            "jersey_barrier": "barrier",
            "barrier": "barrier",
            "Barrier": "barrier",
        },
    },
    # Situational Awareness — 273 images (water-truck, telehandler!)
    {
        "name": "Situational Awareness",
        "workspace": "construction-resources",
        "project": "situational_awareness",
        "version": 1,
        "label_map": {
            "Excavator": "excavator",
            "Dozer": "dozer",
            "Compactor": "compactor",
            "Motor-Grader": "grader",
            "Wheel-Loader": "wheel-loader",
            "Water-Truck": "water-truck",
            "Telehandler": "telehandler",
            "Skid-Steer": "skid-steer",
            "Articulated-Truck": "dump-truck",
            "Backhoe-Loader": "excavator",
            "Truck-Belly-Dump": "dump-truck",
            "Scraper": None,
        },
    },
    # Haul Truck & Scissor Lift — 793 images
    {
        "name": "Haul Truck and Scissor Lift",
        "workspace": "haultruckimages",
        "project": "haul-truck-scissor-lift-new",
        "version": 1,
        "label_map": {
            "Haul Truck": "dump-truck",
            "Haul-Truck": "dump-truck",
            "haul truck": "dump-truck",
            "Scissor-lifts": "scissor-lift",
            "Scissor Lift": "scissor-lift",
            "scissor-lift": "scissor-lift",
            "scissor lift": "scissor-lift",
        },
    },
    # University of Maryland Forklift — 1842 images
    {
        "name": "Univ Maryland Forklift",
        "workspace": "university-of-maryland",
        "project": "forklift-u2ivk",
        "version": 1,
        "label_map": {
            "forklift": "forklift",
            "Forklift": "forklift",
        },
    },
    # CrowdHuman on Roboflow — 9285 images (dense person detection)
    {
        "name": "CrowdHuman (Roboflow)",
        "workspace": "keio-dba-team",
        "project": "crowdhuman-nur7g",
        "version": 1,
        "label_map": {
            "person": "person",
            "Person": "person",
            "head": None,  # head boxes not useful for body detection
            "Head": None,
        },
    },
    # People Detection Thermal — 15303 images (IR/night person detection)
    {
        "name": "People Detection Thermal",
        "workspace": "roboflow-universe-projects",
        "project": "people-detection-thermal",
        "version": 1,
        "label_map": {
            "people": "person",
            "People": "person",
            "person": "person",
            "Person": "person",
        },
    },
    # FLIR Dataset — 11492 images (thermal + person/car)
    {
        "name": "FLIR Thermal Dataset",
        "workspace": "thermal-imaging-0hwfw",
        "project": "flir-data-set",
        "version": 1,
        "label_map": {
            "Person": "person",
            "person": "person",
            "Car": "car",
            "car": "car",
            "Bicycle": None,
            "Dog": None,
        },
    },
    # Person-Vehicle Drone — 21000 images
    {
        "name": "Person-Vehicle Drone",
        "workspace": "drone-6hnkw",
        "project": "person-vehicle-cu6xf",
        "version": 1,
        "label_map": {
            "Person": "person",
            "person": "person",
            "Vehicle": "truck",
            "vehicle": "truck",
        },
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def download_dataset(ds: dict, base_dir: Path, api_key: str = "PUBLIC") -> Path:
    """Download a dataset from Roboflow Universe in YOLOv8 format."""
    from roboflow import Roboflow

    print(f"\n{'='*60}")
    print(f"Downloading: {ds['name']}")
    print(f"  {ds['workspace']}/{ds['project']} v{ds['version']}")
    print(f"{'='*60}")

    rf = Roboflow(api_key=api_key)
    workspace = rf.workspace(ds["workspace"])
    project = workspace.project(ds["project"])
    version = project.version(ds["version"])

    dest = base_dir / ds["project"]
    dataset = version.download("yolov8", location=str(dest), overwrite=True)
    print(f"  Downloaded to {dest}")
    return dest


def read_class_names(dataset_dir: Path) -> list[str]:
    """Read class names from data.yaml in a downloaded YOLO dataset."""
    import yaml
    yaml_path = dataset_dir / "data.yaml"
    if not yaml_path.exists():
        # Try nested
        for p in dataset_dir.rglob("data.yaml"):
            yaml_path = p
            break
    if not yaml_path.exists():
        print(f"  WARNING: No data.yaml found in {dataset_dir}")
        return []
    with open(yaml_path) as f:
        data = yaml.safe_load(f)
    names = data.get("names", [])
    if isinstance(names, dict):
        # {0: 'class0', 1: 'class1', ...}
        max_id = max(names.keys()) if names else -1
        result = [""] * (max_id + 1)
        for k, v in names.items():
            result[int(k)] = v
        return result
    return list(names)


def remap_annotation(
    label_path: Path,
    source_names: list[str],
    label_map: dict[str, str | None],
) -> str | None:
    """Remap a YOLO annotation file to the canonical taxonomy.

    Returns the remapped annotation text, or None if no valid labels remain.
    """
    lines = label_path.read_text().strip().splitlines()
    remapped = []
    for line in lines:
        parts = line.strip().split()
        if len(parts) < 5:
            continue
        src_id = int(parts[0])
        if src_id >= len(source_names):
            continue
        src_label = source_names[src_id]

        # Try exact match first, then case-insensitive
        canonical = label_map.get(src_label)
        if canonical is None and src_label not in label_map:
            # Try case-insensitive
            for k, v in label_map.items():
                if k.lower() == src_label.lower():
                    canonical = v
                    break
        if canonical is None:
            continue  # Drop this detection

        new_id = CLASS_TO_ID[canonical]
        remapped.append(f"{new_id} {' '.join(parts[1:])}")

    if not remapped:
        return None
    return "\n".join(remapped) + "\n"


def upload_image_with_annotation(
    api_key: str,
    project_id: str,
    image_path: Path,
    annotation_text: str,
    batch_name: str,
    split: str = "train",
) -> bool:
    """Upload a single image + YOLO annotation to the Roboflow project."""
    # Step 1: Upload image
    url = f"https://api.roboflow.com/dataset/{project_id}/upload"
    params = {
        "api_key": api_key,
        "batch": batch_name,
        "split": split,
    }

    with open(image_path, "rb") as f:
        resp = requests.post(
            url,
            params=params,
            files={"file": (image_path.name, f, "image/jpeg")},
        )

    if resp.status_code != 200:
        return False

    data = resp.json()
    image_id = data.get("id")
    if not image_id:
        return False

    # Step 2: Upload annotation
    labelmap = {str(v): k for k, v in CLASS_TO_ID.items()}
    ann_url = f"https://api.roboflow.com/dataset/{project_id}/annotate/{image_id}"
    ann_params = {"api_key": api_key, "name": image_path.stem + ".txt"}
    ann_body = {
        "annotationFile": annotation_text,
        "labelmap": labelmap,
    }
    ann_resp = requests.post(ann_url, params=ann_params, json=ann_body)
    return ann_resp.status_code == 200


def process_dataset(
    ds: dict,
    dataset_dir: Path,
    api_key: str,
    project_id: str,
    dry_run: bool = False,
    max_workers: int = 10,
) -> dict:
    """Remap labels and upload all images from a downloaded dataset.

    Uses concurrent uploads (default 10 threads) for ~10x speedup.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    source_names = read_class_names(dataset_dir)
    if not source_names:
        print(f"  ERROR: Could not read class names for {ds['name']}")
        return {"uploaded": 0, "skipped": 0, "errors": 0}

    print(f"  Source classes: {source_names}")
    label_map = ds["label_map"]
    batch_name = ds["project"]

    stats = {"uploaded": 0, "skipped": 0, "errors": 0}
    stats_lock = threading.Lock()

    def _upload_one(img_path, remapped, rf_split):
        ok = upload_image_with_annotation(
            api_key, project_id, img_path, remapped, batch_name, rf_split
        )
        with stats_lock:
            if ok:
                stats["uploaded"] += 1
            else:
                stats["errors"] += 1

    # Collect all work items first, then upload concurrently
    work_items = []

    for split_name in ["train", "valid", "test"]:
        img_dir = dataset_dir / split_name / "images"
        lbl_dir = dataset_dir / split_name / "labels"
        if not img_dir.exists():
            continue

        images = sorted(img_dir.glob("*.*"))
        rf_split = split_name if split_name != "valid" else "valid"
        print(f"  Processing {split_name}: {len(images)} images")

        for img_path in images:
            if img_path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".bmp"):
                continue

            lbl_path = lbl_dir / (img_path.stem + ".txt")
            if not lbl_path.exists():
                stats["skipped"] += 1
                continue

            remapped = remap_annotation(lbl_path, source_names, label_map)
            if remapped is None:
                stats["skipped"] += 1
                continue

            if dry_run:
                stats["uploaded"] += 1
                continue

            work_items.append((img_path, remapped, rf_split))

    if dry_run or not work_items:
        return stats

    print(f"  Uploading {len(work_items)} images with {max_workers} threads...")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for img_path, remapped, rf_split in work_items:
            futures.append(executor.submit(_upload_one, img_path, remapped, rf_split))

        # Progress reporting
        done_count = 0
        for future in as_completed(futures):
            done_count += 1
            if done_count % 100 == 0:
                with stats_lock:
                    print(f"    {done_count}/{len(work_items)} done ({stats['uploaded']} ok, {stats['errors']} err)")

    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Import datasets to GridFront Detect")
    parser.add_argument("--api-key", required=True, help="Roboflow API key")
    parser.add_argument("--project", default="gridfront-detect", help="Roboflow project ID")
    parser.add_argument("--download-dir", default="training/downloads", help="Where to cache downloads")
    parser.add_argument("--dry-run", action="store_true", help="Remap labels but don't upload")
    parser.add_argument("--only", type=str, help="Only process this dataset (project slug)")
    parser.add_argument("--skip-download", action="store_true", help="Skip download, use cached")
    parser.add_argument("--workers", type=int, default=10, help="Concurrent upload threads (default: 10)")
    args = parser.parse_args()

    base_dir = Path(args.download_dir)
    base_dir.mkdir(parents=True, exist_ok=True)

    total_stats = {"uploaded": 0, "skipped": 0, "errors": 0}

    for ds in DATASETS:
        if args.only and ds["project"] != args.only:
            continue

        dataset_dir = base_dir / ds["project"]

        # Download
        if not args.skip_download:
            try:
                download_dataset(ds, base_dir, api_key=args.api_key)
            except Exception as e:
                print(f"  ERROR downloading {ds['name']}: {e}")
                continue
        elif not dataset_dir.exists():
            print(f"  Skipping {ds['name']} — not cached")
            continue

        # Remap + upload
        stats = process_dataset(ds, dataset_dir, args.api_key, args.project, args.dry_run, args.workers)
        print(f"\n  Results for {ds['name']}:")
        print(f"    Uploaded: {stats['uploaded']}")
        print(f"    Skipped:  {stats['skipped']} (no matching labels)")
        print(f"    Errors:   {stats['errors']}")

        for k in total_stats:
            total_stats[k] += stats[k]

    print(f"\n{'='*60}")
    print(f"TOTAL: {total_stats['uploaded']} uploaded, "
          f"{total_stats['skipped']} skipped, {total_stats['errors']} errors")
    print(f"{'='*60}")
    print(f"\nCanonical classes ({len(CANONICAL_CLASSES)}):")
    for i, name in enumerate(CANONICAL_CLASSES):
        print(f"  {i:2d}: {name}")


if __name__ == "__main__":
    main()
