"""Multi-object trackers with ID persistence.

Two trackers live here:

* :class:`Tracker` — the original IoU-based pixel-space tracker. Matches
  detections frame-to-frame by bounding-box IoU. Used when you want
  per-camera track IDs tied to image-plane boxes.

* :class:`WorldTracker` — a distance-based tracker operating in
  machine-world ground-plane coordinates (``x_m``, ``z_m``). Runs after
  :class:`SpatialFusion` so that a person walking around the machine
  keeps the same track ID as they pass through different cameras' fields
  of view. This is what powers unified multi-camera tracking.

Both use greedy matching — no scipy dependency required.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

# Module-level smoothing constants. Tuned for "spatial view should glide,
# not flicker" while still snapping to fast movement. See WorldTracker.
_POS_ALPHA_NEW = 0.6           # First few hits — snap toward truth fast
_POS_ALPHA_ESTABLISHED = 0.22  # After 3+ hits — heavier low-pass for glide
_POS_NEW_HITS = 3
_COAST_FRAMES = 12             # How many lost frames to keep emitting predicted dots
# When a new detection lands within this radius of an existing track but
# carries a different label (e.g. YOLO flips person↔vehicle on the same
# physical object), accept it as a label *correction* rather than spawning
# a new track. Outside this radius the labels must agree.
_LABEL_OVERRIDE_RADIUS_M = 0.6
import math
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


# ────────────────────────────────────────────────────────────────────────
# WorldTracker — post-fusion ground-plane tracker
# ────────────────────────────────────────────────────────────────────────


@dataclass
class WorldTrack:
    """Internal state for a world-space track.

    Position fields (``x_m``/``z_m``/``y_m``) hold the **smoothed** state —
    a low-pass filtered estimate that absorbs depth jitter so the UI can
    render a stable dot. The raw measurement gets blended in via EMA on
    every match (see ``WorldTracker.update``). Velocity is estimated from
    successive smoothed positions (not raw) so a single noisy reading
    doesn't kick the velocity sky-high and ruin the predicted coast.
    """

    track_id: int
    label: str
    x_m: float
    z_m: float
    y_m: float = 0.0
    vx: float = 0.0         # Estimated velocity m/s (x)
    vz: float = 0.0         # Estimated velocity m/s (z)
    confidence: float = 0.0
    last_seen: float = 0.0  # time.monotonic() of last match
    age: int = 0
    hits: int = 1
    lost: int = 0
    cameras_seen: Set[str] = field(default_factory=set)
    last_bbox: Optional[tuple] = None  # remembered for coasted emissions
    last_camera_id: Optional[str] = None


class WorldTracker:
    """Distance-based multi-object tracker in machine-world coordinates.

    Operates on **fused detections** — i.e. detection dicts that already
    carry ``x_m`` and ``z_m`` in the machine-body frame (metres, ground
    plane). Matches new detections to existing tracks by Euclidean
    distance on (x, z), with a constant-velocity prediction to bridge
    short-term dropouts.

    Labels must match for a pair to be considered — a person never
    becomes a vehicle. Within a label, greedy nearest matching is used.

    Output: the same list of dicts, mutated in-place to have a
    ``track_id`` that is stable across cameras and across frames.
    """

    def __init__(
        self,
        match_distance_m: float = 1.8,
        max_lost_frames: int = 30,
        velocity_smoothing: float = 0.4,
    ):
        self.match_distance_m = match_distance_m
        self.max_lost_frames = max_lost_frames
        self.velocity_smoothing = velocity_smoothing

        self._tracks: Dict[int, WorldTrack] = {}
        self._next_id: int = 1  # Start at 1 so 0 stays as "unassigned"

    # ── public API ───────────────────────────────────────────────────────

    def update(self, detections: List[dict]) -> List[dict]:
        """Assign stable track IDs to fused detections.

        Mutates each detection dict with a ``track_id`` and returns the
        same list for convenience. NOTE: even when ``detections`` is
        empty (NN dropped a frame, very common at 25 FPS) we MUST still
        run the coast loop below — otherwise dots vanish on every NN
        miss and the UI flickers. The early return that used to live
        here was the root cause of the visible flicker.
        """
        now = time.monotonic()
        track_ids = list(self._tracks.keys())

        # Build candidate (distance, track_id, det_idx) triples within
        # threshold. Same label always matches. Different labels match
        # only if the predicted position is very close (label override
        # — see _LABEL_OVERRIDE_RADIUS_M docstring).
        pairs: List[Tuple[float, int, int]] = []
        for d_idx, det in enumerate(detections):
            dlabel = det.get("label", "unknown")
            dx = float(det.get("x_m", 0.0))
            dz = float(det.get("z_m", 0.0))
            for tid in track_ids:
                trk = self._tracks[tid]
                dt = max(0.0, now - trk.last_seen)
                dt = min(dt, 1.5)
                px = trk.x_m + trk.vx * dt
                pz = trk.z_m + trk.vz * dt
                dist = math.sqrt((dx - px) ** 2 + (dz - pz) ** 2)
                if trk.label == dlabel:
                    if dist <= self.match_distance_m:
                        pairs.append((dist, tid, d_idx))
                else:
                    # Cross-label match only when extremely close.
                    if dist <= _LABEL_OVERRIDE_RADIUS_M:
                        pairs.append((dist, tid, d_idx))

        pairs.sort(key=lambda p: p[0])  # ascending distance

        used_tracks: Set[int] = set()
        used_dets: Set[int] = set()
        for dist, tid, d_idx in pairs:
            if tid in used_tracks or d_idx in used_dets:
                continue
            trk = self._tracks[tid]
            det = detections[d_idx]

            raw_x = float(det.get("x_m", trk.x_m))
            raw_z = float(det.get("z_m", trk.z_m))
            raw_y = float(det.get("y_m", trk.y_m))
            dt = max(1e-3, now - trk.last_seen)

            # Position EMA — heavy low-pass once the track is established,
            # snappier on the first few frames so it doesn't lag a real
            # appearing person. This is the single source of position
            # smoothing for the whole UI; clients should not re-smooth.
            pos_alpha = (
                _POS_ALPHA_NEW if trk.hits < _POS_NEW_HITS
                else _POS_ALPHA_ESTABLISHED
            )
            prev_x, prev_z = trk.x_m, trk.z_m
            new_x = (1 - pos_alpha) * trk.x_m + pos_alpha * raw_x
            new_z = (1 - pos_alpha) * trk.z_m + pos_alpha * raw_z
            new_y = (1 - pos_alpha) * trk.y_m + pos_alpha * raw_y

            # Velocity from smoothed delta — using raw_x here would let a
            # single noisy reading produce huge instantaneous velocity and
            # ruin the next coast prediction.
            inst_vx = (new_x - prev_x) / dt
            inst_vz = (new_z - prev_z) / dt
            alpha = self.velocity_smoothing
            trk.vx = (1 - alpha) * trk.vx + alpha * inst_vx
            trk.vz = (1 - alpha) * trk.vz + alpha * inst_vz

            trk.x_m = new_x
            trk.z_m = new_z
            trk.y_m = new_y
            # Accept the most recent label (handles cross-label matches
            # — see _LABEL_OVERRIDE_RADIUS_M). Low overhead, fixes the
            # YOLO label-flip churn that was creating duplicate tracks.
            trk.label = det.get("label", trk.label)
            trk.confidence = float(det.get("confidence", trk.confidence))
            trk.last_seen = now
            trk.age += 1
            trk.hits += 1
            trk.lost = 0
            cam_id = det.get("camera_id")
            if cam_id:
                trk.cameras_seen.add(cam_id)
                trk.last_camera_id = cam_id
            bbox = det.get("bbox")
            if bbox:
                trk.last_bbox = tuple(bbox)

            # Write the smoothed state back into the detection dict so
            # everything downstream (zone classifier, SSE clients, the
            # cab display, the spatial view) sees a single canonical
            # smooth position with derived smoothed distance.
            det["track_id"] = tid
            det["x_m"] = round(new_x, 3)
            det["y_m"] = round(new_y, 3)
            det["z_m"] = round(new_z, 3)
            det["distance_m"] = round(math.sqrt(new_x * new_x + new_z * new_z), 3)
            det["coasting"] = False
            used_tracks.add(tid)
            used_dets.add(d_idx)

        # Unmatched detections → new tracks
        for d_idx, det in enumerate(detections):
            if d_idx in used_dets:
                continue
            tid = self._next_id
            self._next_id += 1
            self._tracks[tid] = WorldTrack(
                track_id=tid,
                label=det.get("label", "unknown"),
                x_m=float(det.get("x_m", 0.0)),
                y_m=float(det.get("y_m", 0.0)),
                z_m=float(det.get("z_m", 0.0)),
                confidence=float(det.get("confidence", 0.0)),
                last_seen=now,
                cameras_seen=(
                    {det.get("camera_id")} if det.get("camera_id") else set()
                ),
            )
            det["track_id"] = tid

        # Age out any tracks that didn't match this frame
        self._age_unmatched(used_tracks, now)

        # ── Coasted emissions ────────────────────────────────────────
        # For every track that didn't match this frame but is still
        # inside the coast window, append a synthetic detection at its
        # predicted (constant-velocity) position. The flag ``coasting``
        # tells the renderer it's a prediction, not a fresh measurement
        # — so the UI can fade it slightly if it wants. Without this,
        # any single missed NN frame causes the dot to blink off and
        # back on, which reads as "glitchy" even though tracking is
        # internally stable.
        for tid, trk in self._tracks.items():
            if tid in used_tracks:
                continue
            if trk.lost == 0 or trk.lost > _COAST_FRAMES:
                continue
            dt = max(0.0, min(now - trk.last_seen, 1.5))
            px = trk.x_m + trk.vx * dt
            pz = trk.z_m + trk.vz * dt
            detections.append({
                "track_id": tid,
                "label": trk.label,
                "confidence": round(trk.confidence, 3),
                "x_m": round(px, 3),
                "y_m": round(trk.y_m, 3),
                "z_m": round(pz, 3),
                "distance_m": round(math.sqrt(px * px + pz * pz), 3),
                "camera_id": trk.last_camera_id,
                "bbox": list(trk.last_bbox) if trk.last_bbox else None,
                "coasting": True,
            })

        return detections

    @property
    def active_track_count(self) -> int:
        """Number of live tracks (including those currently lost)."""
        return len(self._tracks)

    def get_tracks(self) -> List[dict]:
        """Snapshot of current tracks for debug / telemetry."""
        return [
            {
                "track_id": t.track_id,
                "label": t.label,
                "x_m": round(t.x_m, 2),
                "z_m": round(t.z_m, 2),
                "vx": round(t.vx, 2),
                "vz": round(t.vz, 2),
                "hits": t.hits,
                "lost": t.lost,
                "cameras_seen": sorted(t.cameras_seen),
            }
            for t in self._tracks.values()
        ]

    # ── internals ────────────────────────────────────────────────────────

    def _age_unmatched(self, used_tracks: Set[int], now: float) -> None:
        """Increment lost counter on unmatched tracks; drop expired ones."""
        for tid in list(self._tracks.keys()):
            if tid in used_tracks:
                continue
            trk = self._tracks[tid]
            trk.lost += 1
            trk.age += 1
            if trk.lost > self.max_lost_frames:
                del self._tracks[tid]
