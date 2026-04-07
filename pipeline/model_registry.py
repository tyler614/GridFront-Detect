"""Model registry — available detection models and their metadata.

Each model defines:
    - slug: HubAI model identifier used by SpatialDetectionNetwork.build()
    - classes: list of class names the model detects (in label-index order)
    - input_size: (width, height) the model expects
    - source: "hubai" to pull from Luxonis Hub, "local" to load a blob
      from ``blob_path`` (relative to the project root).
    - blob_path: when source="local", path to the compiled Myriad X blob

Only one model runs on the VPU at a time. Switching models requires a
pipeline restart.

Notes on the available COCO models:
* Luxonis's public HubAI zoo for RVC2 (Myriad X) only hosts YOLOv6n
  and YOLOv10n in COCO-trained public blobs. YOLOv8n/v11n are NOT
  published for RVC2 as of Apr 2026 — you have to compile them yourself.
* YOLOv6n (r2, 512x288) is the off-the-shelf generic — ~30 FPS
  on Myriad X with >95% person recall inside the 12 m danger zone.
  It exists purely as a placeholder for dev and for initial machine
  commissioning. In production, the proprietary GridFront-v1 model
  (YOLOv8n @ 416, INT8, custom-trained on site footage) replaces it
  via the ``source="local"`` slot below.
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

# ── Available models ────────────────────────────────────────────────────
MODELS: dict[str, ModelDef] = {}


def _register(m: ModelDef) -> None:
    MODELS[m.id] = m


# ── YOLOv6n COCO 512×288 — the off-the-shelf generic detector ─────────
#
# The stock placeholder model, pulled from Luxonis's public HubAI
# zoo (no compilation needed). Runs ~30 FPS on Myriad X with person
# recall >95% inside the 12 m danger zone — good enough for demos,
# dev, and initial commissioning.
#
# This model gets REPLACED by the user's GridFront-v1 proprietary
# blob in production. See the "gridfront-v1" entry below for how
# local-blob loading works.
_register(ModelDef(
    id="yolov6n-coco",
    name="YOLOv6 Nano (Generic 80-class)",
    slug="luxonis/yolov6-nano:r2-coco-512x288",
    classes=COCO_LABELS,
    input_size=(512, 288),
    description=(
        "Off-the-shelf 80-class COCO detector. YOLOv6n — ~30 FPS on "
        "Myriad X. Placeholder until GridFront-v1 custom model is "
        "trained and compiled."
    ),
))


# ── GridFront-v1 (proprietary, local blob) ────────────────────────────
#
# Placeholder registration for the user-trained YOLOv8n model. The
# actual blob will land at pipeline/models/yolov8n-gridfront-v1.blob
# after the training → ONNX → INT8 → blob pipeline completes. Until
# then, this entry is "registered but inert" — trying to activate it
# will surface a clean "blob not found" error in the UI rather than
# crashing the pipeline.
#
# When the blob is ready, drop it at the path below and flip
# active_model in config.json to "yolov8n-gridfront-v1". No code
# changes required — oak_driver.py already handles source="local"
# via the ``model_def.blob_path`` loading path.
_register(ModelDef(
    id="yolov8n-gridfront-v1",
    name="GridFront-v1 (Custom)",
    slug="",  # unused when source="local"
    classes=COCO_LABELS,  # override after training if class list changes
    input_size=(416, 416),
    description=(
        "Proprietary GridFront-v1 detector — YOLOv8n @ 416 INT8, "
        "trained on GridFront construction-site footage. Drop blob "
        "at pipeline/models/yolov8n-gridfront-v1.blob to activate."
    ),
    source="local",
    blob_path="pipeline/models/yolov8n-gridfront-v1.blob",
))


# ── Default model ───────────────────────────────────────────────────────
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
