"""Classify detections into DANGER / WARNING / CLEAR zones.

Zone distance is measured from the detection to the nearest edge of the
machine's bounding-box footprint — *not* from the machine centre.  This
gives correct behaviour for long vehicles where a person standing 2 m
from the rear bumper is much closer than their distance to the centre
would suggest.
"""

from __future__ import annotations

import logging
import math
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


class ZoneClassifier:
    """Classify detections relative to the machine footprint."""

    def __init__(
        self,
        machine_dimensions: Dict[str, float],
        zone_config: Dict[str, float],
    ):
        """
        Args:
            machine_dimensions: ``{"length_m": 8.4, "width_m": 2.5, "height_m": 3.4}``
            zone_config: ``{"danger_m": 3.5, "warning_m": 6.0, "max_range_m": 12.0}``
        """
        self.half_length = machine_dimensions["length_m"] / 2.0
        self.half_width = machine_dimensions["width_m"] / 2.0
        self.danger_m = zone_config["danger_m"]
        self.warning_m = zone_config["warning_m"]
        self.max_range_m = zone_config["max_range_m"]

        logger.info(
            "ZoneClassifier: machine %.1f x %.1f m, danger=%.1f m, warning=%.1f m",
            machine_dimensions["length_m"],
            machine_dimensions["width_m"],
            self.danger_m,
            self.warning_m,
        )

    # ------------------------------------------------------------------
    # Single detection
    # ------------------------------------------------------------------

    def classify(self, detection: dict) -> Tuple[str, float]:
        """Classify one detection by its distance to the machine bounding box edge.

        The machine footprint is an axis-aligned rectangle centred at the
        origin, extending ``[-half_width, half_width]`` in X and
        ``[-half_length, half_length]`` in Z.

        Returns:
            ``(zone_label, edge_distance_m)``
        """
        x = detection["x_m"]
        z = detection["z_m"]

        # Nearest point on the bounding-box perimeter (clamped)
        nearest_x = max(-self.half_width, min(self.half_width, x))
        nearest_z = max(-self.half_length, min(self.half_length, z))

        dx = x - nearest_x
        dz = z - nearest_z
        edge_dist = math.sqrt(dx * dx + dz * dz)

        # If the detection is *inside* the box, edge_dist is 0 -> DANGER
        if edge_dist <= self.danger_m:
            return "DANGER", edge_dist
        elif edge_dist <= self.warning_m:
            return "WARNING", edge_dist
        else:
            return "CLEAR", edge_dist

    # ------------------------------------------------------------------
    # Batch classification
    # ------------------------------------------------------------------

    def classify_all(self, detections: List[dict]) -> List[dict]:
        """Classify a list of detections in place.

        Adds ``zone``, ``distance_m``, and ``bearing_deg`` fields to each
        detection dict.  Detections beyond ``max_range_m`` are tagged CLEAR
        but still included (the UI may choose to hide them).

        Returns:
            The same list, mutated, for convenience.
        """
        for det in detections:
            zone, dist = self.classify(det)
            # Fail-loud: any detection tagged ``unsafe`` (camera bumped,
            # IMU lost, mount likely shifted) is promoted straight to
            # DANGER regardless of geometric distance. The zone we
            # *computed* is no longer trustworthy for that camera, so
            # we refuse to report anything softer.
            if det.get("unsafe"):
                zone = "DANGER"
            det["zone"] = zone
            det["distance_m"] = round(dist, 2)
            det["bearing_deg"] = round(
                math.degrees(math.atan2(det["x_m"], det["z_m"])), 1
            )
        return detections
