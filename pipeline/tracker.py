"""Simple IoU-based multi-object tracker with ID persistence.

Greedy matching — no scipy dependency required.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
import time

import numpy as np

from .detector import Detection


@dataclass
class Track:
    """Internal state for a single tracked object."""

    track_id: int
    label: str
    bbox: tuple         # Last known bbox (x1, y1, x2, y2) normalised 0-1
    x_m: float
    y_m: float
    z_m: float
    confidence: float
    last_seen: float    # timestamp (time.monotonic)
    age: int = 0        # frames since creation
    hits: int = 1       # total detection matches
    lost: int = 0       # consecutive frames without a match


def _iou(a: tuple, b: tuple) -> float:
    """Compute Intersection-over-Union between two (x1, y1, x2, y2) boxes."""
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])

    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter == 0.0:
        return 0.0

    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    if union <= 0.0:
        return 0.0
    return inter / union


class Tracker:
    """IoU-based multi-object tracker.

    Assigns persistent ``track_id`` values across frames so that the same
    physical object keeps its ID as long as it remains visible (or is only
    briefly occluded).

    Usage::

        tracker = Tracker()
        for frame_detections in stream:
            tracked = tracker.update(frame_detections)
            # Each Detection in `tracked` now has a stable track_id.
    """

    def __init__(
        self,
        max_lost_frames: int = 30,
        iou_threshold: float = 0.3,
    ):
        self.max_lost_frames = max_lost_frames
        self.iou_threshold = iou_threshold

        self._tracks: Dict[int, Track] = {}
        self._next_id: int = 0

    # ── public API ───────────────────────────────────────────────────────────

    def update(self, detections: List[Detection]) -> List[Detection]:
        """Match new detections against existing tracks and return updated list.

        Detections are returned with their ``track_id`` set to the matched
        (or newly created) persistent ID.
        """
        now = time.monotonic()
        track_list = list(self._tracks.values())

        if not track_list or not detections:
            # No matching possible — handle the simple cases.
            self._mark_all_lost(track_list, now)
            return self._init_new_tracks(detections, set(), now)

        # ── Build IoU matrix (tracks × detections) ───────────────────────
        iou_matrix = np.zeros((len(track_list), len(detections)), dtype=np.float64)
        for t_idx, trk in enumerate(track_list):
            for d_idx, det in enumerate(detections):
                iou_matrix[t_idx, d_idx] = _iou(trk.bbox, det.bbox)

        matches = self._greedy_match(iou_matrix)
        matched_track_idxs: Set[int] = {t for t, _ in matches}
        matched_det_idxs: Set[int] = {d for _, d in matches}

        # ── Update matched tracks ────────────────────────────────────────
        output: List[Detection] = []
        for t_idx, d_idx in matches:
            trk = track_list[t_idx]
            det = detections[d_idx]

            trk.bbox = det.bbox
            trk.x_m = det.x_m
            trk.y_m = det.y_m
            trk.z_m = det.z_m
            trk.confidence = det.confidence
            trk.label = det.label
            trk.last_seen = now
            trk.age += 1
            trk.hits += 1
            trk.lost = 0

            # Re-stamp the detection with the persistent track ID.
            output.append(
                Detection(
                    track_id=trk.track_id,
                    label=det.label,
                    confidence=det.confidence,
                    bbox=det.bbox,
                    x_m=det.x_m,
                    y_m=det.y_m,
                    z_m=det.z_m,
                    distance_m=det.distance_m,
                )
            )

        # ── Handle unmatched tracks (increment lost) ────────────────────
        for t_idx, trk in enumerate(track_list):
            if t_idx in matched_track_idxs:
                continue
            trk.lost += 1
            trk.age += 1
            if trk.lost > self.max_lost_frames:
                del self._tracks[trk.track_id]

        # ── Create new tracks for unmatched detections ───────────────────
        new_dets = self._init_new_tracks(detections, matched_det_idxs, now)
        output.extend(new_dets)

        return output

    @property
    def active_track_count(self) -> int:
        """Number of tracks currently being maintained (including lost)."""
        return len(self._tracks)

    # ── internals ────────────────────────────────────────────────────────────

    def _greedy_match(
        self, iou_matrix: np.ndarray
    ) -> List[Tuple[int, int]]:
        """Greedy IoU matching — sort all pairs by IoU descending, pick top."""
        matches: List[Tuple[int, int]] = []
        used_tracks: Set[int] = set()
        used_dets: Set[int] = set()

        pairs = []
        for t in range(iou_matrix.shape[0]):
            for d in range(iou_matrix.shape[1]):
                if iou_matrix[t, d] >= self.iou_threshold:
                    pairs.append((iou_matrix[t, d], t, d))
        pairs.sort(reverse=True)

        for _iou_val, t, d in pairs:
            if t not in used_tracks and d not in used_dets:
                matches.append((t, d))
                used_tracks.add(t)
                used_dets.add(d)

        return matches

    def _mark_all_lost(self, track_list: List[Track], now: float) -> None:
        """Increment lost counter on every track; prune expired ones."""
        for trk in track_list:
            trk.lost += 1
            trk.age += 1
            if trk.lost > self.max_lost_frames:
                del self._tracks[trk.track_id]

    def _init_new_tracks(
        self,
        detections: List[Detection],
        skip_idxs: Set[int],
        now: float,
    ) -> List[Detection]:
        """Create new Track entries for unmatched detections."""
        output: List[Detection] = []

        for d_idx, det in enumerate(detections):
            if d_idx in skip_idxs:
                continue

            tid = self._next_id
            self._next_id += 1

            self._tracks[tid] = Track(
                track_id=tid,
                label=det.label,
                bbox=det.bbox,
                x_m=det.x_m,
                y_m=det.y_m,
                z_m=det.z_m,
                confidence=det.confidence,
                last_seen=now,
            )

            output.append(
                Detection(
                    track_id=tid,
                    label=det.label,
                    confidence=det.confidence,
                    bbox=det.bbox,
                    x_m=det.x_m,
                    y_m=det.y_m,
                    z_m=det.z_m,
                    distance_m=det.distance_m,
                )
            )

        return output
