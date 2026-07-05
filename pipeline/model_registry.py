"""Model registry — available detection models and their metadata.

Each model defines:
    - slug: HubAI model identifier used by SpatialDetectionNetwork.build()
    - classes: list of class names the model detects (in label-index order)
    - input_size: (width, height) the model expects
    - description: human-readable summary

Only one model runs on the VPU at a time. Switching models requires a
pipeline restart.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ModelDef:
    """A single detection model definition."""

    id: str                         # Unique key (e.g. "yolov10n-coco")
    name: str                       # Display name
    slug: str                       # HubAI slug for SpatialDetectionNetwork.build()
    classes: list[str]              # Ordered class names (index = label ID)
    input_size: tuple[int, int]     # (width, height)
    description: str = ""
    source: str = "hubai"           # "hubai" | "local" | "custom"
    blob_path: Optional[str] = None # Override slug with local .blob file

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "classes": self.classes,
            "input_size": list(self.input_size),
            "description": self.description,
            "source": self.source,
            "class_count": len(self.classes),
        }


# ── COCO 80-class labels (shared by all COCO-trained models) ────────────
COCO_LABELS = [
    "person", "bicycle", "car", "motorbike", "aeroplane", "bus", "train",
    "truck", "boat", "traffic light", "fire hydrant", "stop sign",
    "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
    "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard",
    "sports ball", "kite", "baseball bat", "baseball glove", "skateboard",
    "surfboard", "tennis racket", "bottle", "wine glass", "cup", "fork",
    "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "sofa", "pottedplant", "bed", "diningtable", "toilet", "tvmonitor",
    "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave",
    "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
    "scissors", "teddy bear", "hair drier", "toothbrush",
]

# ── PPE / Construction safety labels ────────────────────────────────────
PPE_LABELS = [
    "Hardhat", "Mask", "NO-Hardhat", "NO-Mask", "NO-Safety Vest",
    "Person", "Safety Cone", "Safety Vest", "machinery", "vehicle",
]

# ── GridFront Radius labels (the in-house model taxonomy) ───────────────
# Radius is GridFront's detection model line for Scout. v1 ships from the
# license-clean training rebuild (see training/radius/README.md).
RADIUS_LABELS = [
    "person", "excavator", "wheel-loader", "dozer", "crane",
    "dump-truck", "grader", "compactor", "cone",
]


# ── Available models ────────────────────────────────────────────────────
MODELS: dict[str, ModelDef] = {}


def _register(m: ModelDef) -> None:
    MODELS[m.id] = m


# -- YOLOv6 Nano COCO (fast, baseline) --
_register(ModelDef(
    id="yolov6n-coco",
    name="YOLOv6 Nano (General)",
    slug="yolov6-nano",
    classes=COCO_LABELS,
    input_size=(512, 288),
    description="Fastest general model. 80 COCO classes, ~64 FPS on Myriad X.",
))

# -- GridFront Radius v1 (in-house, license-clean rebuild) --
# REMOVED 2026-07-05: the old "gridfront-scout-v1" model (Ultralytics
# YOLO11n) was deleted — Ultralytics claims AGPL-3.0 over trained weights,
# and its training merge included non-commercial datasets (ACID CC BY-NC,
# CrowdHuman, thermal sets). Not shippable in a commercial product.
# Radius v1 replaces it: YOLOv6-N @ 640x384 trained per
# training/radius/README.md. Register it here once trained:
#
# _register(ModelDef(
#     id="radius-v1",
#     name="GridFront Radius v1",
#     slug="",  # local blob, slug unused
#     classes=RADIUS_LABELS,
#     input_size=(640, 384),
#     description="Radius v1 — YOLOv6-N, license-clean construction taxonomy.",
#     source="local",
#     blob_path="models/radius-v1.blob",
# ))


# ── Default model ───────────────────────────────────────────────────────
# yolov6n-coco until Radius v1 lands. (Zoo COCO weights: fine for dev/demo;
# Radius v1 is the shippable artifact.)
DEFAULT_MODEL_ID = "yolov6n-coco"


def get_model(model_id: str) -> ModelDef | None:
    """Look up a model by ID."""
    return MODELS.get(model_id)


def get_default_model() -> ModelDef:
    """Return the default model."""
    return MODELS[DEFAULT_MODEL_ID]


def list_models() -> list[dict]:
    """Return all models as dicts for the API."""
    return [m.to_dict() for m in MODELS.values()]
