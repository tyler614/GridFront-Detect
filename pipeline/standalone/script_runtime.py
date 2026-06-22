"""Script node code that runs on the OAK-D's Movidius VPU (Leon CSS).

This file is *not* imported by the host — it gets read as a string and
attached to a `dai.node.Script` via `setScript()` in `build_standalone_v2.py`.
The Movidius runtime is a stripped-down MicroPython-ish environment:

  * Stdlib is mostly NOT available — `json`, `math`, `socket`, `time`,
    `struct` are. `os`, `threading`, `logging`, etc. are not.
  * No `set()` type. No `global` at module scope — use a dict we mutate.
  * UDP via `socket.socket(socket.AF_INET, socket.SOCK_DGRAM)` works only
    when the Script node runs on LEON_CSS (the network stack lives there,
    not on LEON_MSS). build_standalone_v2 pins this.
  * Logs go via `node.warn()` / `node.error()` — print() is silent.

Architecture:
  * OAK does all spatial detection, frame transform, and zone classification.
  * Per-detection UDP payload carries machine-frame (x_m, y_m) + zone colour.
  * A second UDP socket listens on CONFIG_PORT for pushes from the tablet;
    on boot (and every 30s thereafter) the camera sends a config_request so
    the tablet re-serves current zones/pose even if the tablet rebooted.

Trust model (ARCHITECTURE §4.3 / §5.1, review defect C-2):
  * The OAK is the safety sensor but cannot do crypto — the Script-node VM
    has no `hashlib`/`hmac` and only `json/math/socket/time`. So it CANNOT
    verify the Ed25519 envelope the cloud signs. The verify anchor is the
    P4/hub (it owns NVS, has a real CPU, and re-serves over :5557).
  * Therefore the OAK trusts the P4/hub as the LAN config authority and its
    config integrity rests on (a) LAN isolation — Z3 has no route to WAN/AP,
    firewall-enforced — and (b) a SOURCE-IP ALLOWLIST here: :5557 config is
    accepted ONLY from the allowlisted P4/hub source, every other datagram
    is dropped. This stops a rogue camera / on-segment injector (T-8/T-12)
    and forces an attacker to spoof the P4's address on a static-ARP segment.
  * A monotonic config-revision gate rejects stale / out-of-order config
    (replay / rollback within the window) so a re-sent older doc cannot
    shrink the danger zone after a newer one applied (T-2 at the camera).
  * Full per-frame crypto is deliberately NOT done at the OAK (D7); signing
    is enforced upstream at the P4. The allowlist + isolation are the OAK's
    enforcement. A future v3 may add a true Ed25519 path if the VM gains it.
"""

SCRIPT_SOURCE = r"""
import json
import math
import socket
import time

# ── Config baked at build time ────────────────────────────────────────
DEST_IP     = "__DEST_IP__"          # tablet IP
DEST_PORT   = __DEST_PORT__          # tablet detections port (5556)
CONFIG_PORT = __CONFIG_PORT__        # bidirectional config port (5557)
CAMERA_ID   = "__CAMERA_ID__"
# Source-IP allowlist for inbound :5557 config (review C-2). Only the P4/hub
# LAN authority may rewrite our pose/zones/footprint/fps. "" disables the
# check (NOT recommended — only for a single-host bench loopback). Baked to
# DEST_IP by default since the P4 we send detections to is the same node that
# serves config back over :5557.
CONFIG_SRC_IP = "__CONFIG_SRC_IP__"
LABELS      = __LABELS_JSON__        # list[str], indexed by d.label
SAFETY_INDICES = __SAFETY_INDICES_JSON__   # list[int]
UNITS       = "__UNITS__"

# Initial pose + zones — baked as fallback for the first frames before
# the tablet answers our config_request. Tablet will overwrite via push.
INIT_POS_X     = __INIT_POS_X__        # machine-frame X of camera mount (m)
INIT_POS_Y     = __INIT_POS_Y__        # machine-frame Y of camera mount (m)
INIT_YAW_DEG   = __INIT_YAW_DEG__      # rotation about machine vertical axis
INIT_ZONES     = __INIT_ZONES_JSON__   # [{"color","r"}, ...] — r is meters from machine edge
INIT_MACHINE_LEN = __INIT_MACHINE_LEN_M__  # machine length along Y axis (m)
INIT_MACHINE_WID = __INIT_MACHINE_WID_M__  # machine width along X axis (m)
INIT_TARGET_FPS = __INIT_TARGET_FPS__  # network send rate cap; tablet may override

CONFIG_REQUEST_INTERVAL = 30.0

# ── State (dict so inner functions can mutate without `global`) ──────
state = {
    "pos_x":         INIT_POS_X,
    "pos_y":         INIT_POS_Y,
    "yaw_rad":       INIT_YAW_DEG * math.pi / 180.0,
    "zones":         INIT_ZONES,
    "half_len":      INIT_MACHINE_LEN / 2.0,
    "half_wid":      INIT_MACHINE_WID / 2.0,
    "target_fps":    float(INIT_TARGET_FPS) if INIT_TARGET_FPS > 0 else 0.0,
    "last_cfg_req":  0.0,
    "last_cfg_rx":   0.0,
    "last_send":     0.0,
    # Monotonic config revision (review C-2): the highest config_version we
    # have applied. Persisted across messages (in-RAM for the VM lifetime;
    # the P4 holds the rollback-resistant NVS copy). A pushed config is
    # applied only if its version is strictly greater, so a replayed/stale
    # older doc on the segment is rejected. -1 = nothing applied yet, so the
    # first legitimate push (and the baked fallback) is always accepted.
    "cfg_revision":  -1,
}

ZONE_NONE = 0
ZONE_OUTSIDE = 1
ZONE_YELLOW = 2
ZONE_RED = 3

def zone_name(raw):
    v = str(raw or "").lower()
    if v == "danger" or v == "red":
        return "red"
    if v == "warning" or v == "yellow":
        return "yellow"
    if v == "clear" or v == "outside" or v == "none":
        return "outside"
    return "yellow"

def zone_code(name):
    n = zone_name(name)
    if n == "red":
        return ZONE_RED
    if n == "yellow":
        return ZONE_YELLOW
    return ZONE_OUTSIDE

def zone_name_from_code(code):
    if code == ZONE_RED:
        return "red"
    if code == ZONE_YELLOW:
        return "yellow"
    if code == ZONE_NONE:
        return "none"
    return "outside"

tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
cfg_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
cfg_sock.bind(("", CONFIG_PORT))
cfg_sock.setblocking(False)

def send_config_request():
    try:
        msg = json.dumps({"type": "config_request", "camera_id": CAMERA_ID})
        tx_sock.sendto(msg.encode("utf-8"), (DEST_IP, CONFIG_PORT))
    except Exception as e:
        node.warn("cfg request failed: " + str(e))

def doc_revision(doc):
    # Pull the monotonic config version off a pushed doc. The cloud envelope
    # calls it "config_version" (ARCHITECTURE §5.1); "revision" is the P4 NVS
    # name; "config_revision" is accepted for belt-and-suspenders. Returns an
    # int, or None when the doc carries no version (legacy/local push).
    for key in ("config_version", "revision", "config_revision"):
        if key in doc and doc[key] is not None:
            try:
                return int(doc[key])
            except Exception:
                return None
    return None

def apply_config(doc):
    try:
        # ── Monotonic revision gate (review C-2: anti-replay/rollback) ────
        # Apply only if this doc's version is strictly newer than the last
        # one we applied. A re-sent or out-of-order older doc (e.g. an
        # attacker replaying a "danger zone = 0" push captured earlier, or a
        # P4 that re-serves a stale generation) is dropped. Docs with NO
        # version are still honoured (the P4's local config_request answer
        # and the boot fallback may be unversioned) but they do NOT advance
        # the counter, so they can never roll a real version backwards.
        rev = doc_revision(doc)
        if rev is not None:
            if rev <= state["cfg_revision"]:
                node.warn("config rejected: stale revision " + str(rev)
                          + " <= applied " + str(state["cfg_revision"]))
                return
            state["cfg_revision"] = rev
        if "pose" in doc and doc["pose"] is not None:
            pose = doc["pose"]
            if "x_m" in pose:      state["pos_x"]   = float(pose["x_m"])
            if "y_m" in pose:      state["pos_y"]   = float(pose["y_m"])
            if "yaw_deg" in pose:  state["yaw_rad"] = float(pose["yaw_deg"]) * math.pi / 180.0
        if "zones" in doc and doc["zones"] is not None:
            # r_m is now interpreted as "distance from machine edge", not
            # circle radius around an origin. cx_m/cy_m are accepted for
            # wire-format compat but ignored — the zone shape is derived
            # from the machine rectangle.
            new_zones = []
            for z in doc["zones"]:
                z_name = zone_name(z.get("label", z.get("zone", z.get("color", "yellow"))))
                try:
                    z_code = int(z.get("severity_code", z.get("zone_code", zone_code(z_name))))
                except Exception:
                    z_code = zone_code(z_name)
                if z_code < ZONE_OUTSIDE: z_code = ZONE_OUTSIDE
                if z_code > ZONE_RED: z_code = ZONE_RED
                new_zones.append({
                    "id":    str(z.get("id", "")),
                    "zone":  zone_name_from_code(z_code),
                    "code":  z_code,
                    "r":     float(z.get("r_m", z.get("r", 0.0))),
                })
            state["zones"] = new_zones
        if "machine_footprint_m" in doc and doc["machine_footprint_m"] is not None:
            mf = doc["machine_footprint_m"]
            try:
                state["half_len"] = float(mf.get("length", 0.0)) / 2.0
                state["half_wid"] = float(mf.get("width",  0.0)) / 2.0
            except Exception:
                pass
        if "target_fps" in doc and doc["target_fps"] is not None:
            try:
                tf = float(doc["target_fps"])
                if tf < 0: tf = 0.0
                if tf > 60: tf = 60.0
                state["target_fps"] = tf
            except Exception:
                pass
        # TODO(v3 live-confidence push — NOT implemented, deliberately
        # deferred): a desired `perception.confidence` / `model_id` is a
        # REFLASH-LANE concern today (handled by build_standalone_v2.py via
        # firmware_intent), NOT a hot push. To make confidence live without a
        # reflash, the pipeline (build_standalone_v2.py) must route a
        # dai.NeuralNetwork/SpatialDetectionNetwork runtime-config message
        # from this Script node back into the NN node (a Script->NN XLink the
        # pipeline does not wire today), and this apply_config would then gain
        # a `perception.confidence` branch that pushes setConfidenceThreshold
        # at runtime. model_id can never be a hot push (the .blob is baked).
        # Until that pipeline path exists, confidence/model changes here are
        # intentionally ignored on the wire.
        state["last_cfg_rx"] = time.time()
        node.warn("config applied: rev=" + str(state["cfg_revision"])
                  + " zones=" + str(len(state["zones"]))
                  + " pos=(" + str(state["pos_x"]) + "," + str(state["pos_y"]) + ")"
                  + " yaw_deg=" + str(state["yaw_rad"] * 180.0 / math.pi)
                  + " fps=" + str(state["target_fps"]))
    except Exception as e:
        node.warn("apply_config failed: " + str(e))

def poll_config():
    drained = 0
    while drained < 16:
        try:
            data, addr = cfg_sock.recvfrom(8192)
        except Exception:
            return
        drained = drained + 1
        # ── Source-IP allowlist (review C-2) ────────────────────────────
        # addr is (ip, port). Accept config ONLY from the allowlisted P4/hub
        # authority; silently drop anything else (a rogue camera or any
        # other on-segment host cannot rewrite our safety config). The signed
        # envelope is verified upstream at the P4 — this allowlist + LAN
        # isolation are the OAK's enforcement. An empty CONFIG_SRC_IP
        # disables the check (bench loopback only).
        if CONFIG_SRC_IP:
            src_ip = ""
            try:
                src_ip = addr[0]
            except Exception:
                src_ip = ""
            if src_ip != CONFIG_SRC_IP:
                node.warn("config dropped: src " + str(src_ip)
                          + " not allowlisted (expect " + CONFIG_SRC_IP + ")")
                continue
        try:
            apply_config(json.loads(data.decode("utf-8")))
        except Exception as e:
            node.warn("cfg parse failed: " + str(e))

def classify(mx, my):
    # Distance from point (mx, my) to the nearest edge of the machine
    # rectangle (centred at origin, axis-aligned, half-extents in state).
    # Inside the rectangle, distance is 0. Outside, it's the L2 distance
    # to the closest edge — which makes the contour {p : dist(p)=r} a
    # rounded rectangle (Minkowski sum of the rect and a disc of radius r).
    ax = mx
    if ax < 0: ax = -ax
    ay = my
    if ay < 0: ay = -ay
    dx = ax - state["half_wid"]
    dy = ay - state["half_len"]
    if dx < 0: dx = 0.0
    if dy < 0: dy = 0.0
    edge_dist = math.sqrt(dx * dx + dy * dy)

    # Larger zone codes are more urgent: outside=1, yellow=2, red=3.
    best_code = ZONE_OUTSIDE
    best_id = ""
    for z in state["zones"]:
        if edge_dist <= z["r"]:
            try:
                z_code = int(z.get("code", z.get("severity_code",
                             zone_code(z.get("zone", z.get("label", z.get("color", "yellow")))))))
            except Exception:
                z_code = zone_code(z.get("zone", z.get("label", z.get("color", "yellow"))))
            if z_code > best_code:
                best_code = z_code
                best_id = z.get("id", "")
    return best_code, zone_name_from_code(best_code), best_id

def cam_to_machine(x_c, z_c):
    # Camera frame: x_c = right, z_c = forward, origin at lens.
    # Machine frame: X = right, Y = forward, origin at machine centre.
    # Yaw = 0 ⇒ camera forward aligned with machine +Y.
    c = math.cos(state["yaw_rad"])
    s = math.sin(state["yaw_rad"])
    dx =  x_c * c + z_c * s
    dy = -x_c * s + z_c * c
    return state["pos_x"] + dx, state["pos_y"] + dy

# Boot: announce ourselves so the tablet pushes current config.
send_config_request()
state["last_cfg_req"] = time.time()

# Diagnostic: heartbeat counters surfaced via node.warn so the host
# log stream can prove the script is actually iterating.
state["dbg_loops"] = 0
state["dbg_msgs"] = 0
state["dbg_last_log"] = 0.0

while True:
    poll_config()
    now = time.time()
    if now - state["last_cfg_req"] >= CONFIG_REQUEST_INTERVAL:
        send_config_request()
        state["last_cfg_req"] = now

    state["dbg_loops"] = state["dbg_loops"] + 1
    if now - state["dbg_last_log"] >= 2.0:
        node.warn("tick loops=" + str(state["dbg_loops"])
                  + " msgs=" + str(state["dbg_msgs"]))
        state["dbg_last_log"] = now

    msg = node.io["nn"].get()
    if msg is None:
        continue
    state["dbg_msgs"] = state["dbg_msgs"] + 1
    if state["dbg_msgs"] <= 3:
        try:
            tcount = len(msg.tracklets)
            node.warn("first-msg tracklets=" + str(tcount))
        except Exception as e:
            node.warn("msg.tracklets failed: " + str(e))

    # msg is dai.Tracklets — list of Tracklet, each with stable .id assigned
    # by the OAK ObjectTracker. status: 0=NEW, 1=TRACKED, 2=LOST, 3=REMOVED.
    # We surface NEW+TRACKED only so the UI dot disappears when the person
    # actually leaves the frame instead of lingering on a LOST track.
    tracklets = msg.tracklets

    detections = []
    red_count = 0
    yellow_count = 0
    outside_count = 0
    closest = None
    raw_count = 0

    for t in tracklets:
        if t.status == 2 or t.status == 3:
            continue
        raw_count = raw_count + 1

        # Explicit loop instead of `t.label not in SAFETY_INDICES`:
        # MicroPython's `in` on a list has quirks vs CPython, and we
        # already lost a flash iteration to a silent mismatch here.
        is_safe = False
        for si in SAFETY_INDICES:
            if t.label == si:
                is_safe = True
                break
        if not is_safe:
            continue
        sc = t.spatialCoordinates
        x_c = float(sc.x) / 1000.0
        z_c = float(sc.z) / 1000.0
        mx, my = cam_to_machine(x_c, z_c)
        z_code, z_name, z_id = classify(mx, my)
        # Range from camera (for closest_m / UI bar) — machine-frame dist
        # is less useful when multiple cameras have different origins.
        cam_dist = math.sqrt(x_c * x_c + z_c * z_c)

        label_name = "obj"
        if 0 <= t.label and t.label < len(LABELS):
            label_name = LABELS[t.label]

        detections.append({
            "track_id":   t.id,
            "label":      label_name,
            "x_m":        round(mx, 2),
            "y_m":        round(my, 2),
            "distance_m": round(cam_dist, 2),
            "zone_code":   z_code,
            "zone":        z_name,
            "zone_id":     z_id,
        })
        if z_code == ZONE_RED:
            red_count = red_count + 1
        elif z_code == ZONE_YELLOW:
            yellow_count = yellow_count + 1
        else:
            outside_count = outside_count + 1
        if closest is None or cam_dist < closest:
            closest = cam_dist

    # Network send rate cap. Inference still runs at the camera's full
    # rate (locked at flash time) so danger/warning classification stays
    # responsive locally; only the UDP payload to the tablet is throttled.
    # target_fps == 0 means "uncapped" — emit every frame.
    tf = state["target_fps"]
    if tf > 0:
        min_interval = 1.0 / tf
        if (now - state["last_send"]) < min_interval:
            continue
    state["last_send"] = now

    if len(detections) == 0:
        scene_state_code = ZONE_NONE
    elif red_count > 0:
        scene_state_code = ZONE_RED
    elif yellow_count > 0:
        scene_state_code = ZONE_YELLOW
    else:
        scene_state_code = ZONE_OUTSIDE

    payload = {
        "schema_version": 1,
        "type":      "detections",
        "camera_id": CAMERA_ID,
        "scene_state_code": scene_state_code,
        "scene_state": zone_name_from_code(scene_state_code),
        "detections": detections,
        "summary": {
            "detection_count": len(detections),
            "outside_count": outside_count,
            "yellow_count": yellow_count,
            "red_count": red_count,
            "highest_zone_code": scene_state_code,
            "closest_m":     None if closest is None else round(closest, 2),
            "raw_count":     raw_count,
        },
        "units": UNITS,
        "link":  "ok",
        "ts":    now,
    }
    try:
        tx_sock.sendto(json.dumps(payload).encode("utf-8"), (DEST_IP, DEST_PORT))
    except Exception as e:
        node.warn("sendto failed: " + str(e))
"""
