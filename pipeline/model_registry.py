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

# ── GridFront Scout V1 labels (custom-trained) ─────────────────────────
GRIDFRONT_V1_LABELS = [
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

# -- GridFront Scout V1 (custom, in-house construction equipment) --
_register(ModelDef(
    id="gridfront-scout-v1",
    name="GridFront Scout V1",
    slug="",  # local blob, slug unused
    classes=GRIDFRONT_V1_LABELS,
    input_size=(512, 288),
    description="In-house YOLOv8n trained on construction equipment. 9 classes.",
    source="local",
    blob_path="models/gridfront-scout-v1.blob",
))


# ── Default model ───────────────────────────────────────────────────────
DEFAULT_MODEL_ID = "gridfront-scout-v1"


def get_model(model_id: str) -> ModelDef | None:
    """Look up a model by ID."""
    return MODELS.get(model_id)


def get_default_model() -> ModelDef:
    """Return the default model."""
    return MODELS[DEFAULT_MODEL_ID]


def list_models() -> list[dict]:
    """Return all models as dicts for the API."""
    return [m.to_dict() for m in MODELS.values()]
