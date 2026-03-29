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
# Resolution helpers
# ---------------------------------------------------------------------------
_RGB_RESOLUTION_MAP: dict[str, Any] = {}
_DEPTH_PRESET_MAP: dict[str, Any] = {}

if _DAI_AVAILABLE:
    _RGB_RESOLUTION_MAP = {
        "1080p": dai.ColorCameraProperties.SensorResolution.THE_1080_P,
        "4k": dai.ColorCameraProperties.SensorResolution.THE_4_K,
        "720p": dai.ColorCameraProperties.SensorResolution.THE_720_P,
    }
    _DEPTH_PRESET_MAP = {
        "HIGH_ACCURACY": dai.node.StereoDepth.PresetMode.HIGH_ACCURACY,
        "HIGH_DENSITY": dai.node.StereoDepth.PresetMode.HIGH_DENSITY,
        "DEFAULT": dai.node.StereoDepth.PresetMode.DEFAULT,
    }


# ---------------------------------------------------------------------------
# Detection dataclass (lightweight, dict-friendly)
# ---------------------------------------------------------------------------
class Detection:
    """Single NN detection result."""

    __slots__ = ("label", "confidence", "x_min", "y_min", "x_max", "y_max")

    def __init__(
        self,
        label: str,
        confidence: float,
        x_min: float,
        y_min: float,
        x_max: float,
        y_max: float,
    ):
        self.label = label
        self.confidence = confidence
        self.x_min = x_min
        self.y_min = y_min
        self.x_max = x_max
        self.y_max = y_max

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "confidence": round(self.confidence, 3),
            "bbox": [self.x_min, self.y_min, self.x_max, self.y_max],
        }


# MobileNet-SSD label map (VOC)
MOBILENET_LABELS = [
    "background", "aeroplane", "bicycle", "bird", "boat", "bottle", "bus",
    "car", "cat", "chair", "cow", "diningtable", "dog", "horse",
    "motorbike", "person", "pottedplant", "sheep", "sofa", "train",
    "tvmonitor",
]


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
        self._detections: list[Detection] = []

        # Health metrics
        self._fps: float = 0.0
        self._latency_ms: float = 0.0
        self._connected: bool = False
        self._frame_count: int = 0
        self._last_frame_time: float = 0.0
        self._fps_window: list[float] = []

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
            if self._rgb is None:
                return None
            return {
                "rgb": self._rgb.copy(),
                "depth": self._depth.copy() if self._depth is not None else None,
                "detections": list(self._detections),
                "timestamp": self._last_frame_time,
            }

    def health(self) -> dict:
        """Return current health metrics."""
        return {
            "connected": self._connected,
            "mock": self.mock,
            "fps": round(self._fps, 1),
            "latency_ms": round(self._latency_ms, 1),
            "frame_count": self._frame_count,
            "device_id": self.device_id,
        }

    # ------------------------------------------------------------------
    # Discovery (class-level)
    # ------------------------------------------------------------------

    @staticmethod
    def discover() -> list[dict]:
        """Find all OAK-D cameras on the network.

        Returns a list of dicts with keys: mx_id, state, name.
        """
        if not _DAI_AVAILABLE:
            logger.warning("depthai not available — returning empty discovery list")
            return []

        results = []
        for info in dai.Device.getAllAvailableDevices():
            results.append({
                "mx_id": info.getMxId(),
                "state": str(info.state),
                "name": info.getMxId(),
            })
        logger.info("Discovered %d OAK-D device(s)", len(results))
        return results

    # ------------------------------------------------------------------
    # Live camera loop
    # ------------------------------------------------------------------

    def _build_pipeline(self) -> Any:
        """Construct the depthai pipeline graph."""
        cfg = self.config
        pipeline = dai.Pipeline()

        # ── RGB camera ────────────────────────────────────────────
        cam_rgb = pipeline.create(dai.node.ColorCamera)
        cam_rgb.setPreviewSize(*cfg.preview_size)
        cam_rgb.setResolution(
            _RGB_RESOLUTION_MAP.get(cfg.resolution_rgb, _RGB_RESOLUTION_MAP["1080p"])
        )
        cam_rgb.setInterleaved(False)
        cam_rgb.setFps(cfg.fps)

        # ── Mono cameras for stereo depth ─────────────────────────
        mono_left = pipeline.create(dai.node.MonoCamera)
        mono_left.setResolution(dai.MonoCameraProperties.SensorResolution.THE_400_P)
        mono_left.setCamera("left")
        mono_left.setFps(cfg.fps)

        mono_right = pipeline.create(dai.node.MonoCamera)
        mono_right.setResolution(dai.MonoCameraProperties.SensorResolution.THE_400_P)
        mono_right.setCamera("right")
        mono_right.setFps(cfg.fps)

        # ── Stereo depth ──────────────────────────────────────────
        stereo = pipeline.create(dai.node.StereoDepth)
        stereo.setDefaultProfilePreset(
            _DEPTH_PRESET_MAP.get(cfg.depth_preset, _DEPTH_PRESET_MAP["HIGH_ACCURACY"])
        )
        stereo.setLeftRightCheck(cfg.lr_check)
        stereo.setExtendedDisparity(cfg.extended_disparity)
        stereo.setSubpixel(cfg.subpixel)
        mono_left.out.link(stereo.left)
        mono_right.out.link(stereo.right)

        # ── Neural network ────────────────────────────────────────
        nn = pipeline.create(dai.node.MobileNetDetectionNetwork)
        nn.setConfidenceThreshold(cfg.confidence_threshold)
        nn.setBlobPath(
            str(blobconverter.from_zoo(cfg.nn_model, shaves=cfg.nn_shaves))
        )
        cam_rgb.preview.link(nn.input)

        # ── XLink outputs ─────────────────────────────────────────
        xout_rgb = pipeline.create(dai.node.XLinkOut)
        xout_rgb.setStreamName("rgb")
        cam_rgb.video.link(xout_rgb.input)

        xout_depth = pipeline.create(dai.node.XLinkOut)
        xout_depth.setStreamName("depth")
        stereo.depth.link(xout_depth.input)

        xout_nn = pipeline.create(dai.node.XLinkOut)
        xout_nn.setStreamName("nn")
        nn.out.link(xout_nn.input)

        return pipeline

    def _connect(self) -> bool:
        """Open a connection to the physical device. Returns True on success."""
        try:
            pipeline = self._build_pipeline()
            if self.device_id:
                self._device = dai.Device(pipeline, dai.DeviceInfo(self.device_id))
            else:
                self._device = dai.Device(pipeline)
            self._connected = True
            logger.info("Connected to OAK-D (id=%s)", self.device_id or "auto")
            return True
        except Exception:
            logger.exception("Failed to connect to OAK-D")
            self._connected = False
            return False

    def _disconnect(self) -> None:
        if self._device is not None:
            try:
                self._device.close()
            except Exception:
                pass
            self._device = None
        self._connected = False

    def _live_loop(self) -> None:
        """Acquisition loop for a real OAK-D camera with auto-reconnect."""
        while self._running:
            # (Re)connect
            if not self._connected:
                if not self._connect():
                    logger.info(
                        "Retrying in %.1fs...", self.config.reconnect_interval_s
                    )
                    time.sleep(self.config.reconnect_interval_s)
                    continue

            try:
                q_rgb = self._device.getOutputQueue("rgb", maxSize=4, blocking=False)
                q_depth = self._device.getOutputQueue("depth", maxSize=4, blocking=False)
                q_nn = self._device.getOutputQueue("nn", maxSize=4, blocking=False)

                while self._running and self._connected:
                    t0 = time.time()

                    in_rgb = q_rgb.tryGet()
                    in_depth = q_depth.tryGet()
                    in_nn = q_nn.tryGet()

                    if in_rgb is None:
                        time.sleep(0.001)
                        continue

                    rgb_frame = in_rgb.getCvFrame()

                    depth_frame = None
                    if in_depth is not None:
                        # Raw disparity -> metres
                        raw = in_depth.getFrame().astype(np.float32)
                        # Convert disparity to depth; clamp to configured range
                        depth_frame = np.clip(raw / 1000.0, self.config.min_depth_m, self.config.max_depth_m)

                    detections: list[Detection] = []
                    if in_nn is not None:
                        for det in in_nn.detections:
                            label_idx = det.label
                            label_str = (
                                MOBILENET_LABELS[label_idx]
                                if label_idx < len(MOBILENET_LABELS)
                                else str(label_idx)
                            )
                            detections.append(
                                Detection(
                                    label=label_str,
                                    confidence=det.confidence,
                                    x_min=det.xmin,
                                    y_min=det.ymin,
                                    x_max=det.xmax,
                                    y_max=det.ymax,
                                )
                            )

                    with self._lock:
                        self._rgb = rgb_frame
                        self._depth = depth_frame
                        self._detections = detections
                        self._last_frame_time = time.time()
                        self._frame_count += 1

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
                detections.append(
                    Detection(
                        label=obj["label"],
                        confidence=obj["confidence"],
                        x_min=max(0.0, (obj["cx"] - obj["radius"]) / 640),
                        y_min=max(0.0, (obj["cy"] - obj["radius"]) / 480),
                        x_max=min(1.0, (obj["cx"] + obj["radius"]) / 640),
                        y_max=min(1.0, (obj["cy"] + obj["radius"]) / 480),
                    )
                )

            with self._lock:
                self._rgb = rgb
                self._depth = depth
                self._detections = detections
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
