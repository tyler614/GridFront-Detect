"""Script node code that runs on the OAK-D's Movidius VPU.

This file is *not* imported by the host — it gets read as a string and
attached to a `dai.node.Script` via `setScript()` in `build_standalone.py`.
The Movidius runtime is a stripped-down MicroPython-ish environment:

  * Standard library is mostly NOT available — `json`, `math`, `socket`,
    `time`, `struct` are. `os`, `threading`, `logging`, etc. are not.
  * No `import` of project modules — anything you need must live in this
    file (or be inlined at build time).
  * UDP via `socket.socket(socket.AF_INET, socket.SOCK_DGRAM)` works in
    DepthAI v3+ standalone mode; the camera's Ethernet stack hands the
    packet off to whatever upstream switch/router is configured.
  * Logs go via `node.warn()` / `node.error()` — print() is silent.

VALIDATION TODO before trusting in production:
  1. Verify SpatialDetectionNetwork output is reachable from a Script
     node in standalone mode (we know it works in host mode).
  2. Verify socket.sendto() actually transmits with no host attached.
  3. Decide how config (zones, target IP) gets in: baked at build time
     (current approach) vs read from a flash-resident JSON blob.
"""

# The following block is the literal source attached to the Script node.
# Keep it string-importable so build_standalone.py can hand it to setScript().

SCRIPT_SOURCE = r"""
import json
import math
import socket
import time

# ── Config baked at build time ────────────────────────────────────────
# These are placeholders rewritten by build_standalone.py before flash.
DEST_IP        = "__DEST_IP__"
DEST_PORT      = __DEST_PORT__
DANGER_M       = __DANGER_M__
WARNING_M      = __WARNING_M__
HALF_LENGTH_M  = __HALF_LENGTH_M__
HALF_WIDTH_M   = __HALF_WIDTH_M__
LABELS         = __LABELS_JSON__   # list[str], indexed by detection.label
UNITS          = "__UNITS__"       # "m" or "ft"

# COCO indices we treat as safety-relevant. Mirror of _SAFETY_LABELS in
# oak_driver.py — kept in sync at build time, not at runtime, since we
# can't import the host code from the VPU. Stored as list (not set) —
# MyriadX's stripped Python runtime may not expose set().
SAFETY_INDICES = __SAFETY_INDICES_JSON__   # list[int]

# ── State ─────────────────────────────────────────────────────────────
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
next_track_id = 1     # standalone mode has no real tracker yet — see TODO

def classify(x_m, z_m):
    # Distance from machine bounding-box edge, not centre. Matches
    # ZoneClassifier.classify in pipeline/zone_classifier.py.
    nx = max(-HALF_WIDTH_M, min(HALF_WIDTH_M, x_m))
    nz = max(-HALF_LENGTH_M, min(HALF_LENGTH_M, z_m))
    dx = x_m - nx
    dz = z_m - nz
    edge = math.sqrt(dx * dx + dz * dz)
    if edge <= DANGER_M:
        return "DANGER", edge
    if edge <= WARNING_M:
        return "WARNING", edge
    return "CLEAR", edge

while True:
    # Block on the upstream SpatialDetectionNetwork. The input port is
    # wired up in build_standalone.py via nn.out.link(script.inputs["nn"]).
    msg = node.io["nn"].get()
    if msg is None:
        continue

    detections = []
    danger_count = 0
    warning_count = 0
    clear_count = 0
    closest = None

    for d in msg.detections:
        if d.label not in SAFETY_INDICES:
            continue
        x_m = float(d.spatialCoordinates.x) / 1000.0
        z_m = float(d.spatialCoordinates.z) / 1000.0
        zone, edge = classify(x_m, z_m)
        # Standalone has no WorldTracker — assign a transient ID per
        # frame so the cab display has something stable-looking to key
        # off. Real fusion/tracking moves into the OAK firmware later.
        # No `global` — we're at module scope, not inside a function.
        tid = next_track_id
        next_track_id = (next_track_id + 1) & 0x7fffffff
        detections.append({
            "track_id":   tid,
            "x_m":        round(x_m, 2),
            "z_m":        round(z_m, 2),
            "distance_m": round(edge, 2),
            "zone":       zone,
        })
        if zone == "DANGER":   danger_count  += 1
        elif zone == "WARNING": warning_count += 1
        else:                   clear_count   += 1
        if closest is None or edge < closest:
            closest = edge

    payload = {
        "detections": detections,
        "summary": {
            "danger_count":  danger_count,
            "warning_count": warning_count,
            "clear_count":   clear_count,
            "closest_m":     None if closest is None else round(closest, 2),
        },
        "units": UNITS,
        "link":  "ok",
        "ts":    time.time(),
    }
    try:
        sock.sendto(json.dumps(payload).encode("utf-8"), (DEST_IP, DEST_PORT))
    except Exception as e:
        node.warn("sendto failed: " + str(e))
"""
