"""
GridFront Safety Display — Tablet Server
Serves the kiosk radar app for the Oukitel RT3 Pro tablet.
Connects to the camera detection pipeline and relays to GridFront platform.
"""

from flask import Flask, jsonify, render_template, request, send_from_directory, Response
import threading
import time
import json
import math
import random
import os

from detection_state import (
    update_state, get_state, get_camera_status, get_all_camera_health,
    register_camera, update_camera_health, get_uptime,
)
from machine_profiles import get_machine_profile, get_all_profiles, get_detection_classes

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "templates"),
    static_folder=os.path.join(os.path.dirname(__file__), "static"),
)

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


# ── System Health API ────────────────────────────────────────

@app.route("/api/system/health")
def system_health():
    """Overall system health check."""
    config = load_config()
    state = get_state()
    all_health = get_all_camera_health()

    total_cameras = len(config.get("cameras", []))
    connected_cameras = sum(1 for h in all_health.values() if h.get("connected"))

    return jsonify({
        "status": "ok",
        "active_machine": config.get("machine_type", "wheel_loader"),
        "cameras": {"total": total_cameras, "connected": connected_cameras},
        "detection": {"active": state["timestamp"] is not None, "fps": state["fps"]},
        "uptime_s": round(get_uptime(), 1),
    })


# ── Demo mode ─────────────────────────────────────────────────

def run_demo_data():
    """Generate simulated detection data for testing."""
    # Register demo cameras
    for cam_id in ["cam-0", "cam-1"]:
        register_camera(cam_id)

    angle = 0
    while True:
        angle += 0.05
        distance = 3.5 + 2.0 * math.sin(angle * 0.3)
        x = distance * math.sin(angle)
        z = distance * math.cos(angle)
        zone = "DANGER" if distance < 3 else ("WARNING" if distance < 7 else "CLEAR")

        dets = [{
            "track_id": 1, "label": "person", "confidence": 0.92,
            "x_m": round(x, 2), "y_m": 0, "z_m": round(z, 2),
            "distance_m": round(distance, 2),
            "bearing_deg": round(math.degrees(math.atan2(x, z)), 1),
            "zone": zone, "camera_id": "cam-0",
        }]

        # Update demo camera health
        update_camera_health("cam-0", fps=15.0, latency_ms=12.5)

        if random.random() > 0.7:
            d2 = random.uniform(2, 8)
            a2 = random.uniform(0, math.pi * 2)
            z2 = "DANGER" if d2 < 3 else ("WARNING" if d2 < 7 else "CLEAR")
            dets.append({
                "track_id": 2, "label": "person", "confidence": 0.78,
                "x_m": round(d2 * math.sin(a2), 2), "y_m": 0,
                "z_m": round(d2 * math.cos(a2), 2),
                "distance_m": round(d2, 2),
                "bearing_deg": round(math.degrees(a2), 1),
                "zone": z2, "camera_id": "cam-1",
            })
            update_camera_health("cam-1", fps=14.8, latency_ms=13.1)

        update_state(dets, fps=15.0)
        time.sleep(0.1)


if __name__ == "__main__":
    print("[GridFront Safety Display] Starting in DEMO mode")
    demo = threading.Thread(target=run_demo_data, daemon=True)
    demo.start()
    app.run(host="0.0.0.0", port=5555, debug=False)
