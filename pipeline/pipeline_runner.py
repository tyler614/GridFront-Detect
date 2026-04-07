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
    from .tracker import Tracker, WorldTracker
    from .spatial_fusion import SpatialFusion
    from .zone_classifier import ZoneClassifier

    return (
        OakDriver, OakConfig, Detector, Detection,
        Tracker, WorldTracker, SpatialFusion, ZoneClassifier,
    )


def _import_project_deps():
    """Import project-root dependencies."""
    from machine_profiles import get_machine_profile
    from detection_state import (
        update_state, update_camera_health, set_coverage_sectors,
        set_camera_calibration, clear_camera_calibration,
    )

    return (
        get_machine_profile,
        update_state,
        update_camera_health,
        set_coverage_sectors,
        set_camera_calibration,
        clear_camera_calibration,
    )


def _compute_coverage_sectors(installed_cameras):
    """Convert installed_cameras into a list of coverage sector dicts.

    Angle convention matches machine_profiles.py rotation: yaw_deg is the
    camera's bearing around +Y with 0°=front(+Z), 90°=right(+X), 180°=rear,
    -90°/270°=left. start/end_deg span the HFOV arc centred on yaw_deg.

    Each sector also carries a ``calibrated`` flag — True when a reference
    IMU quaternion was snapshotted via the calibrate endpoint. The UI uses
    this to colour the wedge grey (uncalibrated) vs green (ok).
    """
    sectors = []
    for cam in installed_cameras:
        yaw = float(cam.get("yaw_deg", 0))
        hfov = float(cam.get("hfov_deg", 127))
        half = hfov / 2.0
        sectors.append({
            "id": cam.get("id"),
            "label": cam.get("label", cam.get("id", "")),
            "position_m": list(cam.get("position_m", [0, 0, 0])),
            "yaw_deg": yaw,
            "pitch_deg": float(cam.get("pitch_deg", 0)),
            "hfov_deg": hfov,
            "range_m": float(cam.get("max_range_m", 12.0)),
            "start_deg": yaw - half,
            "end_deg": yaw + half,
            "calibrated": bool(cam.get("imu_ref_quat")),
            "calibrated_at": cam.get("calibrated_at"),
            "bump_threshold_deg": float(cam.get("bump_threshold_deg", 10.0)),
        })
    return sectors


def _quat_angle_deg(a: tuple, b: tuple) -> float:
    """Angular distance in degrees between two unit quaternions (qx,qy,qz,qw)."""
    dot = abs(a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3])
    if dot >= 1.0:
        return 0.0
    if dot <= -1.0:
        return 180.0
    return math.degrees(2.0 * math.acos(dot))


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
        installed_cameras: Optional[List[dict]] = None,
        **kwargs,
    ):
        """Initialise the full pipeline.

        Args:
            machine_type: key into ``machine_profiles.MACHINE_PROFILES``
            mock: if True, use synthetic camera data (no hardware required)
            zone_override: optional zone config to override the profile defaults
            installed_cameras: list of actually-installed cameras — the source
                of truth for mount geometry. Each entry is a dict with:
                ``id``, ``label``, ``device_id``, ``position_m: [x,y,z]``,
                ``yaw_deg``, ``pitch_deg``, ``roll_deg``, ``hfov_deg``,
                ``max_range_m``. When omitted, the profile's camera_mounts
                list is used as a fallback (legacy behaviour).
            device_ids: legacy mapping of ``cam-{mount_id}`` → device IP/MX.
                Only used when ``installed_cameras`` is not provided.
        """
        (
            OakDriver, OakConfig, Detector, Detection,
            Tracker, WorldTracker, SpatialFusion, ZoneClassifier,
        ) = _import_pipeline_deps()
        (
            get_machine_profile,
            self._update_state,
            self._update_camera_health,
            self._set_coverage_sectors,
            self._set_camera_calibration,
            self._clear_camera_calibration,
        ) = _import_project_deps()

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
        # Resolve the installed cameras: explicit list wins, otherwise fall
        # back to the profile's suggested mounts (legacy path).
        if installed_cameras:
            self._installed_cameras = [dict(c) for c in installed_cameras]
        else:
            self._installed_cameras = self._cameras_from_profile(
                profile, device_ids or {}, mock=mock
            )

        # Build camera transforms for SpatialFusion from installed cameras
        camera_transforms: Dict[str, dict] = {}
        for cam in self._installed_cameras:
            camera_transforms[cam["id"]] = {
                "position": cam["position_m"],
                "rotation": [
                    cam.get("pitch_deg", 0),
                    cam.get("yaw_deg", 0),
                    cam.get("roll_deg", 0),
                ],
            }

        # Create one OAK-D driver per installed camera
        self._drivers: Dict[str, Any] = {}
        self._detectors: Dict[str, Any] = {}

        # Resolve active model from config
        self._active_model_id = active_model_id or OakConfig().nn_model_id

        for cam in self._installed_cameras:
            cam_id = cam["id"]
            dev_id = cam.get("device_id")
            config = OakConfig(nn_model_id=self._active_model_id)
            if mock:
                is_mock = True
            elif dev_id:
                is_mock = False
            else:
                # Live mode but no hardware for this slot — skip it
                continue
            self._drivers[cam_id] = OakDriver(config, mock=is_mock, device_id=dev_id)
            self._detectors[cam_id] = Detector()

        # ── Fusion and classification ─────────────────────────────
        self._fusion = SpatialFusion(camera_transforms)
        # Unified world-space tracker — runs AFTER fusion so the same
        # physical person keeps one track_id as they cross cameras.
        self._world_tracker = WorldTracker(
            match_distance_m=1.8,
            max_lost_frames=30,
        )
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
        self._restarting: bool = False
        self._restart_lock = threading.Lock()
        # Publish coverage sectors so the UI can render accurate FOV wedges
        self._coverage_sectors = _compute_coverage_sectors(self._installed_cameras)
        try:
            self._set_coverage_sectors(self._coverage_sectors)
        except Exception:
            logger.exception("Failed to publish initial coverage sectors")

        # ── Bump watchdog ─────────────────────────────────────────
        # For each camera we track calibration state and publish it to
        # detection_state every cycle. Anything not nominal forces the
        # cab display into a hard-fail alarm — we never silently serve
        # detections from a camera whose mount may have moved.
        self._calib_lock = threading.Lock()
        # Hysteresis: a single noisy frame should not page the operator,
        # but a sustained delta over this window does.
        # Machines shake. A 650hp diesel mount oscillates the IMU by
        # several degrees at 10-40 Hz while the mean orientation is
        # rock stable. Combined with the vibration-averaged quat read
        # below, a 2s sustain swallows any plausible transient without
        # delaying a real bump alarm noticeably.
        self._bump_sustain_s = 2.0
        # Window used to low-pass the live quat against the ref quat.
        # Must be long enough to average out engine-vibration jitter
        # but short enough that a real bump is visible within a bump
        # sustain window. 1.5s @ ~15 samples/s = ~22 samples — plenty.
        self._bump_average_window_s = 1.5
        self._camera_bump_since: Dict[str, float] = {}

        # ── Bump watchdog kill switch ────────────────────────────────
        # The IMU-based bump detector is intentionally disabled. On a
        # desk it false-fires constantly because the IMU drifts and the
        # reference quat is from an old calibration. We'll bring this
        # back when the camera is permanently mounted on a real machine
        # and we can re-tune thresholds against actual operating
        # vibration. Until then: silent. The cab display safety_state
        # stays "nominal" because we never write any calibration entries.
        self._bump_watchdog_enabled = False

        if self._bump_watchdog_enabled:
            # Seed calibration status from installed_cameras
            for cam in self._installed_cameras:
                cam_id = cam["id"]
                if cam.get("imu_ref_quat"):
                    entry = {
                        "state": "nominal",
                        "delta_deg": 0.0,
                        "threshold_deg": float(cam.get("bump_threshold_deg", 10.0)),
                        "calibrated_at": cam.get("calibrated_at"),
                        "imu_accuracy_rad": None,
                    }
                else:
                    entry = {
                        "state": "uncalibrated",
                        "delta_deg": 0.0,
                        "threshold_deg": float(cam.get("bump_threshold_deg", 10.0)),
                        "calibrated_at": None,
                        "imu_accuracy_rad": None,
                    }
                try:
                    self._set_camera_calibration(cam_id, entry)
                except Exception:
                    logger.exception("Failed to seed calibration for %s", cam_id)
        else:
            # Wipe any stale calibration entries from a previous run so
            # the SSE clients see a clean nominal state immediately.
            try:
                self._clear_camera_calibration()
            except Exception:
                logger.exception("Failed to clear stale calibration state")

        logger.info(
            "PipelineRunner initialised: machine=%s, cameras=%d, mock=%s",
            machine_type,
            len(self._drivers),
            mock,
        )

    # ------------------------------------------------------------------
    # Legacy fallback — build installed_cameras from a machine profile
    # ------------------------------------------------------------------

    @staticmethod
    def _cameras_from_profile(
        profile: dict,
        device_ids: Dict[str, str],
        mock: bool,
    ) -> List[dict]:
        """Convert profile camera_mounts into installed_cameras entries.

        Used when no explicit ``installed_cameras`` list was provided. A
        single device in ``device_ids`` is auto-assigned to the first mount
        so single-camera setups keep working.
        """
        mounts = profile.get("camera_mounts", [])
        spec = profile.get("camera_spec", {})
        hfov = spec.get("hfov_deg", 127)
        max_range = profile.get("default_zones", {}).get("max_range_m", 12.0)

        # Single-camera fallback: bind to first mount
        _device_ids = dict(device_ids)
        if len(_device_ids) == 1 and len(mounts) > 1:
            only_id = next(iter(_device_ids.values()))
            first_cam_id = f"cam-{mounts[0]['id']}"
            if first_cam_id not in _device_ids:
                _device_ids = {first_cam_id: only_id}

        cameras: List[dict] = []
        for mount in mounts:
            cam_id = f"cam-{mount['id']}"
            dev_id = _device_ids.get(cam_id)
            if not mock and not dev_id:
                continue  # no hardware for this slot in live mode
            rot = mount.get("rotation", [0, 0, 0])
            cameras.append({
                "id": cam_id,
                "label": mount.get("label", mount["id"]),
                "device_id": dev_id,
                "position_m": list(mount.get("position", [0, 0, 0])),
                "pitch_deg": rot[0] if len(rot) > 0 else 0,
                "yaw_deg":   rot[1] if len(rot) > 1 else 0,
                "roll_deg":  rot[2] if len(rot) > 2 else 0,
                "hfov_deg": hfov,
                "max_range_m": max_range,
            })
        return cameras

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
            "active_model": self._active_model_id,
            "restarting": self._restarting,
            "coverage_sectors": list(self._coverage_sectors),
        }

    @property
    def coverage_sectors(self) -> list:
        """Return the list of coverage sectors for the installed cameras."""
        return list(self._coverage_sectors)

    # ------------------------------------------------------------------
    # Model hot-swap
    # ------------------------------------------------------------------

    def restart_with_model(self, model_id: str) -> None:
        """Stop all drivers, rebuild them with a new NN model, and restart.

        Safe to call from a background thread. Uses a lock so concurrent
        switches are serialised. Raises ValueError if model_id is unknown.
        """
        from pipeline.model_registry import get_model
        if get_model(model_id) is None:
            raise ValueError(f"Unknown model: {model_id}")

        with self._restart_lock:
            logger.info("Restarting pipeline with model=%s", model_id)
            # Set immediately so the status API reports the new model name
            # for the full duration of the restart, not just the tail end.
            self._active_model_id = model_id
            self._restarting = True
            try:
                OakDriver, OakConfig, *_ = _import_pipeline_deps()

                # Stop the run loop so it doesn't touch drivers mid-swap
                was_running = self._running
                self._running = False
                if self._thread is not None:
                    self._thread.join(timeout=10.0)
                    self._thread = None

                # Stop and release existing drivers
                for cam_id, driver in self._drivers.items():
                    try:
                        driver.stop()
                    except Exception:
                        logger.exception("Error stopping driver %s during restart", cam_id)

                # Rebuild drivers with the new model
                new_drivers: Dict[str, Any] = {}
                for cam in self._installed_cameras:
                    cam_id = cam["id"]
                    dev_id = cam.get("device_id")
                    config = OakConfig(nn_model_id=model_id)
                    if self._mock:
                        is_mock = True
                    elif dev_id:
                        is_mock = False
                    else:
                        continue
                    new_drivers[cam_id] = OakDriver(config, mock=is_mock, device_id=dev_id)
                self._drivers = new_drivers

                # Start fresh drivers and the run loop
                if was_running:
                    self._running = True
                    self._start_time = time.time()
                    for cam_id, driver in self._drivers.items():
                        try:
                            driver.start()
                            logger.info("Restarted driver for %s", cam_id)
                        except Exception:
                            logger.exception("Failed to start driver %s after restart", cam_id)
                    self._thread = threading.Thread(
                        target=self._run_loop, daemon=True, name="pipeline-runner"
                    )
                    self._thread.start()
                logger.info("Pipeline restart complete (model=%s)", model_id)
            finally:
                self._restarting = False

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        """Main loop: grab frames, detect, track, fuse, classify, push state."""
        target_interval = 1.0 / 30  # 30 Hz — match camera FPS

        while self._running:
            t0 = time.time()

            if self._mock:
                classified = self._mock_cycle()
            else:
                classified = self._live_cycle()

            # Bump watchdog — gated by _bump_watchdog_enabled. See the
            # kill-switch comment in __init__ for why this is currently
            # off.
            if self._bump_watchdog_enabled:
                try:
                    self._check_camera_bumps(classified)
                except Exception:
                    logger.exception("Bump watchdog error")

            # Push to shared Flask state
            self._update_state(classified, fps=self._fps)
            self._last_detection_count = len(classified)

            # Update camera health
            for cam_id, driver in self._drivers.items():
                h = driver.health()
                self._update_camera_health(
                    cam_id,
                    h.get("fps", 0),
                    h.get("latency_ms", 0),
                    nn_fps=h.get("nn_fps"),
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

        Flow:
            per-camera raw detections
              → SpatialFusion (into machine-world coords, merge duplicates)
              → WorldTracker (assign unified track IDs in world space)
              → ZoneClassifier
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
                    track_id=0,  # assigned later by WorldTracker
                    label=d.get("label", "person"),
                    confidence=d.get("confidence", 0.8),
                    bbox=d.get("bbox", (0, 0, 1, 1)),
                    x_m=spatial.get("x", d.get("x_m", 0)),
                    y_m=spatial.get("y", d.get("y_m", 0)),
                    z_m=spatial.get("z", d.get("z_m", 0)),
                    distance_m=d.get("distance_m", 0),
                ))

            camera_dets[cam_id] = dets

        # Fuse across cameras into machine-world coordinates
        fused = self._fusion.fuse(camera_dets)

        # Unified world-space tracking — stable IDs across all cameras
        tracked = self._world_tracker.update(fused)

        # Classify zones
        classified = self._zone_classifier.classify_all(tracked)
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

        # Mock detections are emitted WITHOUT track_ids — the WorldTracker
        # assigns them post-fusion, exercising the same path as live data.

        # ── Person 1: orbits at medium distance ───────────────────
        angle1 = t * 0.3
        dist1 = 4.0 + 2.5 * math.sin(t * 0.15)
        detections.append({
            "track_id": 0,
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
            "track_id": 0,
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
                "track_id": 0,
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
                "track_id": 0,
                "label": "person",
                "confidence": 0.76,
                "x_m": round(3.0 + 0.5 * math.sin(t * 0.3), 2),
                "y_m": 0,
                "z_m": round(1.0 * math.cos(t * 0.4), 2),
                "distance_m": round(dist3, 2),
                "camera_id": "cam-right",
            })

        # Run through the WorldTracker so mock IDs exercise the same
        # path as live data (and give stable IDs across frames).
        tracked = self._world_tracker.update(detections)

        # Classify zones directly (mock data is already in world coords)
        classified = self._zone_classifier.classify_all(tracked)
        return classified

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Bump watchdog
    # ------------------------------------------------------------------

    def _check_camera_bumps(self, classified: List[dict]) -> None:
        """Per-frame: compare live IMU quat to each camera's ref quat.

        Publishes status to detection_state and tags detections from any
        camera in a bumped/imu_lost state with ``unsafe=True`` so the
        zone classifier downstream can fail loud. Does nothing for mock
        cameras since they have no real IMU.
        """
        now = time.time()
        # Build a quick lookup of installed_cameras by id
        cams_by_id = {c["id"]: c for c in self._installed_cameras}
        bumped_ids: set = set()

        for cam_id, cam in cams_by_id.items():
            driver = self._drivers.get(cam_id)
            threshold = float(cam.get("bump_threshold_deg", 10.0))
            ref_quat = cam.get("imu_ref_quat")

            # No driver — camera is configured but not streaming
            if driver is None:
                self._set_camera_calibration(cam_id, {
                    "state": "uncalibrated" if not ref_quat else "imu_lost",
                    "delta_deg": 0.0,
                    "threshold_deg": threshold,
                    "calibrated_at": cam.get("calibrated_at"),
                    "imu_accuracy_rad": None,
                })
                if ref_quat:
                    bumped_ids.add(cam_id)
                continue

            # Mock drivers get a free pass — they report "nominal" when
            # calibrated or "uncalibrated" otherwise. No bump detection.
            if getattr(driver, "mock", False):
                state = "nominal" if ref_quat else "uncalibrated"
                self._set_camera_calibration(cam_id, {
                    "state": state,
                    "delta_deg": 0.0,
                    "threshold_deg": threshold,
                    "calibrated_at": cam.get("calibrated_at"),
                    "imu_accuracy_rad": None,
                })
                continue

            # Prefer a vibration-averaged quat — otherwise every diesel
            # engine shake looks like a bump. Fall back to instantaneous
            # only if the driver doesn't expose the averaged API.
            if hasattr(driver, "get_imu_average"):
                imu = driver.get_imu_average(self._bump_average_window_s)
                if imu is None and hasattr(driver, "get_imu"):
                    imu = driver.get_imu()
            elif hasattr(driver, "get_imu"):
                imu = driver.get_imu()
            else:
                imu = None

            # IMU silent → fail loud. We will NEVER trust stale orientation.
            if imu is None:
                self._set_camera_calibration(cam_id, {
                    "state": "uncalibrated" if not ref_quat else "imu_lost",
                    "delta_deg": 0.0,
                    "threshold_deg": threshold,
                    "calibrated_at": cam.get("calibrated_at"),
                    "imu_accuracy_rad": None,
                })
                if ref_quat:
                    bumped_ids.add(cam_id)
                continue

            imu_ts = imu.get("timestamp", 0)
            imu_age = now - imu_ts if imu_ts else 999
            accuracy = imu.get("accuracy_rad")

            # Stale IMU (>1s) is indistinguishable from a dead sensor.
            if imu_age > 1.0:
                state = "uncalibrated" if not ref_quat else "imu_lost"
                self._set_camera_calibration(cam_id, {
                    "state": state,
                    "delta_deg": 0.0,
                    "threshold_deg": threshold,
                    "calibrated_at": cam.get("calibrated_at"),
                    "imu_accuracy_rad": accuracy,
                })
                if ref_quat:
                    bumped_ids.add(cam_id)
                continue

            # No reference yet → uncalibrated (but IMU is alive)
            if not ref_quat:
                self._set_camera_calibration(cam_id, {
                    "state": "uncalibrated",
                    "delta_deg": 0.0,
                    "threshold_deg": threshold,
                    "calibrated_at": None,
                    "imu_accuracy_rad": accuracy,
                })
                continue

            # Compare current to reference
            live = (imu["qx"], imu["qy"], imu["qz"], imu["qw"])
            ref = tuple(ref_quat)
            delta_deg = _quat_angle_deg(live, ref)

            # State with hysteresis: a single spike under the threshold
            # clears any pending bump timer; once delta has been over
            # the threshold for at least _bump_sustain_s seconds, we
            # latch 'bumped'. Yellow 'warn' band is between 40% and the
            # full threshold — informational only, zone still armed.
            warn_floor = threshold * 0.4
            if delta_deg >= threshold:
                first = self._camera_bump_since.get(cam_id)
                if first is None:
                    self._camera_bump_since[cam_id] = now
                    sustained = 0.0
                else:
                    sustained = now - first
                if sustained >= self._bump_sustain_s:
                    state = "bumped"
                    bumped_ids.add(cam_id)
                else:
                    state = "warn"
            else:
                self._camera_bump_since.pop(cam_id, None)
                if delta_deg >= warn_floor:
                    state = "warn"
                else:
                    state = "nominal"

            self._set_camera_calibration(cam_id, {
                "state": state,
                "delta_deg": round(delta_deg, 3),
                "threshold_deg": threshold,
                "calibrated_at": cam.get("calibrated_at"),
                "imu_accuracy_rad": accuracy,
            })

        # Tag detections from bumped cameras as unsafe so the cab
        # display and classifier can react.
        if bumped_ids and classified:
            for det in classified:
                if det.get("camera_id") in bumped_ids:
                    det["unsafe"] = True
                    det["unsafe_reason"] = "camera_bumped"

    # ------------------------------------------------------------------
    # Calibration API (called from app.py POST /api/cameras/<id>/calibrate)
    # ------------------------------------------------------------------

    def recalibrate_camera(self, camera_id: str) -> dict:
        """Snapshot the current IMU quaternion as this camera's reference.

        Returns a result dict with ``ok`` and either ``calibrated_at`` +
        ``imu_ref_quat`` (success) or ``error`` + ``reason`` (rejected).

        Enforces ``driver.is_stable()`` — refuses to commit a reference
        while the camera is wobbling or the IMU isn't yet confident.
        This is the entire point of the button: if a reference is taken
        from a bad instant, every subsequent bump check compares against
        garbage and the safety system silently lies.
        """
        driver = self._drivers.get(camera_id)
        if driver is None:
            return {"ok": False, "error": "unknown_camera", "reason": f"No driver for {camera_id}"}
        if getattr(driver, "mock", False):
            return {"ok": False, "error": "mock_camera", "reason": "Cannot calibrate a mock camera"}
        if not hasattr(driver, "is_stable"):
            return {"ok": False, "error": "driver_no_stability", "reason": "Driver missing is_stable()"}

        stability = driver.is_stable()
        if not stability.get("stable"):
            return {
                "ok": False,
                "error": "not_stable",
                "reason": stability.get("reason", "Hold still"),
                "stability": stability,
            }

        # Snapshot the AVERAGED orientation, not the instantaneous one —
        # otherwise calibrating on a running machine locks the reference
        # to whatever point of the vibration cycle we happened to catch.
        imu = None
        if hasattr(driver, "get_imu_average"):
            imu = driver.get_imu_average(2.0)
        if imu is None:
            imu = driver.get_imu()
        if imu is None:
            return {"ok": False, "error": "no_imu", "reason": "IMU has no reading"}

        ref_quat = [imu["qx"], imu["qy"], imu["qz"], imu["qw"]]
        from datetime import datetime, timezone
        calibrated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

        # Update runtime installed_cameras entry so the watchdog picks it
        # up on its next cycle. The caller (app.py) is responsible for
        # persisting to config.json.
        with self._calib_lock:
            for cam in self._installed_cameras:
                if cam["id"] == camera_id:
                    cam["imu_ref_quat"] = ref_quat
                    cam["calibrated_at"] = calibrated_at
                    break
            # Refresh coverage sectors so the UI flips grey→green
            self._coverage_sectors = _compute_coverage_sectors(self._installed_cameras)
            try:
                self._set_coverage_sectors(self._coverage_sectors)
            except Exception:
                logger.exception("Failed to republish coverage after calibrate")
            self._camera_bump_since.pop(camera_id, None)

        return {
            "ok": True,
            "camera_id": camera_id,
            "imu_ref_quat": ref_quat,
            "calibrated_at": calibrated_at,
            "stability": stability,
        }

    def get_calibration_status(self, camera_id: str) -> dict:
        """Return live status for the Settings UI countdown / health dot.

        Shape::

            {
              "camera_id": "cam-0",
              "has_driver": bool,
              "imu_present": bool,
              "stability": {...}  # from driver.is_stable()
              "ref_quat": [qx,qy,qz,qw] | None,
              "calibrated_at": iso | None,
              "current_delta_deg": float | None,
              "state": str
            }
        """
        cam = next(
            (c for c in self._installed_cameras if c["id"] == camera_id),
            None,
        )
        if cam is None:
            return {"camera_id": camera_id, "has_driver": False, "error": "unknown_camera"}
        driver = self._drivers.get(camera_id)
        has_driver = driver is not None
        is_mock = bool(getattr(driver, "mock", False)) if driver else False
        imu = driver.get_imu() if (driver and hasattr(driver, "get_imu")) else None
        stability = (
            driver.is_stable()
            if (driver and hasattr(driver, "is_stable") and not is_mock)
            else {"stable": False, "reason": "Mock or no driver", "samples": 0,
                  "max_delta_deg": 0.0, "window_s": 2.0, "accuracy_rad": None}
        )
        ref = cam.get("imu_ref_quat")
        current_delta = None
        if ref and imu:
            current_delta = round(
                _quat_angle_deg(
                    (imu["qx"], imu["qy"], imu["qz"], imu["qw"]),
                    tuple(ref),
                ),
                3,
            )
        # Pull live state from detection_state so UI stays consistent
        try:
            from detection_state import get_camera_calibration
            cal = get_camera_calibration(camera_id) or {}
            state = cal.get("state", "uncalibrated")
        except Exception:
            state = "uncalibrated"

        return {
            "camera_id": camera_id,
            "has_driver": has_driver,
            "mock": is_mock,
            "imu_present": imu is not None,
            "stability": stability,
            "ref_quat": ref,
            "calibrated_at": cam.get("calibrated_at"),
            "bump_threshold_deg": float(cam.get("bump_threshold_deg", 10.0)),
            "current_delta_deg": current_delta,
            "state": state,
        }

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
