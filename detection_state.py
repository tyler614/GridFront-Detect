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
    """Thread-safe read of the current detection state."""
    with _lock:
        return _state.copy()


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


def update_camera_health(camera_id, fps, latency_ms):
    """Update a camera's health metrics."""
    with _camera_lock:
        if camera_id not in _camera_health:
            register_camera(camera_id)
        _camera_health[camera_id].update({
            "connected": True,
            "fps": round(fps, 1),
            "latency_ms": round(latency_ms, 1),
            "last_seen": time.time(),
        })


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
