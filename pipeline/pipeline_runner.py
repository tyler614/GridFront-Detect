"""Main detection pipeline — ties all components together.

Orchestrates the full flow:
    OAK-D drivers  -->  Detector  -->  Tracker  -->  SpatialFusion  -->  ZoneClassifier  -->  Flask state

Works in two modes:
    * **Live** — connects to real OAK-D cameras via the oak_driver module.
    * **Mock** — generates realistic synthetic detections for UI development
      and testing without any camera hardware.
"""

from __future__ import annotations

import logging
import math
import random
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports — so the module can be imported even when sibling modules
# are not yet available (e.g. during isolated unit tests).
# ---------------------------------------------------------------------------


def _import_pipeline_deps():
    """Import pipeline-internal dependencies."""
    from .oak_driver import OakDriver
    from .oak_config import OakConfig
    from .detector import Detector, Detection
    from .tracker import Tracker
    from .spatial_fusion import SpatialFusion
    from .zone_classifier import ZoneClassifier

    return OakDriver, OakConfig, Detector, Detection, Tracker, SpatialFusion, ZoneClassifier


def _import_project_deps():
    """Import project-root dependencies."""
    from machine_profiles import get_machine_profile
    from detection_state import update_state, update_camera_health

    return get_machine_profile, update_state, update_camera_health


# ===================================================================
# PipelineRunner
# ===================================================================

class PipelineRunner:
    """End-to-end detection pipeline for a single machine."""

    def __init__(
        self,
        machine_type: str = "wheel_loader",
        mock: bool = True,
        zone_override: Optional[Dict[str, float]] = None,
        device_ids: Optional[Dict[str, str]] = None,
        active_model_id: Optional[str] = None,
        **kwargs,
    ):
        """Initialise the full pipeline.

        Args:
            machine_type: key into ``machine_profiles.MACHINE_PROFILES``
            mock: if True, use synthetic camera data (no hardware required)
            zone_override: optional zone config to override the profile defaults
            device_ids: optional mapping of ``cam-{mount_id}`` to device IP or
                MX ID.  When only one camera is available, pass a single entry
                and it will be assigned to the first mount.
        """
        (
            OakDriver, OakConfig, Detector, Detection,
            Tracker, SpatialFusion, ZoneClassifier,
        ) = _import_pipeline_deps()
        get_machine_profile, self._update_state, self._update_camera_health = (
            _import_project_deps()
        )

        # ── Load machine profile ──────────────────────────────────
        profile = get_machine_profile(machine_type)
        if profile is None:
            raise ValueError(
                f"Unknown machine type '{machine_type}'. "
                f"Check machine_profiles.MACHINE_PROFILES for valid keys."
            )
        self._profile = profile
        self._machine_type = machine_type
        self._mock = mock

        # ── Zone configuration ────────────────────────────────────
        zone_config = zone_override or profile["default_zones"]
        self._zone_config = zone_config

        # ── Camera setup ──────────────────────────────────────────
        mounts = profile["camera_mounts"]

        # Build camera transforms for SpatialFusion
        camera_transforms: Dict[str, dict] = {}
        for mount in mounts:
            cam_id = f"cam-{mount['id']}"
            camera_transforms[cam_id] = {
                "position": mount["position"],
                "rotation": mount["rotation"],
            }

        # Create one OAK-D driver per mount
        self._drivers: Dict[str, Any] = {}
        self._detectors: Dict[str, Any] = {}
        self._trackers: Dict[str, Any] = {}

        # Resolve device IDs — if only one camera is provided, assign it
        # to the first mount so a single OAK-D PoE can still drive the
        # pipeline without needing a full multi-camera rig.
        _device_ids = device_ids or {}
        if len(_device_ids) == 1 and len(mounts) > 1:
            only_id = list(_device_ids.values())[0]
            first_cam_id = f"cam-{mounts[0]['id']}"
            if first_cam_id not in _device_ids:
                _device_ids = {first_cam_id: only_id}

        # Resolve active model from config
        self._active_model_id = active_model_id or OakConfig().nn_model_id

        for mount in mounts:
            cam_id = f"cam-{mount['id']}"
            dev_id = _device_ids.get(cam_id)
            config = OakConfig(nn_model_id=self._active_model_id)
            if mock:
                # Full mock mode — create mock drivers for all mounts
                is_mock = True
            elif dev_id:
                # Live mode with assigned hardware
                is_mock = False
            else:
                # Live mode but no hardware — skip this mount entirely
                continue
            self._drivers[cam_id] = OakDriver(config, mock=is_mock, device_id=dev_id)
            self._detectors[cam_id] = Detector()
            self._trackers[cam_id] = Tracker()

        # ── Fusion and classification ─────────────────────────────
        self._fusion = SpatialFusion(camera_transforms)
        self._zone_classifier = ZoneClassifier(
            profile["dimensions"], zone_config
        )

        # ── Runtime state ─────────────────────────────────────────
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._fps: float = 0.0
        self._frame_count: int = 0
        self._fps_window: List[float] = []
        self._start_time: float = 0.0
        self._last_detection_count: int = 0
        self._mock_step: int = 0

        logger.info(
            "PipelineRunner initialised: machine=%s, cameras=%d, mock=%s",
            machine_type,
            len(self._drivers),
            mock,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the pipeline in a background thread."""
        if self._running:
            logger.warning("Pipeline already running")
            return

        self._running = True
        self._start_time = time.time()

        # Start all camera drivers
        for cam_id, driver in self._drivers.items():
            try:
                driver.start()
                logger.info("Started driver for %s", cam_id)
            except Exception:
                logger.exception("Failed to start driver for %s", cam_id)

        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="pipeline-runner"
        )
        self._thread.start()
        logger.info("Pipeline started")

    def stop(self) -> None:
        """Stop the pipeline and all camera drivers."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=10.0)
            self._thread = None

        for cam_id, driver in self._drivers.items():
            try:
                driver.stop()
            except Exception:
                logger.exception("Error stopping driver %s", cam_id)

        logger.info("Pipeline stopped")

    @property
    def stats(self) -> dict:
        """Return current pipeline statistics for health endpoints."""
        uptime = time.time() - self._start_time if self._start_time else 0
        camera_health = {}
        for cam_id, driver in self._drivers.items():
            camera_health[cam_id] = driver.health()
        return {
            "running": self._running,
            "mock": self._mock,
            "machine_type": self._machine_type,
            "fps": round(self._fps, 1),
            "frame_count": self._frame_count,
            "uptime_s": round(uptime, 1),
            "cameras": camera_health,
            "last_detection_count": self._last_detection_count,
        }

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        """Main loop: grab frames, detect, track, fuse, classify, push state."""
        target_interval = 0.1  # 10 Hz

        while self._running:
            t0 = time.time()

            if self._mock:
                classified = self._mock_cycle()
            else:
                classified = self._live_cycle()

            # Push to shared Flask state
            self._update_state(classified, fps=self._fps)
            self._last_detection_count = len(classified)

            # Update camera health
            for cam_id, driver in self._drivers.items():
                h = driver.health()
                self._update_camera_health(
                    cam_id, h.get("fps", 0), h.get("latency_ms", 0)
                )

            # FPS bookkeeping
            self._frame_count += 1
            self._update_fps(t0)

            # Sleep to maintain target rate
            elapsed = time.time() - t0
            sleep_time = max(0.0, target_interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

    # ------------------------------------------------------------------
    # Live cycle (real cameras)
    # ------------------------------------------------------------------

    def _live_cycle(self) -> List[dict]:
        """Run one cycle using real camera data.

        Handles a mixed fleet: some drivers connect to real hardware, others
        run in mock mode (when fewer physical cameras are available than the
        machine profile defines).  Mock drivers produce pre-labelled
        Detection objects that should NOT be re-processed through the
        Detector (which expects raw NN integer label IDs).
        """
        camera_dets: Dict[str, list] = {}

        for cam_id, driver in self._drivers.items():
            frame = driver.get_frame()
            if frame is None:
                continue  # Camera disconnected or not yet ready

            from .detector import Detection as Det
            dets: list = []

            for raw in frame["detections"]:
                d = raw.to_dict() if hasattr(raw, "to_dict") else raw
                # oak_driver.Detection stores spatial as {x, y, z} in metres
                spatial = d.get("spatial", {})
                dets.append(Det(
                    track_id=0,
                    label=d.get("label", "person"),
                    confidence=d.get("confidence", 0.8),
                    bbox=d.get("bbox", (0, 0, 1, 1)),
                    x_m=spatial.get("x", d.get("x_m", 0)),
                    y_m=spatial.get("y", d.get("y_m", 0)),
                    z_m=spatial.get("z", d.get("z_m", 0)),
                    distance_m=d.get("distance_m", 0),
                ))

            tracked = self._trackers[cam_id].update(dets)
            camera_dets[cam_id] = tracked

        # Fuse across cameras into machine-world coordinates
        fused = self._fusion.fuse(camera_dets)

        # Classify zones
        classified = self._zone_classifier.classify_all(fused)
        return classified

    # ------------------------------------------------------------------
    # Mock cycle (synthetic data)
    # ------------------------------------------------------------------

    def _mock_cycle(self) -> List[dict]:
        """Generate realistic synthetic detections without camera hardware.

        Produces a mix of persons and vehicles at varying positions, with
        movement patterns that exercise the full zone range.
        """
        self._mock_step += 1
        step = self._mock_step
        t = step * 0.1  # Simulated time in seconds

        detections: List[dict] = []

        # ── Person 1: orbits at medium distance ───────────────────
        angle1 = t * 0.3
        dist1 = 4.0 + 2.5 * math.sin(t * 0.15)
        detections.append({
            "track_id": 1,
            "label": "person",
            "confidence": 0.92,
            "x_m": round(dist1 * math.sin(angle1), 2),
            "y_m": 0,
            "z_m": round(dist1 * math.cos(angle1), 2),
            "distance_m": round(dist1, 2),
            "camera_id": "cam-front",
        })

        # ── Person 2: approaches and retreats from rear ──────────
        dist2 = 3.0 + 4.0 * abs(math.sin(t * 0.08))
        angle2 = math.pi + 0.3 * math.sin(t * 0.2)
        detections.append({
            "track_id": 2,
            "label": "person",
            "confidence": 0.87,
            "x_m": round(dist2 * math.sin(angle2), 2),
            "y_m": 0,
            "z_m": round(dist2 * math.cos(angle2), 2),
            "distance_m": round(dist2, 2),
            "camera_id": "cam-rear",
        })

        # ── Vehicle: slow pass on the left side ──────────────────
        if step % 200 < 120:
            veh_z = -8.0 + (step % 200) * 0.15
            detections.append({
                "track_id": 3,
                "label": "vehicle",
                "confidence": 0.83,
                "x_m": round(-5.0 + 0.5 * math.sin(t * 0.1), 2),
                "y_m": 0,
                "z_m": round(veh_z, 2),
                "distance_m": round(math.sqrt(25 + veh_z * veh_z), 2),
                "camera_id": "cam-left",
            })

        # ── Occasional third person on the right ─────────────────
        if step % 150 < 80:
            dist3 = 2.0 + 1.0 * math.sin(t * 0.25)
            detections.append({
                "track_id": 4,
                "label": "person",
                "confidence": 0.76,
                "x_m": round(3.0 + 0.5 * math.sin(t * 0.3), 2),
                "y_m": 0,
                "z_m": round(1.0 * math.cos(t * 0.4), 2),
                "distance_m": round(dist3, 2),
                "camera_id": "cam-right",
            })

        # Classify zones directly (mock data is already in world coords)
        classified = self._zone_classifier.classify_all(detections)
        return classified

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _update_fps(self, t0: float) -> None:
        """Maintain a rolling FPS estimate over the last 30 cycles."""
        now = time.time()
        self._fps_window.append(now)
        if len(self._fps_window) > 30:
            self._fps_window = self._fps_window[-30:]
        if len(self._fps_window) >= 2:
            span = self._fps_window[-1] - self._fps_window[0]
            if span > 0:
                self._fps = (len(self._fps_window) - 1) / span
