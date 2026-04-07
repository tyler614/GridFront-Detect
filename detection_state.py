"""
GridFront Detect — Shared Detection State
Thread-safe state management for detections and camera health.
"""

import threading
import time

# ── Detection state ──────────────────────────────────────────
_state = {
    "detections": [],
    "summary": {"danger_count": 0, "warning_count": 0, "clear_count": 0, "closest_m": None, "cameras_active": 0},
    "timestamp": None,
    "fps": 0,
}
_lock = threading.Lock()

# ── Coverage sectors (static per pipeline run — updated on start/restart) ──
# List of {id, label, position_m:[x,y,z], yaw_deg, hfov_deg, range_m,
#          start_deg, end_deg}. Angle convention: 0°=front(+Z), 90°=right(+X),
# 180°=rear(-Z), -90°=left(-X).
_coverage_sectors: list = []
_coverage_lock = threading.Lock()

# ── Per-camera calibration state (bump watchdog) ──
# Keyed by camera id. Each value:
#   {state: 'uncalibrated'|'nominal'|'warn'|'bumped'|'imu_lost',
#    delta_deg: float,        # current angular delta from reference
#    threshold_deg: float,    # red line — above this we fail loud
#    calibrated_at: iso8601 | None,
#    imu_accuracy_rad: float | None}
#
# This is the load-bearing safety signal: the cab display reads it to
# decide whether to trust each camera's zone. NEVER silently omit a
# bumped camera from this dict — missing = uncalibrated = red.
_camera_calibration: dict = {}
_calibration_lock = threading.Lock()

# ── Camera health tracking ───────────────────────────────────
_camera_health = {}
_camera_lock = threading.Lock()

# ── Startup time (for uptime calculation) ────────────────────
_start_time = time.time()


def update_state(detections, fps=0):
    """Called by detection pipeline to push new data."""
    global _state
    with _lock:
        det_dicts = [d.to_dict() if hasattr(d, "to_dict") else d for d in detections]
        danger = [d for d in det_dicts if d.get("zone") == "DANGER"]
        warning = [d for d in det_dicts if d.get("zone") == "WARNING"]
        distances = [d.get("distance_m", 999) for d in det_dicts]
        _state = {
            "detections": det_dicts,
            "summary": {
                "danger_count": len(danger),
                "warning_count": len(warning),
                "clear_count": len(det_dicts) - len(danger) - len(warning),
                "closest_m": min(distances) if distances else None,
                "cameras_active": len(set(d.get("camera_id", "") for d in det_dicts)),
            },
            "timestamp": time.time(),
            "fps": round(fps, 1),
        }


def get_state():
    """Thread-safe read of the current detection state.

    Includes ``coverage`` — the list of camera coverage sectors — and
    ``cameras_calibration`` — per-camera bump-watchdog status — so SSE
    clients receive both automatically and react to pipeline restarts
    or a bumped camera without polling a second endpoint.

    Also includes a top-level ``safety_state``:
      * ``nominal`` — all cameras calibrated and within threshold
      * ``bumped`` — at least one camera is flagged bumped or imu_lost;
                     cab display MUST show a full-screen red alarm
      * ``uncalibrated`` — at least one camera has never been calibrated
    """
    with _lock:
        snapshot = _state.copy()
    with _coverage_lock:
        snapshot["coverage"] = list(_coverage_sectors)
    with _calibration_lock:
        cal = {k: dict(v) for k, v in _camera_calibration.items()}
    snapshot["cameras_calibration"] = cal
    # Embed per-camera health (fps, nn_fps, latency) into every SSE
    # frame so the UI can show real camera + NN throughput without a
    # second polling loop.
    with _camera_lock:
        snapshot["cameras"] = {
            cid: dict(h) for cid, h in _camera_health.items()
        }

    if not cal:
        snapshot["safety_state"] = "nominal"
        snapshot["bumped_cameras"] = []
        return snapshot

    bumped = [cid for cid, c in cal.items() if c.get("state") in ("bumped", "imu_lost")]
    uncal = [cid for cid, c in cal.items() if c.get("state") == "uncalibrated"]
    if bumped:
        snapshot["safety_state"] = "bumped"
    elif uncal:
        snapshot["safety_state"] = "uncalibrated"
    else:
        snapshot["safety_state"] = "nominal"
    snapshot["bumped_cameras"] = bumped
    return snapshot


def set_coverage_sectors(sectors):
    """Replace the current coverage sectors. Called by PipelineRunner on
    start/restart whenever installed_cameras changes."""
    global _coverage_sectors
    with _coverage_lock:
        _coverage_sectors = list(sectors)


def get_coverage_sectors():
    """Return the current coverage sectors list."""
    with _coverage_lock:
        return list(_coverage_sectors)


def set_camera_calibration(camera_id: str, entry: dict) -> None:
    """Update the calibration/bump status for a single camera.

    ``entry`` should include at least ``state``. Other fields (delta_deg,
    threshold_deg, calibrated_at, imu_accuracy_rad) are copied as-is.
    Called from the pipeline's bump watchdog each frame.
    """
    with _calibration_lock:
        _camera_calibration[camera_id] = dict(entry)


def get_camera_calibration(camera_id: str) -> dict | None:
    """Return current calibration state for a camera (None if unknown)."""
    with _calibration_lock:
        entry = _camera_calibration.get(camera_id)
        return dict(entry) if entry else None


def get_all_camera_calibration() -> dict:
    """Return a snapshot of every camera's calibration state."""
    with _calibration_lock:
        return {k: dict(v) for k, v in _camera_calibration.items()}


def clear_camera_calibration(camera_id: str | None = None) -> None:
    """Remove calibration state for one camera, or all of them."""
    with _calibration_lock:
        if camera_id is None:
            _camera_calibration.clear()
        else:
            _camera_calibration.pop(camera_id, None)


def register_camera(camera_id):
    """Register a camera for health tracking."""
    with _camera_lock:
        if camera_id not in _camera_health:
            _camera_health[camera_id] = {
                "camera_id": camera_id,
                "connected": False,
                "fps": 0,
                "latency_ms": 0,
                "last_seen": None,
            }


def update_camera_health(camera_id, fps, latency_ms, nn_fps=None):
    """Update a camera's health metrics.

    ``fps`` is the RGB delivery rate (camera/encoder throughput).
    ``nn_fps`` is the decoupled NN inference throughput — optional so
    mock drivers and older call sites keep working.
    """
    with _camera_lock:
        if camera_id not in _camera_health:
            _camera_health[camera_id] = {
                "camera_id": camera_id,
                "connected": False,
                "fps": 0,
                "nn_fps": 0,
                "latency_ms": 0,
                "last_seen": None,
            }
        payload = {
            "connected": True,
            "fps": round(fps, 1),
            "latency_ms": round(latency_ms, 1),
            "last_seen": time.time(),
        }
        if nn_fps is not None:
            payload["nn_fps"] = round(nn_fps, 1)
        _camera_health[camera_id].update(payload)


def get_camera_status(camera_id):
    """Return health info for a specific camera, or None if not tracked."""
    with _camera_lock:
        health = _camera_health.get(camera_id)
        if health is None:
            return None
        info = health.copy()
        # Mark as disconnected if no update in 5 seconds
        if info["last_seen"] and (time.time() - info["last_seen"]) > 5.0:
            info["connected"] = False
        return info


def get_all_camera_health():
    """Return health info for all tracked cameras."""
    with _camera_lock:
        now = time.time()
        result = {}
        for cam_id, health in _camera_health.items():
            info = health.copy()
            if info["last_seen"] and (now - info["last_seen"]) > 5.0:
                info["connected"] = False
            result[cam_id] = info
        return result


def get_uptime():
    """Return seconds since module was loaded."""
    return time.time() - _start_time
