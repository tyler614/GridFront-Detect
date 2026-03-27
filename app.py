"""
GridFront Safety Display — Tablet Server
Serves the kiosk radar app for the Oukitel RT3 Pro tablet.
Connects to the camera detection pipeline and relays to GridFront platform.
"""

from flask import Flask, jsonify, render_template, request, send_from_directory
import threading
import time
import json
import math
import random
import os

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "templates"),
    static_folder=os.path.join(os.path.dirname(__file__), "static"),
)

# ── Shared state ──────────────────────────────────────────────
_state = {
    "detections": [],
    "summary": {"danger_count": 0, "warning_count": 0, "clear_count": 0, "closest_m": None, "cameras_active": 0},
    "timestamp": None,
    "fps": 0,
}
_lock = threading.Lock()

# ── Camera configuration (persisted to config.json) ──────────
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
DEFAULT_CONFIG = {
    "machine_name": "Machine 1",
    "cameras": [],
    "zones": {"danger_m": 3.0, "warning_m": 7.0, "max_range_m": 10.0},
    "connectivity": {"mode": "wifi", "wifi_ssid": "", "wifi_password": "", "apn": ""},
    "alerts": {"sound_enabled": True, "danger_sound": "alarm", "warning_sound": "chime"},
    "display": {"theme": "dark", "brightness": 80},
    "platform": {"url": "https://platform.gridfront.io", "api_key": "", "tenant_id": ""},
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


# ── API Routes ────────────────────────────────────────────────

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


@app.route("/api/spatial")
def get_spatial():
    with _lock:
        return jsonify(_state)


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


# ── Demo mode ─────────────────────────────────────────────────

def run_demo_data():
    """Generate simulated detection data for testing."""
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

        update_state(dets, fps=15.0)
        time.sleep(0.1)


if __name__ == "__main__":
    print("[GridFront Safety Display] Starting in DEMO mode")
    demo = threading.Thread(target=run_demo_data, daemon=True)
    demo.start()
    app.run(host="0.0.0.0", port=5555, debug=False)
