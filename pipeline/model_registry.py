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

# -- YOLOv10 Nano COCO (better accuracy, still fast) --
_register(ModelDef(
    id="yolov10n-coco",
    name="YOLOv10 Nano (General)",
    slug="luxonis/yolov10-nano:coco-512x288",
    classes=COCO_LABELS,
    input_size=(512, 288),
    description="Better accuracy than v6, 80 COCO classes. ~29 FPS on Myriad X.",
))

# -- PPE / Construction Safety (purpose-built) --
_register(ModelDef(
    id="ppe-construction",
    name="PPE Detection (Construction)",
    slug="luxonis/ppe-detection:640x640",
    classes=PPE_LABELS,
    input_size=(640, 640),
    description="Construction safety: hardhats, vests, cones, machinery, vehicles. ~13 FPS.",
))

# -- Person Detection (high-accuracy, single-class) --
_register(ModelDef(
    id="scrfd-person",
    name="Person Detection (SCRFD)",
    slug="luxonis/scrfd-person-detection:r2-640x640",
    classes=["person"],
    input_size=(640, 640),
    description="High-accuracy person-only detector. Best for people-around-machinery alerts.",
))

# -- Fire Detection --
_register(ModelDef(
    id="fire-detection",
    name="Fire Detection",
    slug="luxonis/fire-detection:r2-416x416",
    classes=["fire"],
    input_size=(416, 416),
    description="Detects fire and flames. Useful for equipment fire safety.",
))

# -- YOLOv6 Large COCO (highest accuracy, slower) --
_register(ModelDef(
    id="yolov6l-coco",
    name="YOLOv6 Large (General)",
    slug="luxonis/yolov6-large:r2-coco-512x288",
    classes=COCO_LABELS,
    input_size=(512, 288),
    description="Highest accuracy general model. 80 COCO classes, ~8 FPS on Myriad X.",
))


# ── Default model ───────────────────────────────────────────────────────
DEFAULT_MODEL_ID = "yolov10n-coco"


def get_model(model_id: str) -> ModelDef | None:
    """Look up a model by ID."""
    return MODELS.get(model_id)


def get_default_model() -> ModelDef:
    """Return the default model."""
    return MODELS[DEFAULT_MODEL_ID]


def list_models() -> list[dict]:
    """Return all models as dicts for the API."""
    return [m.to_dict() for m in MODELS.values()]
