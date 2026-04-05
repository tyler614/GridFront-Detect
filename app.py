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


# ── Page Routes ──────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("detect.html")


@app.route("/radar")
def radar_page():
    return render_template("radar.html")


@app.route("/cameras")
def cameras_page():
    return render_template("cameras.html")


@app.route("/settings")
def settings_page():
    return render_template("settings.html")


@app.route("/alerts")
def alerts_page():
    return render_template("alerts.html")


@app.route("/dashboard")
def dashboard_page():
    return render_template("dashboard.html")


@app.route("/machines")
def machines_page():
    return render_template("machines.html")


# ── Spatial API ──────────────────────────────────────────────

@app.route("/api/spatial")
def get_spatial():
    return jsonify(get_state())


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
            time.sleep(0.1)  # 10Hz max
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
    active_id = config.get("active_model", "yolov10n-coco")
    models = list_models()
    for m in models:
        m["active"] = m["id"] == active_id
    return jsonify({"models": models, "active_model": active_id})


@app.route("/api/models/active", methods=["POST"])
def set_active_model():
    """Switch the active detection model. Requires pipeline restart."""
    data = request.json
    model_id = data.get("model_id") if data else None
    if not model_id or model_id not in MODELS:
        return jsonify({"error": f"Unknown model: {model_id}"}), 400
    config = load_config()
    config["active_model"] = model_id
    save_config(config)
    # Pipeline restart would happen here in production
    return jsonify({"status": "ok", "active_model": model_id, "restart_required": True})


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

    # Downsample — target ~40000 points for dense screen coverage
    total_pixels = h * w
    target_points = 40000
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
    points = np.round(points, 3).tolist()

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

    # Discover cameras on the network
    from pipeline.oak_driver import OakDriver
    devices = OakDriver.discover()

    # Build device_ids mapping: cam-{mount_id} -> IP or MX ID
    # First try broadcast discovery, then fall back to config IPs
    device_ids = {}
    if devices:
        print(f"  Found {len(devices)} OAK-D camera(s) via broadcast:")
        for d in devices:
            print(f"    {d['name']} ({d['mx_id']}) — {d['state']}")
        from machine_profiles import get_machine_profile as _gmp
        profile = _gmp(machine_type)
        mounts = profile["camera_mounts"] if profile else []
        for i, d in enumerate(devices):
            if i < len(mounts):
                cam_id = f"cam-{mounts[i]['id']}"
                device_ids[cam_id] = d["name"]
                print(f"    -> Assigned to {cam_id} ({mounts[i]['label']})")
    if not device_ids:
        # PoE broadcast discovery is unreliable; check config for known IPs
        cam_configs = config.get("cameras", [])
        poe_entries = [(c.get("mount", f"{i}"), c["ip"])
                       for i, c in enumerate(cam_configs) if c.get("ip")]
        if poe_entries:
            print(f"  Using {len(poe_entries)} camera IP(s) from config.json:")
            for mount_id, ip in poe_entries:
                cam_id = f"cam-{mount_id}"
                device_ids[cam_id] = ip
                print(f"    {cam_id} -> {ip}")
        else:
            print("  No cameras found — pipeline will retry on connect.")

    from pipeline.pipeline_runner import PipelineRunner
    active_model = config.get("active_model", "yolov10n-coco")
    print(f"  Active model: {active_model}")
    _pipeline_runner = PipelineRunner(
        machine_type=machine_type,
        mock=False,
        zone_override=config.get("zones"),
        device_ids=device_ids,
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
