"""
GridFront Safety Display — Tablet Server
Serves the kiosk radar app for the Oukitel RT3 Pro tablet.
Connects to the camera detection pipeline and relays to GridFront platform.
"""

from flask import Flask, jsonify, render_template, request, send_from_directory, Response
import argparse
import logging
import time
import json
import os
import numpy as np

from detection_state import (
    get_state, get_camera_status, get_all_camera_health, get_uptime,
    get_coverage_sectors,
)
from machine_profiles import get_machine_profile, get_all_profiles, get_detection_classes
from pipeline.model_registry import list_models, get_model, MODELS

logger = logging.getLogger(__name__)

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "templates"),
    static_folder=os.path.join(os.path.dirname(__file__), "static"),
)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True

# Global reference to the live pipeline (set in main when --live is used)
_pipeline_runner = None

# ── Camera configuration (persisted to config.json) ──────────
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
DEFAULT_CONFIG = {
    "machine_name": "Machine 1",
    "machine_type": "wheel_loader",
    "cameras": [],
    "installed_cameras": [],
    "zones": {"danger_m": 3.0, "warning_m": 7.0, "max_range_m": 10.0},
    "connectivity": {"mode": "wifi", "wifi_ssid": "", "wifi_password": "", "apn": ""},
    "alerts": {"sound_enabled": True, "danger_sound": "alarm", "warning_sound": "chime"},
    "display": {"theme": "dark", "brightness": 80},
    "platform": {"url": "https://platform.gridfront.io", "api_key": "", "tenant_id": ""},
    "detection_config": {},
}


def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            saved = json.load(f)
            # Merge with defaults for any new keys
            merged = {**DEFAULT_CONFIG, **saved}
            return merged
    return DEFAULT_CONFIG.copy()


def save_config(config):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def resolve_installed_cameras(config):
    """Return the installed_cameras list for the current config.

    If config already has an ``installed_cameras`` entry, use it as-is.
    Otherwise, synthesise a list from the legacy ``cameras`` array by
    pairing each entry's IP with the matching mount in the active machine
    profile (by ``mount`` key, falling back to position in the list).
    Returns [] when nothing can be resolved.
    """
    installed = config.get("installed_cameras") or []
    if installed:
        return [dict(c) for c in installed]

    legacy = config.get("cameras") or []
    if not legacy:
        return []

    machine_type = config.get("machine_type", "wheel_loader")
    profile = get_machine_profile(machine_type)
    if profile is None:
        return []

    mounts_by_id = {m["id"]: m for m in profile.get("camera_mounts", [])}
    mounts_in_order = profile.get("camera_mounts", [])
    spec = profile.get("camera_spec", {})
    hfov = spec.get("hfov_deg", 127)
    max_range = profile.get("default_zones", {}).get("max_range_m", 12.0)

    out = []
    for i, cam in enumerate(legacy):
        ip = cam.get("ip")
        if not ip:
            continue
        mount_id = cam.get("mount")
        mount = mounts_by_id.get(mount_id)
        if mount is None and i < len(mounts_in_order):
            mount = mounts_in_order[i]
        if mount is None:
            continue
        rot = mount.get("rotation", [0, 0, 0])
        out.append({
            "id": cam.get("id") or f"cam-{mount['id']}",
            "label": cam.get("label") or mount.get("label", mount["id"]),
            "device_id": ip,
            "position_m": list(mount.get("position", [0, 0, 0])),
            "pitch_deg": rot[0] if len(rot) > 0 else 0,
            "yaw_deg":   rot[1] if len(rot) > 1 else 0,
            "roll_deg":  rot[2] if len(rot) > 2 else 0,
            "hfov_deg": hfov,
            "max_range_m": max_range,
        })
    return out


# ── Page Routes ──────────────────────────────────────────────

@app.route("/")
def index():
    # Single-page app: detect.html is the only view. Settings live in a
    # popup on this same page (see toggleSettings in detect.html). The old
    # /dashboard, /cameras, /alerts, /settings, /radar, /machines templates
    # were removed — everything they did is now either a popup section or
    # an API endpoint consumed directly by detect.html.
    return render_template("detect.html")


# ── Spatial API ──────────────────────────────────────────────

@app.route("/api/spatial")
def get_spatial():
    return jsonify(get_state())


@app.route("/api/coverage")
def get_coverage():
    """Return the current per-camera coverage sectors.

    Sectors describe the FOV wedge each installed camera contributes to
    the machine-world view, so the spatial view and cab display can render
    accurately which arcs around the machine are actually monitored.
    """
    sectors = get_coverage_sectors()
    if not sectors and _pipeline_runner is not None:
        sectors = _pipeline_runner.coverage_sectors
    return jsonify({"sectors": sectors, "count": len(sectors)})


@app.route("/api/spatial/stream")
def spatial_stream():
    """SSE endpoint for push-based detection updates."""
    def generate():
        last_ts = 0
        while True:
            state = get_state()
            if state["timestamp"] and state["timestamp"] != last_ts:
                last_ts = state["timestamp"]
                yield f"data: {json.dumps(state)}\n\n"
            time.sleep(1.0 / 30)  # 30Hz max — match pipeline rate
    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Config API ───────────────────────────────────────────────

@app.route("/api/config", methods=["GET"])
def get_config():
    return jsonify(load_config())


@app.route("/api/config", methods=["POST"])
def update_config():
    config = load_config()
    updates = request.json
    config.update(updates)
    save_config(config)
    return jsonify({"status": "ok", "config": config})


# ── Camera CRUD API ──────────────────────────────────────────

@app.route("/api/cameras", methods=["GET"])
def get_cameras():
    config = load_config()
    return jsonify(config.get("cameras", []))


@app.route("/api/cameras", methods=["POST"])
def add_camera():
    config = load_config()
    camera = request.json
    # Assign an ID
    camera["id"] = f"cam-{len(config['cameras'])}"
    if "status" not in camera:
        camera["status"] = "disconnected"
    config["cameras"].append(camera)
    save_config(config)
    return jsonify({"status": "ok", "camera": camera})


@app.route("/api/cameras/<camera_id>", methods=["PATCH"])
def update_camera(camera_id):
    config = load_config()
    for cam in config["cameras"]:
        if cam["id"] == camera_id:
            cam.update(request.json)
            save_config(config)
            return jsonify({"status": "ok", "camera": cam})
    return jsonify({"error": "Camera not found"}), 404


@app.route("/api/cameras/<camera_id>", methods=["DELETE"])
def delete_camera(camera_id):
    config = load_config()
    config["cameras"] = [c for c in config["cameras"] if c["id"] != camera_id]
    save_config(config)
    return jsonify({"status": "ok"})


@app.route("/api/cameras/<camera_id>/calibration_status", methods=["GET"])
def camera_calibration_status(camera_id):
    """Live calibration + stability telemetry for the Settings UI.

    Polled while the Calibrate button countdown is visible. Returns both
    the static reference state (calibrated_at, ref_quat) and the live
    stability window (samples, max_delta_deg) so the UI can show a
    real-time "Hold still… 2s… 1s… Locked ✓" indicator.
    """
    if _pipeline_runner is None:
        return jsonify({"error": "No pipeline running"}), 503
    status = _pipeline_runner.get_calibration_status(camera_id)
    return jsonify(status)


@app.route("/api/cameras/<camera_id>/calibrate", methods=["POST"])
def camera_calibrate(camera_id):
    """Snapshot the current IMU orientation as this camera's reference.

    This is a SAFETY-CRITICAL endpoint. It refuses to commit unless:

      * the driver is a real OAK-D (not mock),
      * IMU packets are arriving,
      * stability window shows the camera hasn't moved > 0.5° over 2s,
      * BNO085 reports a reasonable accuracy.

    On success, the reference quaternion + calibrated_at timestamp are
    both written to the live pipeline (so the bump watchdog picks them
    up immediately) AND persisted to config.json so they survive a
    server restart. A failed calibrate returns 400 with a human-readable
    reason that the Settings UI displays next to the button.
    """
    if _pipeline_runner is None:
        return jsonify({"ok": False, "error": "no_pipeline"}), 503

    result = _pipeline_runner.recalibrate_camera(camera_id)
    if not result.get("ok"):
        return jsonify(result), 400

    # Persist to config.json so a reboot doesn't forget the reference
    config = load_config()
    installed = config.get("installed_cameras") or []
    updated = False
    for cam in installed:
        if cam.get("id") == camera_id:
            cam["imu_ref_quat"] = result["imu_ref_quat"]
            cam["calibrated_at"] = result["calibrated_at"]
            if "bump_threshold_deg" not in cam:
                cam["bump_threshold_deg"] = 10.0
            updated = True
            break
    if not updated:
        # Config was migrated from legacy 'cameras' — rebuild and retry
        installed = resolve_installed_cameras(config)
        for cam in installed:
            if cam.get("id") == camera_id:
                cam["imu_ref_quat"] = result["imu_ref_quat"]
                cam["calibrated_at"] = result["calibrated_at"]
                cam["bump_threshold_deg"] = 10.0
                updated = True
                break
        if updated:
            config["installed_cameras"] = installed

    if updated:
        save_config(config)
    else:
        logger.warning(
            "Calibrated %s but could not find it in config.json — "
            "reference will be lost on restart", camera_id
        )

    return jsonify(result)


@app.route("/api/cameras/<camera_id>/status")
def camera_status(camera_id):
    """Get camera health (connected, fps, latency)."""
    status = get_camera_status(camera_id)
    if status is None:
        return jsonify({"error": "Camera not found or not tracked"}), 404
    return jsonify(status)


# ── Machine Profiles API ────────────────────────────────────

@app.route("/api/machines")
def list_machines():
    """List all machine profiles."""
    return jsonify(get_all_profiles())


@app.route("/api/machines/<machine_type>")
def get_machine(machine_type):
    """Get a specific machine profile."""
    profile = get_machine_profile(machine_type)
    if profile is None:
        return jsonify({"error": f"Unknown machine type: {machine_type}"}), 404
    return jsonify(profile)


@app.route("/api/machines/<machine_type>/activate", methods=["POST"])
def activate_machine(machine_type):
    """Set active machine type (saves to config)."""
    profile = get_machine_profile(machine_type)
    if profile is None:
        return jsonify({"error": f"Unknown machine type: {machine_type}"}), 400
    config = load_config()
    config["machine_type"] = machine_type
    config["zones"] = profile["default_zones"].copy()
    save_config(config)
    return jsonify({"status": "ok", "machine_type": machine_type, "zones": config["zones"]})


# ── Detection Config API ────────────────────────────────────

@app.route("/api/detection/config", methods=["GET"])
def get_detection_config():
    """Get detection class config (which classes to detect, priorities)."""
    config = load_config()
    saved = config.get("detection_config", {})
    # Merge defaults with any saved overrides
    classes = get_detection_classes()
    result = {}
    for cls_key, cls_def in classes.items():
        overrides = saved.get(cls_key, {})
        result[cls_key] = {
            "label": cls_def["label"],
            "icon": cls_def["icon"],
            "priority": overrides.get("priority", cls_def["default_priority"]),
            "enabled": overrides.get("enabled", True),
        }
    return jsonify(result)


@app.route("/api/detection/config", methods=["POST"])
def update_detection_config():
    """Update detection class config."""
    updates = request.json
    if not isinstance(updates, dict):
        return jsonify({"error": "Expected JSON object"}), 400
    config = load_config()
    if "detection_config" not in config:
        config["detection_config"] = {}
    config["detection_config"].update(updates)
    save_config(config)
    return jsonify({"status": "ok", "detection_config": config["detection_config"]})


# ── Model API ───────────────────────────────────────────────

@app.route("/api/models", methods=["GET"])
def get_models():
    """List all available detection models with their classes."""
    config = load_config()
    active_id = config.get("active_model", "yolov6n-coco")
    models = list_models()
    for m in models:
        m["active"] = m["id"] == active_id
    return jsonify({"models": models, "active_model": active_id})


@app.route("/api/models/active", methods=["POST"])
def set_active_model():
    """Switch the active detection model.

    Persists to config.json and, if a live pipeline is running, hot-swaps the
    model in a background thread. The response returns immediately; clients
    should poll /api/camera/status to watch the restart complete.
    """
    data = request.json
    model_id = data.get("model_id") if data else None
    if not model_id or model_id not in MODELS:
        return jsonify({"error": f"Unknown model: {model_id}"}), 400
    config = load_config()
    config["active_model"] = model_id
    save_config(config)

    if _pipeline_runner is not None:
        import threading as _threading
        def _do_restart():
            try:
                _pipeline_runner.restart_with_model(model_id)
            except Exception:
                logger.exception("Pipeline restart with model %s failed", model_id)
        _threading.Thread(
            target=_do_restart, daemon=True, name=f"model-swap-{model_id}"
        ).start()
        return jsonify({
            "status": "restarting",
            "active_model": model_id,
            "message": "Pipeline is restarting with the new model.",
        }), 202

    return jsonify({
        "status": "ok",
        "active_model": model_id,
        "restart_required": False,
        "message": "No live pipeline — model will be used on next server start.",
    })


# ── System Health API ────────────────────────────────────────

@app.route("/api/system/health")
def system_health():
    """Overall system health check."""
    config = load_config()
    state = get_state()
    all_health = get_all_camera_health()

    total_cameras = len(config.get("cameras", []))
    connected_cameras = sum(1 for h in all_health.values() if h.get("connected"))

    result = {
        "status": "ok",
        "active_machine": config.get("machine_type", "wheel_loader"),
        "cameras": {"total": total_cameras, "connected": connected_cameras},
        "detection": {"active": state["timestamp"] is not None, "fps": state["fps"]},
        "uptime_s": round(get_uptime(), 1),
    }

    # Include pipeline stats when running in live mode
    if _pipeline_runner is not None:
        result["pipeline"] = _pipeline_runner.stats

    return jsonify(result)


# ── Camera Discovery API ────────────────────────────────────

@app.route("/api/cameras/discover")
def discover_cameras():
    """Scan the network for OAK-D cameras."""
    from pipeline.oak_driver import OakDriver
    devices = OakDriver.discover()
    return jsonify({"devices": devices, "count": len(devices)})


# ── Pipeline Control API ────────────────────────────────────

@app.route("/api/pipeline/status")
def pipeline_status():
    """Get the current pipeline status."""
    if _pipeline_runner is None:
        return jsonify({"running": False, "mode": "demo"})
    return jsonify({**_pipeline_runner.stats, "mode": "live"})


@app.route("/api/imu")
def get_imu():
    """Get camera IMU orientation (pitch, roll, yaw + quaternion)."""
    if _pipeline_runner is None:
        return jsonify({"error": "No pipeline running"}), 503
    for cam_id, driver in _pipeline_runner._drivers.items():
        if not driver.mock:
            imu = driver.get_imu()
            if imu:
                return jsonify(imu)
    return jsonify({"error": "IMU not available"}), 204


@app.route("/api/ir", methods=["GET"])
def get_ir_status():
    """Get IR illumination status."""
    if _pipeline_runner is None:
        return jsonify({"error": "No pipeline running"}), 503
    result = {}
    for cam_id, driver in _pipeline_runner._drivers.items():
        if not driver.mock and driver._device is not None:
            result[cam_id] = {
                "ir_active": driver._ir_active,
                "ir_auto": driver.config.ir_auto,
                "ir_flood": driver.config.ir_flood_intensity,
                "ir_dot": driver.config.ir_dot_intensity,
            }
    return jsonify(result)


@app.route("/api/ir", methods=["POST"])
def set_ir():
    """Control IR illumination. Body: {flood: 0-1, dot: 0-1, auto: bool}"""
    data = request.json
    if _pipeline_runner is None:
        return jsonify({"error": "No pipeline running"}), 503
    for cam_id, driver in _pipeline_runner._drivers.items():
        if not driver.mock and driver._device is not None:
            if "flood" in data:
                val = float(data["flood"])
                driver._device.setIrFloodLightIntensity(val)
                driver.config.ir_flood_intensity = val
            if "dot" in data:
                val = float(data["dot"])
                driver._device.setIrLaserDotProjectorIntensity(val)
                driver.config.ir_dot_intensity = val
            if "auto" in data:
                driver.config.ir_auto = bool(data["auto"])
    return jsonify({"status": "ok"})


# ── Camera Video Feed (MJPEG) ─────────────────────────────────

@app.route("/api/camera/status")
def camera_status_overview():
    """High-level camera connection state for the livestream UI.

    Returns:
        {
          "state": "connected" | "connecting" | "restarting" | "error" | "no_camera",
          "model": "yolov6n-coco",
          "model_name": "YOLOv10 Nano (General)",
          "fps": 12.5,
          "last_frame_age_s": 0.04 or null,
          "message": "human-readable detail when not connected",
          "device_id": "169.254.1.222" or null
        }
    """
    config = load_config()
    active_model_id = config.get("active_model", "yolov6n-coco")
    model_def = MODELS.get(active_model_id)
    model_name = model_def.name if model_def else active_model_id

    # No pipeline at all
    if _pipeline_runner is None:
        return jsonify({
            "state": "no_camera",
            "model": active_model_id,
            "model_name": model_name,
            "fps": 0,
            "last_frame_age_s": None,
            "message": "No pipeline running on this server.",
            "device_id": None,
        })

    stats = _pipeline_runner.stats

    # Restart in progress
    if stats.get("restarting"):
        new_model_id = stats.get("active_model", active_model_id)
        new_model_def = MODELS.get(new_model_id)
        new_model_name = new_model_def.name if new_model_def else new_model_id
        return jsonify({
            "state": "restarting",
            "model": new_model_id,
            "model_name": new_model_name,
            "fps": 0,
            "last_frame_age_s": None,
            "message": f"Switching model to {new_model_name}…",
            "device_id": None,
        })

    cameras = stats.get("cameras", {})
    if not cameras:
        return jsonify({
            "state": "no_camera",
            "model": active_model_id,
            "model_name": model_name,
            "fps": 0,
            "last_frame_age_s": None,
            "message": "No cameras configured. Add one in Settings.",
            "device_id": None,
        })

    # Pick the most informative driver: prefer non-mock, then connected
    def _rank(h):
        return (not h.get("mock", False), h.get("connected", False))
    cam_id, health = max(cameras.items(), key=lambda kv: _rank(kv[1]))

    now = time.time()
    last_frame_age = None
    if health.get("last_frame_time"):
        last_frame_age = round(now - health["last_frame_time"], 2)

    device_id = health.get("device_id")

    if health.get("connected") and last_frame_age is not None and last_frame_age < 2.0:
        state = "connected"
        message = ""
    elif health.get("last_error"):
        state = "error"
        message = health["last_error"]
    elif not health.get("ever_connected"):
        state = "connecting"
        message = f"Connecting to camera {device_id or ''}…".strip()
    else:
        state = "connecting"
        message = "Reconnecting to camera…"

    return jsonify({
        "state": state,
        "model": health.get("model_id", active_model_id),
        "model_name": model_name,
        "fps": health.get("fps", 0),
        "last_frame_age_s": last_frame_age,
        "message": message,
        "device_id": device_id,
    })


@app.route("/api/camera/snapshot")
def camera_snapshot():
    """Return pre-encoded JPEG of the latest camera frame — near-zero server time."""
    if _pipeline_runner is not None:
        # Prefer real camera
        for cam_id, driver in _pipeline_runner._drivers.items():
            if not driver.mock:
                jpeg = driver.get_jpeg()
                if jpeg:
                    return Response(jpeg, mimetype='image/jpeg',
                                    headers={"Cache-Control": "no-store"})
        # Fall back to any driver
        for cam_id, driver in _pipeline_runner._drivers.items():
            jpeg = driver.get_jpeg()
            if jpeg:
                return Response(jpeg, mimetype='image/jpeg',
                                headers={"Cache-Control": "no-store"})

    # No frame available
    return Response(b'', status=204)


@app.route("/api/camera/depthimage")
def camera_depthimage():
    """Return depth map as a grayscale JPEG — pixel-perfect alignment with camera feed."""
    import cv2
    driver = None
    if _pipeline_runner is not None:
        for cam_id, d in _pipeline_runner._drivers.items():
            if not d.mock:
                driver = d
                break
        if driver is None:
            for cam_id, d in _pipeline_runner._drivers.items():
                driver = d
                break

    if driver is None:
        return Response(b'', status=204)

    frame = driver.get_frame()
    if frame is None or frame.get("depth") is None:
        return Response(b'', status=204)

    depth = frame["depth"]  # float32, metres
    # Normalize: 0.3m=white(255), 15m=dark(40), invalid=black(0)
    valid = depth > 0.3
    img = np.zeros(depth.shape, dtype=np.uint8)
    d_clamped = np.clip(depth[valid], 0.3, 15.0)
    # Invert: near=bright, far=dim
    img[valid] = (255 - ((d_clamped - 0.3) / 14.7 * 215)).astype(np.uint8)

    _, jpeg = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return Response(
        jpeg.tobytes(),
        mimetype="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@app.route("/api/camera/pointcloud")
def camera_pointcloud():
    """Return a downsampled 3D point cloud from the depth map plus detections."""
    driver = None
    if _pipeline_runner is not None:
        # Prefer non-mock driver
        for cam_id, d in _pipeline_runner._drivers.items():
            if not d.mock:
                driver = d
                break
        # Fall back to any driver
        if driver is None:
            for cam_id, d in _pipeline_runner._drivers.items():
                driver = d
                break

    if driver is None:
        return jsonify({"points": [], "detections": [], "timestamp": 0})

    frame = driver.get_frame()
    if frame is None or frame.get("depth") is None:
        return jsonify({"points": [], "detections": [], "timestamp": 0})

    depth = frame["depth"]  # float32, metres, shape (H, W)
    h, w = depth.shape

    # Pinhole intrinsics for OAK-D Pro W (150° DFOV wide lens)
    # f = diagonal_pixels / (2 * tan(DFOV/2))
    diag = np.sqrt(w**2 + h**2)
    fx = fy = diag / (2 * np.tan(np.radians(75)))  # 75° = 150°/2
    cx_cam, cy_cam = w / 2.0, h / 2.0

    # Downsample for live streaming
    total_pixels = h * w
    target_points = int(request.args.get('points', 50000))
    step = max(1, int(np.sqrt(total_pixels / target_points)))

    # Build coordinate grids for downsampled pixels
    vs = np.arange(0, h, step)
    us = np.arange(0, w, step)
    uu, vv = np.meshgrid(us, vs)
    uu = uu.ravel()
    vv = vv.ravel()

    d_vals = depth[vv, uu]

    # Filter out invalid depths (zero, too close, too far)
    valid = (d_vals > 0.3) & (d_vals < 15.0)
    uu = uu[valid]
    vv = vv[valid]
    d_vals = d_vals[valid]

    # Project to 3D: x=right, y=down, z=forward
    x_3d = (uu.astype(np.float32) - cx_cam) * d_vals / fx
    y_3d = (vv.astype(np.float32) - cy_cam) * d_vals / fy
    z_3d = d_vals

    # Stack and round for compact JSON
    points = np.stack([x_3d, y_3d, z_3d], axis=1)
    # Hard cap to target_points for performance
    if len(points) > target_points:
        idx = np.random.choice(len(points), target_points, replace=False)
        points = points[idx]
    # Binary format: return raw Float32Array (x,y,z triples) — ~360KB vs ~627KB JSON
    if request.args.get('format') == 'binary':
        points = np.round(points, 2).astype(np.float32)
        return Response(
            points.tobytes(),
            mimetype="application/octet-stream",
            headers={"Cache-Control": "no-store"},
        )

    points = np.round(points, 2).tolist()

    # Detections with 3D positions
    det_list = []
    for det in frame.get("detections", []):
        d = det.to_dict() if hasattr(det, "to_dict") else det
        det_list.append(d)

    result = {"points": points, "detections": det_list, "timestamp": frame.get("timestamp", 0)}

    return Response(
        json.dumps(result),
        mimetype="application/json",
        headers={"Cache-Control": "no-store"},
    )


@app.route("/api/camera/mesh")
def camera_mesh():
    """Return a triangle mesh built from the depth map as binary.

    The depth image is a grid — we connect neighboring pixels into triangles,
    skipping edges where depth changes drastically (object boundaries).

    Returns binary: [vertices (float32 x,y,z triples)] + [indices (uint32 triangle triples)]
    Header: first 8 bytes = vertex_count (uint32) + index_count (uint32)
    """
    import struct

    driver = None
    if _pipeline_runner is not None:
        for cam_id, d in _pipeline_runner._drivers.items():
            if not d.mock:
                driver = d
                break
        if driver is None:
            for cam_id, d in _pipeline_runner._drivers.items():
                driver = d
                break

    if driver is None:
        return Response(struct.pack('<II', 0, 0), mimetype="application/octet-stream")

    frame = driver.get_frame()
    if frame is None or frame.get("depth") is None:
        return Response(struct.pack('<II', 0, 0), mimetype="application/octet-stream")

    depth = frame["depth"]  # float32, metres, shape (H, W)
    h, w = depth.shape

    # Camera intrinsics — OAK-D Pro W 150° DFOV
    diag = np.sqrt(w**2 + h**2)
    fx = fy = diag / (2 * np.tan(np.radians(75)))
    cx_cam, cy_cam = w / 2.0, h / 2.0

    # Downsample grid — higher res = smoother mesh
    target_rows = int(request.args.get('rows', 160))
    target_cols = int(request.args.get('cols', 240))
    step_r = max(1, h // target_rows)
    step_c = max(1, w // target_cols)

    rows = np.arange(0, h, step_r)
    cols = np.arange(0, w, step_c)
    nr, nc = len(rows), len(cols)

    # Sample depth at grid points
    grid_v, grid_u = np.meshgrid(rows, cols, indexing='ij')  # (nr, nc)
    grid_depth = depth[grid_v, grid_u]  # (nr, nc)

    # Mark valid pixels
    valid = (grid_depth > 0.3) & (grid_depth < 15.0)

    # Project grid to 3D
    grid_x = (grid_u.astype(np.float32) - cx_cam) * grid_depth / fx
    grid_y = (grid_v.astype(np.float32) - cy_cam) * grid_depth / fy
    grid_z = grid_depth

    # Flatten to vertex array (nr*nc, 3)
    vertices = np.stack([grid_x.ravel(), grid_y.ravel(), grid_z.ravel()], axis=1)
    vertices = np.round(vertices, 2).astype(np.float32)

    # Build triangle indices — connect each 2x2 quad into 2 triangles
    # Skip triangles where any vertex is invalid or depth jump > threshold
    depth_threshold = 0.15  # metres — tight threshold for clean object silhouettes

    indices = []
    for r in range(nr - 1):
        for c in range(nc - 1):
            # Four corners of the quad
            i00 = r * nc + c
            i01 = r * nc + c + 1
            i10 = (r + 1) * nc + c
            i11 = (r + 1) * nc + c + 1

            # Check all four are valid
            if not (valid[r, c] and valid[r, c+1] and valid[r+1, c] and valid[r+1, c+1]):
                continue

            # Check depth continuity — skip object edges
            d00 = grid_depth[r, c]
            d01 = grid_depth[r, c+1]
            d10 = grid_depth[r+1, c]
            d11 = grid_depth[r+1, c+1]

            if (abs(d00 - d01) > depth_threshold or
                abs(d00 - d10) > depth_threshold or
                abs(d01 - d11) > depth_threshold or
                abs(d10 - d11) > depth_threshold):
                continue

            # Two triangles per quad
            indices.extend([i00, i10, i01])  # lower-left triangle
            indices.extend([i01, i10, i11])  # upper-right triangle

    indices = np.array(indices, dtype=np.uint32)
    num_verts = len(vertices)
    num_indices = len(indices)

    # Pack: header (8 bytes) + vertices + indices
    header = struct.pack('<II', num_verts, num_indices)
    body = header + vertices.tobytes() + indices.tobytes()

    return Response(
        body,
        mimetype="application/octet-stream",
        headers={"Cache-Control": "no-store"},
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GridFront Safety Display Server")
    parser.add_argument(
        "--machine", type=str, default=None,
        help="Machine type (e.g. wheel_loader, excavator). Overrides config.json.",
    )
    parser.add_argument(
        "--port", type=int, default=5555,
        help="Server port (default: 5555)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    config = load_config()
    machine_type = args.machine or config.get("machine_type", "wheel_loader")

    print(f"[GridFront Detect] Starting — machine: {machine_type}")

    # Resolve the physically-installed cameras. installed_cameras in
    # config.json is the source of truth; fall back to synthesising from
    # the legacy `cameras` array so older configs keep working.
    installed_cameras = resolve_installed_cameras(config)

    # Optional: if broadcast discovery finds extra OAK-Ds not listed in
    # config, just log them — installers should add them via Settings.
    from pipeline.oak_driver import OakDriver
    devices = OakDriver.discover()
    if devices:
        print(f"  Found {len(devices)} OAK-D camera(s) via broadcast:")
        for d in devices:
            print(f"    {d['name']} ({d['mx_id']}) — {d['state']}")

    if installed_cameras:
        print(f"  Installed cameras ({len(installed_cameras)}):")
        for cam in installed_cameras:
            print(
                f"    {cam['id']} '{cam['label']}' @ "
                f"pos={cam['position_m']} yaw={cam.get('yaw_deg', 0)}° "
                f"hfov={cam.get('hfov_deg', 127)}° -> {cam.get('device_id')}"
            )
    else:
        print("  No installed_cameras configured — add one via Settings.")

    from pipeline.pipeline_runner import PipelineRunner
    active_model = config.get("active_model", "yolov6n-coco")
    print(f"  Active model: {active_model}")
    _pipeline_runner = PipelineRunner(
        machine_type=machine_type,
        mock=False,
        zone_override=config.get("zones"),
        installed_cameras=installed_cameras,
        active_model_id=active_model,
    )
    _pipeline_runner.start()

    # Ensure clean shutdown releases OAK-D XLink on exit
    import signal
    import atexit

    def _shutdown(*args):
        print("\n[GridFront Detect] Shutting down — releasing camera...")
        if _pipeline_runner is not None:
            _pipeline_runner.stop()
        print("[GridFront Detect] Camera released. Goodbye.")
        raise SystemExit(0)

    atexit.register(lambda: _pipeline_runner.stop() if _pipeline_runner else None)
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    app.run(host="0.0.0.0", port=args.port, debug=False, threaded=True)
