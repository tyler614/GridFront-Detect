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
CAMERA_ID   = "__CAMERA_ID__"       # GridFront serial (last-6 of OAK MXID), user-facing id
CAMERA_MXID = "__CAMERA_MXID__"     # full OAK MXID — INTERNAL/logging only, never surfaced
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
INIT_PITCH_DEG = __INIT_PITCH_DEG__    # downward camera tilt about its X axis (deg)
INIT_ZONES     = __INIT_ZONES_JSON__   # [{"color","r"}, ...] — r is meters from machine edge
INIT_MACHINE_LEN = __INIT_MACHINE_LEN_M__  # machine length along Y axis (m)
INIT_MACHINE_WID = __INIT_MACHINE_WID_M__  # machine width along X axis (m)
INIT_TARGET_FPS = __INIT_TARGET_FPS__  # network send rate cap; tablet may override

CONFIG_REQUEST_INTERVAL = 30.0

# Effective person confidence. The NN node is baked with a LOW catch floor
# (0.30 in build_standalone_v2.py); THIS is the real operating threshold, and
# it is RUNTIME-TUNABLE: the display pushes "min_confidence" over :5557 and
# apply_config() updates it live, no reflash. Held in state[] (not a bare
# global) so inner functions can mutate it in-place, same as pose/yaw.
INIT_CONF_THRESHOLD = 0.55

# ── State (dict so inner functions can mutate without `global`) ──────
state = {
    "pos_x":         INIT_POS_X,
    "pos_y":         INIT_POS_Y,
    "yaw_rad":       INIT_YAW_DEG * math.pi / 180.0,
    # Camera de-tilt: downward pitch about the camera X axis, applied in
    # cam_to_machine BEFORE yaw so a tilted mast cam maps depth onto true
    # ground-plane forward distance. Runtime-tunable via :5557 "pitch_deg".
    "pitch_rad":     INIT_PITCH_DEG * math.pi / 180.0,
    "conf_thresh":   INIT_CONF_THRESHOLD,
    # Per-track EMA smoothing of machine-frame (x_m, y_m) to stop the radar
    # dot jittering frame-to-frame. pos_ema maps track_id -> last smoothed
    # (x, y); it is pruned every frame to the tracks present so it stays
    # bounded for the VM lifetime. pos_alpha is the EMA factor: lower =
    # smoother + laggier, higher = more responsive. 0.4 ≈ 0.25s time-constant
    # at ~10fps. Runtime-tunable via :5557 "position_smoothing"/"smoothing".
    "pos_ema":       {},
    "pos_alpha":     0.4,
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
        # MUST send from cfg_sock (bound :5557), NOT tx_sock: the P4 replies to the
        # request's SOURCE port, and only cfg_sock is read by poll_config(). Sending
        # from tx_sock's ephemeral port means every reply lands unread and live config
        # (pose/zones/pitch/fov) never applies — the camera silently keeps baked values.
        cfg_sock.sendto(msg.encode("utf-8"), (DEST_IP, CONFIG_PORT))
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
            # pitch_deg is the camera's downward tilt; de-tilt happens in
            # cam_to_machine. Accepted at runtime in the same pose block.
            if "pitch_deg" in pose and pose["pitch_deg"] is not None:
                try:
                    state["pitch_rad"] = float(pose["pitch_deg"]) * math.pi / 180.0
                except Exception:
                    pass
        # Runtime-tunable person confidence (the display's live knob). Accept
        # either "min_confidence" or "confidence", clamp to a sane [0.10,0.95]
        # window, and update the effective threshold the tracklet loop filters
        # on. This is the on-camera analogue of the deferred v3 NN push: we
        # don't retune the NN node, we raise/lower the SCRIPT-side gate, so it
        # works with no Script->NN XLink and no reflash.
        conf_in = None
        if "min_confidence" in doc and doc["min_confidence"] is not None:
            conf_in = doc["min_confidence"]
        elif "confidence" in doc and doc["confidence"] is not None:
            conf_in = doc["confidence"]
        if conf_in is not None:
            try:
                cv = float(conf_in)
                if cv >= 0.10 and cv <= 0.95:
                    state["conf_thresh"] = cv
                    node.warn("conf_thresh updated -> " + str(cv))
                else:
                    node.warn("conf ignored (out of [0.10,0.95]): " + str(cv))
            except Exception:
                node.warn("conf ignored (non-numeric): " + str(conf_in))
        # Runtime-tunable per-track position EMA factor (the display's live
        # smoothing knob). Accept either "position_smoothing" or "smoothing",
        # clamp to a sane [0.05,1.0] window, and update state["pos_alpha"] the
        # detection loop smooths on. Same pattern as min_confidence above —
        # works with no reflash.
        smooth_in = None
        if "position_smoothing" in doc and doc["position_smoothing"] is not None:
            smooth_in = doc["position_smoothing"]
        elif "smoothing" in doc and doc["smoothing"] is not None:
            smooth_in = doc["smoothing"]
        if smooth_in is not None:
            try:
                sv = float(smooth_in)
                if sv >= 0.05 and sv <= 1.0:
                    state["pos_alpha"] = sv
                    node.warn("pos_alpha updated -> " + str(sv))
                else:
                    node.warn("smoothing ignored (out of [0.05,1.0]): " + str(sv))
            except Exception:
                node.warn("smoothing ignored (non-numeric): " + str(smooth_in))
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
        # NOTE: "confidence" is now applied SCRIPT-SIDE above (state["conf_thresh"],
        # the tracklet-loop gate) — a true live knob with no reflash and no
        # Script->NN XLink. The NN node itself keeps its baked 0.30 catch floor;
        # we only ever raise the gate ABOVE that floor, so the display can push
        # min_confidence anywhere in [0.10,0.95] live. `model_id` can still never
        # be a hot push (the .blob is baked) — that stays a reflash-lane concern
        # in build_standalone_v2.py via firmware_intent.
        state["last_cfg_rx"] = time.time()
        node.warn("config applied: rev=" + str(state["cfg_revision"])
                  + " zones=" + str(len(state["zones"]))
                  + " pos=(" + str(state["pos_x"]) + "," + str(state["pos_y"]) + ")"
                  + " yaw_deg=" + str(state["yaw_rad"] * 180.0 / math.pi)
                  + " pitch_deg=" + str(state["pitch_rad"] * 180.0 / math.pi)
                  + " conf=" + str(state["conf_thresh"])
                  + " smooth=" + str(state["pos_alpha"])
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

def cam_to_machine(x_c, y_c, z_c):
    # Camera OPTICAL frame: x_c = right, y_c = DOWN, z_c = forward, origin at
    # lens. Machine frame: X = right, Y = forward, origin at machine centre.
    # Yaw = 0 ⇒ camera forward aligned with machine +Y.
    #
    # STEP 1 — PITCH de-tilt (about the camera X axis), applied BEFORE yaw.
    # A mast cam tilted DOWN by p degrees sees the ground's far distance
    # foreshortened in z_c; rotating (z,y) back up by p recovers the true
    # ground-plane forward distance. Because +y is DOWN, a downward tilt
    # brings the floor's far distance back up via the +y*sin(p) term:
    #     ground_forward = z_c*cos(p) + y_c*sin(p)
    # No-op when pitch_rad == 0 (default / level bench), so the existing
    # yaw+translate path is untouched on a level mount.
    # SIGN CAVEAT: this sign (downward pitch = positive p, +y*sin(p)) MUST be
    # confirmed with a tape-measure test on a real tilted mount before trust —
    # the bench is level so this branch is currently INACTIVE and unverified.
    p = state["pitch_rad"]
    if p != 0.0:
        cp = math.cos(p)
        sp = math.sin(p)
        z_fwd = z_c * cp + y_c * sp
    else:
        z_fwd = z_c
    # STEP 2 — YAW rotation + translate (unchanged), now on the de-tilted
    # forward distance.
    c = math.cos(state["yaw_rad"])
    s = math.sin(state["yaw_rad"])
    dx =  x_c * c + z_fwd * s
    dy = -x_c * s + z_fwd * c
    return state["pos_x"] + dx, state["pos_y"] + dy

# Boot: announce ourselves so the tablet pushes current config.
# One-time traceability line: the user-facing GridFront serial plus the full
# OAK MXID (the latter is internal/logging only — never the wire id).
node.warn("boot camera_id=" + CAMERA_ID + " mxid=" + CAMERA_MXID)
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
    # Track ids seen THIS frame, used to prune state["pos_ema"] after the loop
    # so the smoothing cache stays bounded. No set() type in this VM, so a
    # dict-as-set: keys are the live track ids. Built every frame (incl. 0
    # detections) so the prune below always runs and never leaks stale tracks.
    current_tids = {}

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

        # Runtime confidence gate (the display's live knob, state["conf_thresh"],
        # default 0.55). The tracklet's source NN detection carries the raw
        # confidence (t.srcImgDetection.confidence in DepthAI 2.x). Skip any
        # detection below the gate BEFORE it is counted or added to the payload,
        # so a lower NN floor (0.30, baked) can be raised live without a reflash.
        conf = 0.0
        try:
            conf = float(t.srcImgDetection.confidence)
        except Exception:
            conf = 0.0
        if conf < state["conf_thresh"]:
            continue

        sc = t.spatialCoordinates
        x_c = float(sc.x) / 1000.0
        y_c = float(sc.y) / 1000.0
        z_c = float(sc.z) / 1000.0
        mx, my = cam_to_machine(x_c, y_c, z_c)
        # Per-track EMA on the machine-frame position to de-jitter the radar
        # dot. Smooth ONCE here, before classify(), so the dot AND its zone
        # colour are computed from the same smoothed point (no double-apply).
        # distance_m below stays RAW (camera-frame range) for closest/zone bar.
        tid = t.id
        current_tids[tid] = True
        a = state["pos_alpha"]
        prev = state["pos_ema"].get(tid)
        if prev is not None:
            mx = a * mx + (1.0 - a) * prev[0]
            my = a * my + (1.0 - a) * prev[1]
        state["pos_ema"][tid] = (mx, my)
        z_code, z_name, z_id = classify(mx, my)
        # Range from camera (for closest_m / UI bar) — machine-frame dist
        # is less useful when multiple cameras have different origins.
        cam_dist = math.sqrt(x_c * x_c + z_c * z_c)

        label_name = "obj"
        if 0 <= t.label and t.label < len(LABELS):
            label_name = LABELS[t.label]

        detections.append({
            "track_id":   tid,
            "label":      label_name,
            "x_m":        round(mx, 2),
            "y_m":        round(my, 2),
            "distance_m": round(cam_dist, 2),
            "confidence": round(conf, 2),
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

    # Prune the smoothing cache to the tracks seen THIS frame so it stays
    # bounded over the VM lifetime. Runs every frame — including 0-detection
    # frames (current_tids empty ⇒ cache emptied), and BEFORE the rate-cap
    # `continue` below so a throttled frame still drops departed tracks.
    new_ema = {}
    for k in state["pos_ema"]:
        if k in current_tids:
            new_ema[k] = state["pos_ema"][k]
    state["pos_ema"] = new_ema

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
