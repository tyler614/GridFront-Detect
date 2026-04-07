"""OAK-D Pro W PoE camera driver — discovery, connection, frame acquisition.

Works in two modes:
  * **Live mode** — connects to a real OAK-D camera via depthai SDK v3.5.0
  * **Mock mode** — generates synthetic frames so the rest of the pipeline
    can be developed and tested without hardware.

Usage::

    from pipeline.oak_driver import OakDriver
    from pipeline.oak_config import OakConfig

    driver = OakDriver(OakConfig(), mock=True)
    driver.start()
    frame = driver.get_frame()  # dict with rgb, depth, detections
    driver.stop()
"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Any

import numpy as np

from pipeline.oak_config import OakConfig
from pipeline.model_registry import get_model, get_default_model, COCO_LABELS

# ── Safety-relevant label filter ────────────────────────────────────────
# YOLOv6n-COCO is a generic 80-class detector — perfect for spotting
# people on a construction site, deeply unhelpful when it occasionally
# decides a person is a "tvmonitor" or "teddy bear". Filter to the
# classes we actually care about for industrial safety, and coalesce
# the four vehicle subclasses into a single "vehicle" label so the
# WorldTracker doesn't churn track IDs when YOLO flip-flops between
# car/truck/bus on the same physical object. GridFront-v1 (the custom
# model) will replace this with site-specific classes — until then this
# is the right denoising for the placeholder model.
_SAFETY_LABELS: dict[str, str] = {
    "person": "person",
    "bicycle": "vehicle",
    "car": "vehicle",
    "motorbike": "vehicle",
    "bus": "vehicle",
    "truck": "vehicle",
}


def _quat_mean(quats):
    """Mean of a list of (qx,qy,qz,qw) unit quaternions.

    Uses sign-normalized sum-and-renormalize — cheap and correct for
    the small angular spreads we see from vibration (a few degrees).
    Returns ``None`` for an empty input.
    """
    if not quats:
        return None
    q0 = quats[0]
    sx = sy = sz = sw = 0.0
    for q in quats:
        # Flip any quat in the opposite hemisphere from q0 so we don't
        # average q and -q into zero.
        dot = q0[0] * q[0] + q0[1] * q[1] + q0[2] * q[2] + q0[3] * q[3]
        if dot < 0:
            sx -= q[0]; sy -= q[1]; sz -= q[2]; sw -= q[3]
        else:
            sx += q[0]; sy += q[1]; sz += q[2]; sw += q[3]
    n = math.sqrt(sx * sx + sy * sy + sz * sz + sw * sw)
    if n == 0:
        return q0
    return (sx / n, sy / n, sz / n, sw / n)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Conditional depthai import — missing SDK just forces mock mode
# ---------------------------------------------------------------------------
try:
    import depthai as dai
    import blobconverter

    _DAI_AVAILABLE = True
except ImportError:
    dai = None  # type: ignore[assignment]
    blobconverter = None  # type: ignore[assignment]
    _DAI_AVAILABLE = False


# ---------------------------------------------------------------------------
# Depth preset mapping (v3.5.0 API)
# ---------------------------------------------------------------------------
_DEPTH_PRESET_MAP: dict[str, Any] = {}

if _DAI_AVAILABLE:
    _DEPTH_PRESET_MAP = {
        "HIGH_ACCURACY": dai.node.StereoDepth.PresetMode.ACCURACY,
        "HIGH_DENSITY": dai.node.StereoDepth.PresetMode.DENSITY,
        # FAST_DENSITY and FAST_ACCURACY trade a bit of depth quality
        # for ~20% lower VPU cost. Since SpatialDetectionNetwork only
        # needs depth at the bbox centroids (crop-and-average), we
        # don't need full per-pixel density — freeing VPU cycles for
        # the NN gets us closer to the 30 FPS camera ceiling.
        "FAST_DENSITY": dai.node.StereoDepth.PresetMode.FAST_DENSITY,
        "FAST_ACCURACY": dai.node.StereoDepth.PresetMode.FAST_ACCURACY,
        "ROBOTICS": dai.node.StereoDepth.PresetMode.ROBOTICS,
        "DEFAULT": dai.node.StereoDepth.PresetMode.DEFAULT,
    }

# ---------------------------------------------------------------------------
# RGB resolution to (width, height) for requestOutput()
# ---------------------------------------------------------------------------
_RGB_SIZE_MAP: dict[str, tuple[int, int]] = {
    "800p": (1280, 800),
    "720p": (1280, 720),
    "480p": (640, 480),
    "400p": (640, 400),
}


# ---------------------------------------------------------------------------
# Detection dataclass (lightweight, dict-friendly)
# ---------------------------------------------------------------------------
class Detection:
    """Single NN detection result with optional 3D spatial position."""

    __slots__ = (
        "label", "confidence", "x_min", "y_min", "x_max", "y_max",
        "spatial_x", "spatial_y", "spatial_z",
    )

    def __init__(
        self,
        label: str,
        confidence: float,
        x_min: float,
        y_min: float,
        x_max: float,
        y_max: float,
        spatial_x: float = 0.0,
        spatial_y: float = 0.0,
        spatial_z: float = 0.0,
    ):
        self.label = label
        self.confidence = confidence
        self.x_min = x_min
        self.y_min = y_min
        self.x_max = x_max
        self.y_max = y_max
        self.spatial_x = spatial_x  # metres, right +
        self.spatial_y = spatial_y  # metres, down +
        self.spatial_z = spatial_z  # metres, forward +

    @property
    def distance_m(self) -> float:
        return math.sqrt(
            self.spatial_x ** 2 + self.spatial_y ** 2 + self.spatial_z ** 2
        )

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "confidence": round(self.confidence, 3),
            "bbox": [self.x_min, self.y_min, self.x_max, self.y_max],
            "distance_m": round(self.distance_m, 2),
            "spatial": {
                "x": round(self.spatial_x, 3),
                "y": round(self.spatial_y, 3),
                "z": round(self.spatial_z, 3),
            },
        }



# COCO_LABELS imported from model_registry


# ===================================================================
# OakDriver
# ===================================================================
class OakDriver:
    """Manage a single OAK-D camera: build pipeline, stream frames."""

    def __init__(
        self,
        config: OakConfig | None = None,
        *,
        mock: bool = False,
        device_id: str | None = None,
    ):
        self.config = config or OakConfig()
        self.mock = mock or (not _DAI_AVAILABLE)
        self.device_id = device_id  # MX ID or IP address

        if not _DAI_AVAILABLE and not mock:
            logger.warning(
                "depthai SDK not available — falling back to mock mode"
            )
            self.mock = True

        # Internal state
        self._device: Any = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

        # Latest frame data (protected by _lock)
        self._rgb: np.ndarray | None = None
        self._depth: np.ndarray | None = None
        self._last_depth_host_t: float = 0.0  # Rate limiter for host-side depth copy
        self._detections: list[Detection] = []
        self._jpeg: bytes | None = None  # Pre-encoded JPEG for low-latency serving
        self._encoded_rgb: bool = False  # True when using on-device MJPEG encoder

        # IMU orientation (rotation vector as quaternion + euler)
        self._imu_rotation: dict | None = None  # {qx, qy, qz, qw, pitch, roll, yaw, accuracy_rad}
        # Ring buffer of recent quaternions for stability checking:
        # list of (timestamp, (qx, qy, qz, qw)). Kept short — only the
        # last ~3 seconds. Used by is_stable() for the calibrate button.
        self._imu_history: list[tuple[float, tuple[float, float, float, float]]] = []

        # Health metrics
        self._fps: float = 0.0          # RGB delivery rate (encoder output)
        self._nn_fps: float = 0.0       # NN detection throughput (decoupled)
        self._latency_ms: float = 0.0
        self._connected: bool = False
        self._frame_count: int = 0
        self._last_frame_time: float = 0.0
        self._fps_window: list[float] = []
        self._nn_fps_window: list[float] = []  # Ring buffer of NN packet arrival times
        self._last_error: str | None = None  # Last connect/stream error, cleared on success
        self._ever_connected: bool = False   # True once _connect() has succeeded at least once

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the acquisition loop in a background thread."""
        if self._running:
            return
        self._running = True
        target = self._mock_loop if self.mock else self._live_loop
        self._thread = threading.Thread(target=target, daemon=True, name="oak-driver")
        self._thread.start()
        logger.info("OakDriver started (mock=%s)", self.mock)

    def stop(self) -> None:
        """Stop acquisition and release device resources."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        self._disconnect()
        logger.info("OakDriver stopped")

    def get_frame(self) -> dict | None:
        """Return the latest frame bundle, or None if no data yet.

        Returns dict with keys:
            rgb        — numpy uint8 array, shape (H, W, 3) BGR
            depth      — numpy float32 array, shape (H, W) in metres
            detections — list of Detection objects (call .to_dict() to serialise)
            timestamp  — float, time.time() when frame was captured
        """
        with self._lock:
            if self._jpeg is None and self._rgb is None:
                return None
            # Lazily decode JPEG to numpy if needed
            rgb = self._rgb
            if rgb is None and self._jpeg is not None:
                import cv2
                rgb = cv2.imdecode(
                    np.frombuffer(self._jpeg, dtype=np.uint8),
                    cv2.IMREAD_COLOR,
                )
            return {
                "rgb": rgb,
                "depth": self._depth,
                "detections": list(self._detections),
                "timestamp": self._last_frame_time,
            }

    def get_jpeg(self) -> bytes | None:
        """Return pre-encoded JPEG bytes of the latest frame, or None."""
        with self._lock:
            return self._jpeg

    def get_imu(self) -> dict | None:
        """Return latest IMU orientation, or None if unavailable."""
        with self._lock:
            return dict(self._imu_rotation) if self._imu_rotation else None

    def get_imu_average(self, window_s: float = 2.0) -> dict | None:
        """Return a vibration-averaged IMU quaternion over the last ``window_s``.

        Critical for the bump watchdog on heavy equipment: a 650hp diesel
        shaking the mount will jitter the instantaneous quaternion by
        several degrees while the *mean* orientation is rock-stable. The
        watchdog compares this averaged quat against the reference, so
        vibration alone never trips the alarm.

        Returns ``None`` if there's no history yet. Otherwise a dict with
        ``qx/qy/qz/qw``, ``samples``, ``timestamp`` (latest sample time),
        and ``accuracy_rad`` (latest BNO085 estimate).
        """
        now = time.time()
        with self._lock:
            history = [
                (t, q) for (t, q) in self._imu_history
                if now - t <= window_s
            ]
            latest = dict(self._imu_rotation) if self._imu_rotation else None
        if not history or latest is None:
            return None
        quats = [q for (_t, q) in history]
        mq = _quat_mean(quats)
        if mq is None:
            return None
        return {
            "qx": mq[0], "qy": mq[1], "qz": mq[2], "qw": mq[3],
            "samples": len(history),
            "timestamp": history[-1][0],
            "accuracy_rad": latest.get("accuracy_rad"),
        }

    def is_stable(
        self,
        window_s: float = 3.0,
        max_delta_deg: float = 3.0,
        require_samples: int = 20,
    ) -> dict:
        """Check whether the IMU has been steady enough to calibrate.

        Returns a dict shaped like::

            {
              "stable": bool,
              "samples": int,
              "max_delta_deg": float,  # observed worst-case angle over window
              "window_s": float,
              "accuracy_rad": float | None,  # latest BNO085 accuracy estimate
              "reason": str,  # human-readable when stable=False
            }

        Stability is defined as: the mean quaternion of the FIRST half
        of the window is within ``max_delta_deg`` of the mean of the
        SECOND half. This tolerates high-frequency vibration (diesel
        engines, hydraulic pumps, pneumatic hammers) while still
        catching a real drift — if the mean orientation is moving, the
        two halves disagree; if only the samples jitter around a fixed
        mean, the two halves match.

        The calibrate API endpoint MUST call this before snapshotting
        a reference quaternion — calibrating while the camera is still
        settling is exactly how a zone gets locked to a wrong frame.
        """
        now = time.time()
        with self._lock:
            history = [
                (t, q) for (t, q) in self._imu_history
                if now - t <= window_s
            ]
            latest = dict(self._imu_rotation) if self._imu_rotation else None

        if latest is None or not history:
            return {
                "stable": False,
                "samples": len(history),
                "max_delta_deg": 0.0,
                "window_s": window_s,
                "accuracy_rad": None,
                "reason": "No IMU data yet",
            }

        if len(history) < require_samples:
            return {
                "stable": False,
                "samples": len(history),
                "max_delta_deg": 0.0,
                "window_s": window_s,
                "accuracy_rad": latest.get("accuracy_rad"),
                "reason": f"Collecting IMU samples ({len(history)}/{require_samples})",
            }

        # Split-half mean drift: compare the averaged orientation of the
        # older half of the window against the averaged orientation of
        # the newer half. Vibration (symmetric jitter around a fixed
        # mean) cancels in the averages; true drift shows up because
        # the two halves no longer agree.
        mid = len(history) // 2
        older = [q for (_t, q) in history[:mid]]
        newer = [q for (_t, q) in history[mid:]]
        q_old = _quat_mean(older) if older else None
        q_new = _quat_mean(newer) if newer else None
        if q_old is None or q_new is None:
            worst_deg = 0.0
        else:
            dot = abs(
                q_old[0] * q_new[0] + q_old[1] * q_new[1]
                + q_old[2] * q_new[2] + q_old[3] * q_new[3]
            )
            dot = min(1.0, max(-1.0, dot))
            worst_deg = math.degrees(2.0 * math.acos(dot))

        accuracy_rad = latest.get("accuracy_rad")
        # BNO085 reports absolute-orientation uncertainty in radians. A
        # fresh power-on sits around 6-10° until the magnetometer sees a
        # figure-8 calibration; it settles to ~2-3° after. We only need
        # *consistent* readings for the bump watchdog (deltas relative
        # to the reference quat) so absolute accuracy just needs to be
        # "sensor isn't flailing" — 10° is a comfortable ceiling.
        acc_ok = accuracy_rad is None or accuracy_rad <= math.radians(10.0)

        stable = worst_deg <= max_delta_deg and acc_ok
        reason = ""
        if not stable:
            if worst_deg > max_delta_deg:
                reason = f"Camera moving ({worst_deg:.2f}° > {max_delta_deg}°)"
            elif not acc_ok:
                reason = (
                    f"IMU accuracy {math.degrees(accuracy_rad):.1f}° — "
                    "wave camera in a figure-8 to calibrate compass"
                )

        return {
            "stable": stable,
            "samples": len(history),
            "max_delta_deg": round(worst_deg, 3),
            "window_s": window_s,
            "accuracy_rad": accuracy_rad,
            "reason": reason,
        }

    def health(self) -> dict:
        """Return current health metrics."""
        return {
            "connected": self._connected,
            "mock": self.mock,
            "fps": round(self._fps, 1),           # Camera / encoder rate
            "nn_fps": round(self._nn_fps, 1),     # NN inference throughput
            "latency_ms": round(self._latency_ms, 1),
            "frame_count": self._frame_count,
            "device_id": self.device_id,
            "last_error": self._last_error,
            "ever_connected": self._ever_connected,
            "model_id": self.config.nn_model_id,
            "last_frame_time": self._last_frame_time,
        }

    # ------------------------------------------------------------------
    # Discovery (class-level)
    # ------------------------------------------------------------------

    @staticmethod
    def discover() -> list[dict]:
        """Find all OAK-D cameras on the network.

        Returns a list of dicts with keys: mx_id, state, name, protocol.
        """
        if not _DAI_AVAILABLE:
            logger.warning("depthai not available — returning empty discovery list")
            return []

        results = []
        for info in dai.Device.getAllAvailableDevices():
            device_id = info.getDeviceId() if hasattr(info, "getDeviceId") else info.deviceId
            results.append({
                "mx_id": device_id,
                "state": str(info.state),
                "name": info.name,
                "protocol": str(info.protocol),
            })
        logger.info("Discovered %d OAK-D device(s)", len(results))
        return results

    # ------------------------------------------------------------------
    # Live camera loop (depthai v3.5.0 API)
    # ------------------------------------------------------------------

    def _find_device_info(self) -> Any:
        """Resolve a DeviceInfo for connection.

        Prefers discovery-based lookup (which returns fully-populated
        DeviceInfo with correct state/protocol) over constructing from
        raw IP, since the latter can trigger incompatible boot paths.
        """
        # Always try discovery first — more reliable for PoE
        for attempt in range(6):
            available = dai.Device.getAllAvailableDevices()
            for info in available:
                if self.device_id is None:
                    logger.info("Discovery found device: %s (%s)", info.name, info.deviceId)
                    return info  # No preference — return first
                if info.name == self.device_id or info.deviceId == self.device_id:
                    logger.info("Discovery matched device: %s (%s)", info.name, info.deviceId)
                    return info
            if not self.device_id:
                break  # No device_id and nothing found
            logger.info("Discovery attempt %d/6 — device %s not found yet", attempt + 1, self.device_id)
            time.sleep(3)

        # Fall back to constructing from IP/MX ID with protocol hints
        if self.device_id:
            logger.warning(
                "Device %s not found via discovery — using direct DeviceInfo with TCP hint",
                self.device_id,
            )
            info = dai.DeviceInfo(self.device_id)
            info.state = dai.XLinkDeviceState.X_LINK_BOOTLOADER
            info.protocol = dai.XLinkProtocol.X_LINK_TCP_IP
            return info
        return None

    def _connect(self) -> bool:
        """Build pipeline, connect to device, and set up output queues."""
        try:
            cfg = self.config
            device_info = self._find_device_info()

            # ── Create pipeline with device ──────────────────────
            if device_info:
                self._pipeline = dai.Pipeline(dai.Device(device_info))
            else:
                self._pipeline = dai.Pipeline()
            p = self._pipeline

            # ── Color camera (auto-assigns to CAM_A) ─────────────
            cam_rgb = p.create(dai.node.Camera)
            cam_rgb.build(sensorFps=cfg.fps)

            # Cap auto-exposure to the frame period so the sensor can't
            # drop below target FPS in low light. At 30 FPS the frame
            # period is 33333 µs — if AE extends exposure past this,
            # the OV9782 automatically halves the sensor rate, capping
            # us at ~15-28 FPS depending on scene brightness. Pinning
            # the ceiling at 33ms guarantees 30 FPS; the image will
            # just get noisier (ISO goes up) in dim conditions.
            try:
                max_exp_us = int(1_000_000 / max(cfg.fps, 1)) - 500  # 500µs readout margin
                cam_rgb.initialControl.setAutoExposureLimit(max_exp_us)
                logger.info(
                    "Auto-exposure capped at %d µs to hold %d FPS",
                    max_exp_us, cfg.fps,
                )
            except Exception:
                logger.warning("Could not set auto-exposure limit", exc_info=True)

            # ── Stereo depth (optional — disabled saves PoE bandwidth)
            if cfg.enable_depth:
                stereo = p.create(dai.node.StereoDepth)
                preset = _DEPTH_PRESET_MAP.get(
                    cfg.depth_preset, _DEPTH_PRESET_MAP["HIGH_ACCURACY"]
                )
                stereo.build(autoCreateCameras=True, presetMode=preset)
                stereo.setLeftRightCheck(cfg.lr_check)
                stereo.setSubpixel(cfg.subpixel)

                # Depth post-processing: minimal filters for speed
                stereo.initialConfig.postProcessing.thresholdFilter.minRange = int(cfg.min_depth_m * 1000)
                stereo.initialConfig.postProcessing.thresholdFilter.maxRange = int(cfg.max_depth_m * 1000)
                stereo.initialConfig.postProcessing.speckleFilter.enable = False
                stereo.initialConfig.postProcessing.temporalFilter.enable = False
                stereo.initialConfig.postProcessing.spatialFilter.enable = False
                # Depth XLink bandwidth was the main reason we were
                # capped at ~14 FPS: uint16 * 640x400 * 30 ≈ 120 Mbps,
                # which saturates 100-Base PoE and starves the MJPEG
                # stream. Decimation 4 drops depth to 320x200 ≈ 30 Mbps
                # while still giving us enough resolution for spatial
                # NN output and the depth image API.
                stereo.initialConfig.postProcessing.decimationFilter.decimationFactor = 4

                # maxSize=1, non-blocking: always serve the latest
                # depth frame, drop anything older instead of piling up
                # a backlog that can stall the pipeline under load.
                try:
                    self._q_depth = stereo.depth.createOutputQueue(maxSize=1, blocking=False)
                except TypeError:
                    # Older depthai signatures — fall back and set after
                    self._q_depth = stereo.depth.createOutputQueue()
                    try:
                        self._q_depth.setMaxSize(1)
                        self._q_depth.setBlocking(False)
                    except Exception:
                        pass
            else:
                self._q_depth = None

            # ── Spatial detection network (on-device inference) ──
            self._q_nn = None
            self._nn_labels: list[str] = COCO_LABELS  # default fallback
            if cfg.enable_nn and cfg.enable_depth:
                # NN failures are fatal: an orphan SpatialDetectionNetwork node
                # with no blob crashes p.start() with a cryptic
                # "NeuralNetwork(N) - No blob is loaded" error. Raise a clean,
                # user-facing error instead so the status API can surface it.
                model_def = get_model(cfg.nn_model_id) or get_default_model()
                self._nn_labels = model_def.classes

                nn = p.create(dai.node.SpatialDetectionNetwork)

                try:
                    if model_def.source == "local" and model_def.blob_path:
                        import os
                        blob_abs = os.path.join(
                            os.path.dirname(os.path.dirname(__file__)),
                            model_def.blob_path,
                        )
                        if not os.path.isfile(blob_abs):
                            raise RuntimeError(
                                f"Local blob for '{model_def.id}' not found at "
                                f"{blob_abs}. Drop the compiled .blob file there "
                                "and restart, or pick a different model."
                            )
                        nn.build(cam_rgb, stereo, blob_abs, fps=cfg.fps)
                        logger.info(
                            "SpatialDetectionNetwork loaded (local): %s (%s)",
                            model_def.name, blob_abs,
                        )
                    else:
                        nn.build(cam_rgb, stereo, model_def.slug, fps=cfg.fps)
                        logger.info(
                            "SpatialDetectionNetwork loaded: %s (%s)",
                            model_def.name, model_def.slug,
                        )
                except Exception as e:
                    # Extract the most useful line from the depthai error
                    msg = str(e).strip().splitlines()[-1] if str(e).strip() else repr(e)
                    if "404" in msg or "Cannot find a Model" in msg:
                        pretty = (
                            f"Model '{model_def.id}' not found on HubAI "
                            f"(slug: {model_def.slug}). Pick a different model in Settings."
                        )
                    else:
                        pretty = f"Model '{model_def.id}' failed to load: {msg}"
                    logger.error("NN build failed — %s", pretty)
                    raise RuntimeError(pretty) from e

                try:
                    self._q_nn = nn.out.createOutputQueue(maxSize=1, blocking=False)
                except TypeError:
                    self._q_nn = nn.out.createOutputQueue()
                    try:
                        self._q_nn.setMaxSize(1); self._q_nn.setBlocking(False)
                    except Exception:
                        pass

                # CRITICAL: make the NN input non-blocking so cam_rgb
                # is never back-pressured by slow inference. This is the
                # async pipeline pattern — when the NN can't keep up,
                # incoming frames simply drop at its input queue and the
                # encoder branch continues running at full 30 FPS. The
                # tracker downstream covers the gap by predicting
                # positions between NN updates.
                for attr in ("input", "inputDepth"):
                    port = getattr(nn, attr, None)
                    if port is None:
                        continue
                    try:
                        port.setBlocking(False)
                    except Exception:
                        pass
                    for setter in ("setQueueSize", "setMaxSize"):
                        fn = getattr(port, setter, None)
                        if fn:
                            try:
                                fn(1)
                            except Exception:
                                pass

            # ── RGB output with on-device MJPEG encoding ────────
            rgb_size = _RGB_SIZE_MAP.get(cfg.resolution_rgb, (640, 480))
            rgb_out = cam_rgb.requestOutput(
                rgb_size, type=dai.ImgFrame.Type.NV12, fps=cfg.fps
            )

            encoder = p.create(dai.node.VideoEncoder)
            encoder.build(
                rgb_out,
                profile=dai.VideoEncoderProperties.Profile.MJPEG,
                quality=60,
                frameRate=cfg.fps,
            )
            # Encoder output queue: maxSize=1 non-blocking so the UI
            # always sees the newest JPEG and we never sit on stale
            # frames. This is what kills apparent lag the most.
            try:
                self._q_rgb = encoder.bitstream.createOutputQueue(maxSize=1, blocking=False)
            except TypeError:
                self._q_rgb = encoder.bitstream.createOutputQueue()
                try:
                    self._q_rgb.setMaxSize(1); self._q_rgb.setBlocking(False)
                except Exception:
                    pass
            self._encoded_rgb = True  # Flag: frames arrive as JPEG

            # ── IMU — rotation vector for camera orientation ────
            self._q_imu = None
            try:
                imu = p.create(dai.node.IMU)
                imu.enableIMUSensor(dai.IMUSensor.ROTATION_VECTOR, 100)
                imu.setBatchReportThreshold(1)
                imu.setMaxBatchReports(1)
                try:
                    self._q_imu = imu.out.createOutputQueue(maxSize=4, blocking=False)
                except TypeError:
                    self._q_imu = imu.out.createOutputQueue()
                    try:
                        self._q_imu.setMaxSize(4); self._q_imu.setBlocking(False)
                    except Exception:
                        pass
                logger.info("IMU enabled (rotation vector @ 100 Hz)")
            except Exception:
                logger.warning("IMU not available on this device — orientation disabled")

            # ── Start ────────────────────────────────────────────
            p.start()
            self._device = p.getDefaultDevice()

            # ── IR illumination ──────────────────────────────────
            ir_drivers = self._device.getIrDrivers()
            if ir_drivers:
                logger.info("IR drivers detected: %s", ir_drivers)
                if cfg.ir_flood_intensity > 0:
                    self._device.setIrFloodLightIntensity(cfg.ir_flood_intensity)
                    logger.info("IR flood light set to %.0f%%", cfg.ir_flood_intensity * 100)
                if cfg.ir_dot_intensity > 0:
                    self._device.setIrLaserDotProjectorIntensity(cfg.ir_dot_intensity)
                    logger.info("IR dot projector set to %.0f%%", cfg.ir_dot_intensity * 100)
            else:
                logger.warning("No IR drivers found on device")

            self._connected = True
            self._ever_connected = True
            self._last_error = None
            logger.info("Connected to OAK-D (id=%s)", self.device_id or "auto")
            return True

        except Exception as e:
            # Prefer an already-friendly RuntimeError message; otherwise use last line
            msg = str(e).strip().splitlines()[-1] if str(e).strip() else repr(e)
            self._last_error = msg
            logger.exception("Failed to connect to OAK-D")
            self._disconnect()
            return False

    def _disconnect(self) -> None:
        """Release device + pipeline with a hard timeout.

        depthai's ``device.close()`` can block indefinitely when the device
        is in a crashed/wedged state (e.g. after a failed NN build on a
        Myriad-X). We run it on a background thread and time out after 3s,
        leaking the handle if necessary — the OS reclaims XLink on process
        exit, and a wedged device will recover on the next successful boot.
        """
        device = self._device
        pipeline = getattr(self, "_pipeline", None)
        self._device = None
        self._pipeline = None
        self._q_rgb = None
        self._q_depth = None
        self._q_nn = None
        self._connected = False

        if device is None and pipeline is None:
            return

        def _do_close():
            if pipeline is not None:
                try:
                    pipeline.stop()
                except Exception:
                    pass
            if device is not None:
                try:
                    device.close()
                except Exception:
                    pass

        t = threading.Thread(target=_do_close, daemon=True, name="oak-disconnect")
        t.start()
        t.join(timeout=3.0)
        if t.is_alive():
            logger.warning(
                "OAK-D close() did not return within 3s — abandoning handle. "
                "This is usually caused by a prior device crash; a process "
                "restart will fully recover it."
            )
        else:
            logger.info("OAK-D device closed (XLink released)")

    def _live_loop(self) -> None:
        """Acquisition loop for a real OAK-D camera with auto-reconnect."""
        while self._running:
            if not self._connected:
                if not self._connect():
                    logger.info(
                        "Retrying in %.1fs...", self.config.reconnect_interval_s
                    )
                    time.sleep(self.config.reconnect_interval_s)
                    continue

            try:
                while self._running and self._connected:
                    # Block on the RGB queue — the thread parks cheaply
                    # and wakes the instant a new encoded frame arrives.
                    # This removes the time.sleep(0.001) polling loop,
                    # which on Windows was actually sleeping ~15 ms per
                    # miss (default scheduler timer resolution), capping
                    # effective throughput around 27-28 FPS instead of
                    # the camera's true 30. Use a short timeout so the
                    # loop can still check self._running periodically.
                    try:
                        in_rgb = self._q_rgb.get()  # blocking
                    except Exception:
                        in_rgb = None
                    if in_rgb is None:
                        continue
                    t0 = time.time()

                    # MJPEG-encoded: use hardware JPEG directly, skip CPU decode
                    if self._encoded_rgb:
                        jpeg_bytes = bytes(in_rgb.getData())
                        rgb_frame = None  # Decode lazily only if needed
                    else:
                        rgb_frame = in_rgb.getCvFrame()
                        jpeg_bytes = self._encode_jpeg(rgb_frame)

                    # Depth: only process on host at most ~4 Hz. We
                    # drain the queue to keep it fresh (non-blocking,
                    # maxSize=1 drops older frames at the device edge)
                    # but we skip the expensive astype+clip on most
                    # ticks. Nothing in the hot path needs full-rate
                    # host depth — the NN consumes it on-device for
                    # spatial coords, and the /api/camera/depthimage
                    # endpoint is happy with ~4 Hz.
                    depth_frame = None
                    if self._q_depth is not None:
                        in_depth = self._q_depth.tryGet()
                        if in_depth is not None:
                            now_d = time.time()
                            if (now_d - getattr(self, "_last_depth_host_t", 0.0)) >= 0.25:
                                raw = in_depth.getFrame().astype(np.float32)
                                depth_frame = np.clip(
                                    raw / 1000.0,
                                    self.config.min_depth_m,
                                    self.config.max_depth_m,
                                )
                                self._last_depth_host_t = now_d

                    # ── Parse NN detections ──────────────────────
                    # This queue is decoupled from the RGB encoder —
                    # new NN packets arrive at the inference rate, not
                    # the camera rate. We track their arrival cadence
                    # as a separate FPS so the HUD can show "NN 25 FPS"
                    # while the camera feed runs at a full 30 FPS.
                    detections: list[Detection] = []
                    if self._q_nn is not None:
                        in_nn = self._q_nn.tryGet()
                        if in_nn is not None:
                            nn_now = time.time()
                            self._nn_fps_window.append(nn_now)
                            if len(self._nn_fps_window) > 30:
                                self._nn_fps_window = self._nn_fps_window[-30:]
                            if len(self._nn_fps_window) >= 2:
                                span = self._nn_fps_window[-1] - self._nn_fps_window[0]
                                if span > 0:
                                    self._nn_fps = (len(self._nn_fps_window) - 1) / span
                            for det in in_nn.detections:
                                label_id = det.label
                                labels = self._nn_labels
                                raw_label = (
                                    labels[label_id]
                                    if 0 <= label_id < len(labels)
                                    else f"class_{label_id}"
                                )
                                # Drop everything that isn't a person or
                                # vehicle (see _SAFETY_LABELS docstring).
                                # Once GridFront-v1 ships with site-specific
                                # classes this filter goes away.
                                label_str = _SAFETY_LABELS.get(raw_label)
                                if label_str is None:
                                    continue
                                sc = det.spatialCoordinates
                                detections.append(
                                    Detection(
                                        label=label_str,
                                        confidence=det.confidence,
                                        x_min=det.xmin,
                                        y_min=det.ymin,
                                        x_max=det.xmax,
                                        y_max=det.ymax,
                                        spatial_x=sc.x / 1000.0,
                                        spatial_y=sc.y / 1000.0,
                                        spatial_z=sc.z / 1000.0,
                                    )
                                )

                    # ── Read IMU rotation ───────────────────────
                    imu_data = None
                    imu_quat = None
                    if self._q_imu is not None:
                        imu_packet = self._q_imu.tryGet()
                        if imu_packet is not None:
                            for imu_report in imu_packet.packets:
                                rv = imu_report.rotationVector
                                qx, qy, qz, qw = rv.i, rv.j, rv.k, rv.real
                                # BNO085 reports orientation confidence as
                                # an angular uncertainty in radians. Field
                                # name varies across depthai versions, so
                                # try a couple of attributes.
                                accuracy_rad = None
                                for attr in ("rotationVectorAccuracy", "accuracy"):
                                    if hasattr(rv, attr):
                                        try:
                                            accuracy_rad = float(getattr(rv, attr))
                                        except Exception:
                                            accuracy_rad = None
                                        break
                                # Quaternion to euler (pitch/roll/yaw)
                                sinr = 2.0 * (qw * qx + qy * qz)
                                cosr = 1.0 - 2.0 * (qx * qx + qy * qy)
                                roll = math.atan2(sinr, cosr)
                                sinp = 2.0 * (qw * qy - qz * qx)
                                pitch = math.asin(max(-1.0, min(1.0, sinp)))
                                siny = 2.0 * (qw * qz + qx * qy)
                                cosy = 1.0 - 2.0 * (qy * qy + qz * qz)
                                yaw = math.atan2(siny, cosy)
                                imu_data = {
                                    "qx": round(qx, 6), "qy": round(qy, 6),
                                    "qz": round(qz, 6), "qw": round(qw, 6),
                                    "pitch": round(pitch, 4),
                                    "roll": round(roll, 4),
                                    "yaw": round(yaw, 4),
                                    "accuracy_rad": accuracy_rad,
                                    "timestamp": time.time(),
                                }
                                imu_quat = (qx, qy, qz, qw)

                    with self._lock:
                        self._rgb = rgb_frame
                        # Only overwrite cached depth when we actually
                        # produced a new one on this tick — most ticks
                        # we skip the expensive clip to stay fast.
                        if depth_frame is not None:
                            self._depth = depth_frame
                        self._detections = detections
                        self._jpeg = jpeg_bytes
                        if imu_data is not None:
                            self._imu_rotation = imu_data
                            if imu_quat is not None:
                                t_imu = imu_data["timestamp"]
                                self._imu_history.append((t_imu, imu_quat))
                                # Keep only the last 3 seconds
                                cutoff = t_imu - 3.0
                                self._imu_history = [
                                    e for e in self._imu_history if e[0] >= cutoff
                                ]
                        self._last_frame_time = time.time()
                        self._frame_count += 1

                    # Auto-IR: check brightness every 30 frames
                    if (self.config.ir_auto and self._device is not None
                            and self._frame_count % 30 == 0):
                        self._auto_ir_check(jpeg_bytes, rgb_frame)

                    self._update_fps(t0)

            except Exception:
                logger.exception("OAK-D stream error — will reconnect")
                self._disconnect()
                time.sleep(self.config.reconnect_interval_s)

    # ------------------------------------------------------------------
    # Mock camera loop
    # ------------------------------------------------------------------

    def _mock_loop(self) -> None:
        """Generate synthetic frames at ~config.fps."""
        self._connected = True
        logger.info("Mock camera loop running at %d FPS", self.config.fps)
        step = 0
        interval = 1.0 / max(self.config.fps, 1)

        while self._running:
            t0 = time.time()
            step += 1
            angle = step * 0.04

            # ── Synthetic RGB: grey 640x480 ──────────────────────
            rgb = np.full((480, 640, 3), 128, dtype=np.uint8)

            # ── Synthetic depth map with a few "objects" ─────────
            depth = np.full((480, 640), 10.0, dtype=np.float32)

            # Place 2-3 blobs at varying positions
            mock_objects = self._mock_objects(step, angle)
            for obj in mock_objects:
                cx, cy, radius, obj_depth = obj["cx"], obj["cy"], obj["radius"], obj["depth_m"]
                y_indices, x_indices = np.ogrid[:480, :640]
                mask = ((x_indices - cx) ** 2 + (y_indices - cy) ** 2) <= radius ** 2
                depth[mask] = obj_depth
                # Tint the RGB slightly so objects are visible
                rgb[mask] = [100, 140, 180]

            # ── Synthetic detections ─────────────────────────────
            detections: list[Detection] = []
            for obj in mock_objects:
                # Approximate spatial position from pixel + depth
                depth_m = obj["depth_m"]
                cx_norm = obj["cx"] / 640.0
                cy_norm = obj["cy"] / 480.0
                # Simple pinhole: x_m ≈ (cx_norm - 0.5) * depth * fov_factor
                spatial_x = (cx_norm - 0.5) * depth_m * 1.5
                spatial_y = (cy_norm - 0.5) * depth_m * 1.1
                spatial_z = depth_m
                detections.append(
                    Detection(
                        label=obj["label"],
                        confidence=obj["confidence"],
                        x_min=max(0.0, (obj["cx"] - obj["radius"]) / 640),
                        y_min=max(0.0, (obj["cy"] - obj["radius"]) / 480),
                        x_max=min(1.0, (obj["cx"] + obj["radius"]) / 640),
                        y_max=min(1.0, (obj["cy"] + obj["radius"]) / 480),
                        spatial_x=spatial_x,
                        spatial_y=spatial_y,
                        spatial_z=spatial_z,
                    )
                )

            jpeg_bytes = self._encode_jpeg(rgb)

            with self._lock:
                self._rgb = rgb
                self._depth = depth
                self._detections = detections
                self._jpeg = jpeg_bytes
                self._last_frame_time = time.time()
                self._frame_count += 1

            self._update_fps(t0)

            elapsed = time.time() - t0
            sleep_time = max(0.0, interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

        self._connected = False

    @staticmethod
    def _mock_objects(step: int, angle: float) -> list[dict]:
        """Return 2-3 synthetic objects orbiting in the frame."""
        objects = [
            {
                "label": "person",
                "confidence": 0.92,
                "cx": int(320 + 150 * math.sin(angle)),
                "cy": int(240 + 80 * math.cos(angle)),
                "radius": 40,
                "depth_m": 3.5 + 2.0 * math.sin(angle * 0.3),
            },
            {
                "label": "car",
                "confidence": 0.85,
                "cx": int(200 + 100 * math.cos(angle * 0.7)),
                "cy": int(300 + 60 * math.sin(angle * 0.5)),
                "radius": 55,
                "depth_m": 6.0 + 3.0 * math.cos(angle * 0.4),
            },
        ]
        # Occasionally add a third detection
        if step % 30 < 15:
            objects.append({
                "label": "person",
                "confidence": 0.74,
                "cx": int(480 + 80 * math.sin(angle * 1.3)),
                "cy": int(180 + 50 * math.cos(angle * 0.9)),
                "radius": 35,
                "depth_m": 2.0 + 1.5 * math.sin(angle * 0.6),
            })
        return objects

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _encode_jpeg(frame: np.ndarray, quality: int = 50) -> bytes:
        """Encode a frame as JPEG for streaming."""
        import cv2
        _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return buf.tobytes()

    _ir_active: bool = False
    _ir_cooldown: int = 0  # Frames to wait before next IR toggle

    def _auto_ir_check(self, jpeg_bytes: bytes | None, rgb_frame: np.ndarray | None) -> None:
        """Auto-enable IR when the scene is dark. Uses cooldown to prevent flicker."""
        if self._ir_cooldown > 0:
            self._ir_cooldown -= 1
            return
        try:
            import cv2
            if rgb_frame is not None:
                grey = cv2.cvtColor(rgb_frame, cv2.COLOR_BGR2GRAY)
            elif jpeg_bytes is not None:
                img = cv2.imdecode(
                    np.frombuffer(jpeg_bytes, dtype=np.uint8), cv2.IMREAD_GRAYSCALE
                )
                if img is None:
                    return
                grey = img
            else:
                return

            mean_brightness = float(grey.mean())

            if mean_brightness < 35 and not self._ir_active:
                self._device.setIrFloodLightIntensity(0.5)
                self._device.setIrLaserDotProjectorIntensity(0.3)
                self._ir_active = True
                self._ir_cooldown = 150  # Wait ~5 seconds before re-checking
                logger.info("Auto-IR ON (brightness=%.0f)", mean_brightness)
            elif mean_brightness > 120 and self._ir_active:
                # Only turn off if scene is very bright (not just IR-lit)
                self._device.setIrFloodLightIntensity(0)
                self._device.setIrLaserDotProjectorIntensity(0)
                self._ir_active = False
                self._ir_cooldown = 150
                logger.info("Auto-IR OFF (brightness=%.0f)", mean_brightness)
        except Exception:
            pass

    def _update_fps(self, t0: float) -> None:
        """Maintain a rolling FPS estimate over the last 30 frames."""
        now = time.time()
        self._latency_ms = (now - t0) * 1000
        self._fps_window.append(now)
        # Keep last 30 timestamps
        if len(self._fps_window) > 30:
            self._fps_window = self._fps_window[-30:]
        if len(self._fps_window) >= 2:
            span = self._fps_window[-1] - self._fps_window[0]
            if span > 0:
                self._fps = (len(self._fps_window) - 1) / span
