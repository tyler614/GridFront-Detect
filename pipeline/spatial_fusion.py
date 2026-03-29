"""Transform camera-local detections into machine-centered world coordinates.

Each OAK-D camera produces detections in its own local coordinate frame
(X right, Y up, Z forward).  This module applies the camera's mount
transform to place every detection in a shared *machine-body* frame whose
origin sits at the geometric centre of the machine footprint on the ground
plane.

After transformation, duplicate detections (the same real-world object seen
by overlapping cameras) are merged so downstream consumers get a single
entry per physical entity.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


class SpatialFusion:
    """Multi-camera coordinate fusion and duplicate merging."""

    def __init__(self, camera_transforms: Dict[str, dict]):
        """Initialise with per-camera mount descriptions.

        Args:
            camera_transforms: mapping of camera_id to mount info, e.g.::

                {
                    "cam-front": {"position": [0, 2.8, 4.2], "rotation": [0, 0, 0]},
                    "cam-rear":  {"position": [0, 2.5, -4.2], "rotation": [0, 180, 0]},
                }

            *position* is ``[x, y, z]`` metres in the machine-body frame.
            *rotation* is ``[rx, ry, rz]`` degrees (Euler XYZ extrinsic).
        """
        self.transforms: Dict[str, np.ndarray] = {}
        for cam_id, mount in camera_transforms.items():
            self.transforms[cam_id] = self._build_transform(
                mount["position"], mount["rotation"]
            )
        logger.info(
            "SpatialFusion initialised with %d camera transform(s)", len(self.transforms)
        )

    # ------------------------------------------------------------------
    # Transform construction
    # ------------------------------------------------------------------

    @staticmethod
    def _build_transform(
        position: List[float], rotation_deg: List[float]
    ) -> np.ndarray:
        """Build a 4x4 homogeneous transform from mount position and rotation.

        The rotation is specified as extrinsic Euler angles (degrees) applied
        in XYZ order:  R = Rz * Ry * Rx.
        """
        rx, ry, rz = [math.radians(a) for a in rotation_deg]

        # Individual rotation matrices
        cx, sx = math.cos(rx), math.sin(rx)
        cy, sy = math.cos(ry), math.sin(ry)
        cz, sz = math.cos(rz), math.sin(rz)

        # Combined rotation R = Rz * Ry * Rx
        R = np.array(
            [
                [cy * cz, sx * sy * cz - cx * sz, cx * sy * cz + sx * sz],
                [cy * sz, sx * sy * sz + cx * cz, cx * sy * sz - sx * cz],
                [-sy,     sx * cy,                 cx * cy],
            ],
            dtype=np.float64,
        )

        T = np.eye(4, dtype=np.float64)
        T[:3, :3] = R
        T[0, 3] = position[0]
        T[1, 3] = position[1]
        T[2, 3] = position[2]
        return T

    # ------------------------------------------------------------------
    # Per-camera transform
    # ------------------------------------------------------------------

    def transform_detections(
        self, detections: list, camera_id: str
    ) -> List[dict]:
        """Transform detections from camera-local to machine-world coordinates.

        Each detection must expose ``x_m``, ``y_m``, ``z_m`` (camera-local
        metres).  Accepts Detection dataclass instances (via ``.to_dict()``)
        or plain dicts.

        Returns a list of dicts with world-coordinate positions and the
        originating ``camera_id`` tag.
        """
        T = self.transforms.get(camera_id)
        if T is None:
            logger.warning(
                "No transform registered for camera '%s' — skipping %d detection(s)",
                camera_id,
                len(detections),
            )
            return []

        world_dets: List[dict] = []
        for det in detections:
            d = det.to_dict() if hasattr(det, "to_dict") else dict(det)

            local = np.array(
                [d["x_m"], d["y_m"], d["z_m"], 1.0], dtype=np.float64
            )
            world = T @ local

            d["x_m"] = round(float(world[0]), 2)
            d["y_m"] = round(float(world[1]), 2)
            d["z_m"] = round(float(world[2]), 2)
            d["camera_id"] = camera_id
            world_dets.append(d)

        return world_dets

    # ------------------------------------------------------------------
    # Duplicate merging
    # ------------------------------------------------------------------

    def merge_duplicates(
        self, all_detections: List[dict], distance_threshold: float = 1.5
    ) -> List[dict]:
        """Merge detections that are likely the same physical object.

        Within each label group, if two detections are closer than
        *distance_threshold* metres (XZ ground-plane distance) they are
        merged: positions are averaged and the higher-confidence entry is
        kept as the representative.
        """
        if not all_detections:
            return []

        # Group by label
        by_label: Dict[str, List[dict]] = {}
        for d in all_detections:
            by_label.setdefault(d.get("label", "unknown"), []).append(d)

        merged: List[dict] = []
        for label, dets in by_label.items():
            used = [False] * len(dets)
            for i in range(len(dets)):
                if used[i]:
                    continue
                cluster = [dets[i]]
                used[i] = True

                for j in range(i + 1, len(dets)):
                    if used[j]:
                        continue
                    dx = dets[i]["x_m"] - dets[j]["x_m"]
                    dz = dets[i]["z_m"] - dets[j]["z_m"]
                    dist = math.sqrt(dx * dx + dz * dz)
                    if dist < distance_threshold:
                        cluster.append(dets[j])
                        used[j] = True

                # Pick highest-confidence detection as representative
                rep = max(cluster, key=lambda d: d.get("confidence", 0))
                if len(cluster) > 1:
                    # Average positions across the cluster
                    avg_x = sum(d["x_m"] for d in cluster) / len(cluster)
                    avg_y = sum(d["y_m"] for d in cluster) / len(cluster)
                    avg_z = sum(d["z_m"] for d in cluster) / len(cluster)
                    rep["x_m"] = round(avg_x, 2)
                    rep["y_m"] = round(avg_y, 2)
                    rep["z_m"] = round(avg_z, 2)
                    # Record which cameras contributed
                    rep["camera_ids"] = list(
                        set(d.get("camera_id", "") for d in cluster)
                    )
                merged.append(rep)

        return merged

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def fuse(
        self,
        camera_detections: Dict[str, list],
        distance_threshold: float = 1.5,
    ) -> List[dict]:
        """Transform per-camera detections into a unified world-coordinate list.

        Args:
            camera_detections: mapping ``camera_id -> [Detection, ...]``
            distance_threshold: merge radius in metres (XZ plane)

        Returns:
            Merged list of detection dicts in machine-world coordinates.
        """
        all_world: List[dict] = []
        for cam_id, dets in camera_detections.items():
            if cam_id not in self.transforms:
                logger.debug("Skipping unknown camera '%s'", cam_id)
                continue
            world_dets = self.transform_detections(dets, cam_id)
            all_world.extend(world_dets)

        return self.merge_duplicates(all_world, distance_threshold)
