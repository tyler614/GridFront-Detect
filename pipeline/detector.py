"""Object detection using OAK-D neural network output + depth estimation.

Takes RGB frames, depth maps, and MobileNet-SSD detections from the OAK-D
driver and produces typed Detection objects with 3D positions.

Pure numpy — no depthai dependency required at import time.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np

from .depth_estimator import (
    CameraIntrinsics,
    OAK_D_PRO_W_400P,
    distance_3d,
    pixel_to_3d,
    sample_depth,
)


@dataclass
class Detection:
    """A single detected object with 3D position in camera-local metres."""

    track_id: int
    label: str          # "person", "vehicle", etc.
    confidence: float   # 0-1
    bbox: tuple         # (x1, y1, x2, y2) normalised 0-1
    x_m: float          # X position in camera-local metres (right +)
    y_m: float          # Y position (up +)
    z_m: float          # Z position (forward +, i.e. depth)
    distance_m: float   # Euclidean distance from camera

    def to_dict(self) -> Dict[str, Any]:
        return {
            "track_id": self.track_id,
            "label": self.label,
            "confidence": round(self.confidence, 2),
            "bbox": tuple(round(v, 4) for v in self.bbox),
            "x_m": round(self.x_m, 2),
            "y_m": round(self.y_m, 2),
            "z_m": round(self.z_m, 2),
            "distance_m": round(self.distance_m, 2),
        }


# ── MobileNet-SSD class ID → GridFront label mapping ────────────────────────
# Only the IDs we care about are listed; everything else is ignored.
_MOBILENET_LABEL_MAP: Dict[int, str] = {
    15: "person",
    6: "vehicle",   # bus
    7: "vehicle",   # car
    14: "vehicle",  # motorbike
}


def _get_attr(det, key: str, default=None):
    """Read an attribute from either a depthai detection object or a dict."""
    if isinstance(det, dict):
        return det.get(key, default)
    return getattr(det, key, default)


class Detector:
    """Processes OAK-D NN detections into typed 3D Detection objects.

    Usage::

        from pipeline.depth_estimator import OAK_D_PRO_W_400P
        det = Detector(intrinsics=OAK_D_PRO_W_400P)
        results = det.process_frame(rgb, depth, nn_detections)
    """

    def __init__(
        self,
        intrinsics: CameraIntrinsics = OAK_D_PRO_W_400P,
        confidence_threshold: float = 0.5,
        max_depth_m: float = 30.0,
        depth_patch_size: int = 5,
        label_map: Optional[Dict[int, str]] = None,
    ):
        self.intrinsics = intrinsics
        self.confidence_threshold = confidence_threshold
        self.max_depth_m = max_depth_m
        self.depth_patch_size = depth_patch_size
        self.label_map = label_map or _MOBILENET_LABEL_MAP

        # Simple counter for assigning initial track IDs (overwritten by Tracker).
        self._next_id = 0

    # ── public API ───────────────────────────────────────────────────────────

    def process_frame(
        self,
        rgb: np.ndarray,
        depth: np.ndarray,
        nn_detections: list,
    ) -> List[Detection]:
        """Process a single frame and return a list of Detection objects.

        Args:
            rgb: HxWx3 colour image (used for reference only, not processed).
            depth: HxW depth map — float32 metres or uint16 millimetres.
            nn_detections: List of NN detection results.  Each item is either a
                depthai ``ImgDetection`` (attributes: label, confidence, xmin,
                ymin, xmax, ymax) or a plain dict with the same keys.

        Returns:
            List of valid Detection instances with 3D positions.
        """
        results: List[Detection] = []

        for det in nn_detections:
            label_id = int(_get_attr(det, "label", -1))
            label_str = self.label_map.get(label_id)
            if label_str is None:
                continue  # Not a class we care about.

            confidence = float(_get_attr(det, "confidence", 0.0))
            if confidence < self.confidence_threshold:
                continue

            xmin = float(_get_attr(det, "xmin", 0.0))
            ymin = float(_get_attr(det, "ymin", 0.0))
            xmax = float(_get_attr(det, "xmax", 0.0))
            ymax = float(_get_attr(det, "ymax", 0.0))
            bbox = (xmin, ymin, xmax, ymax)

            # ── Depth sampling ───────────────────────────────────────────
            depth_m = sample_depth(
                depth, bbox, patch_size=self.depth_patch_size
            )
            if depth_m <= 0.0 or not np.isfinite(depth_m):
                continue
            if depth_m > self.max_depth_m:
                continue

            # ── Back-project to 3D ───────────────────────────────────────
            # Centre pixel of the bbox.
            px = (xmin + xmax) / 2.0 * self.intrinsics.width
            py = (ymin + ymax) / 2.0 * self.intrinsics.height

            x_m, y_m, z_m = pixel_to_3d(px, py, depth_m, self.intrinsics)
            dist = distance_3d(x_m, y_m, z_m)

            track_id = self._next_id
            self._next_id += 1

            results.append(
                Detection(
                    track_id=track_id,
                    label=label_str,
                    confidence=confidence,
                    bbox=bbox,
                    x_m=x_m,
                    y_m=y_m,
                    z_m=z_m,
                    distance_m=dist,
                )
            )

        return results
