"""Standalone pipeline bake, DepthAI 2.x edition.

Why 2.x: DepthAI 3.x Python bindings have a broken pybind conversion for
std::vector<unsigned char>, which blocks every Python flash path
(flash(), createDAP+flashDAP). 2.29.0 works and uses a local YOLO .blob
instead of a HubAI slug, so the pipeline can be built offline with no
pre-flash device session.

Architecture (v2 zone-based):
  * The camera owns zone classification. Host reads config.json and bakes
    the initial pose + zones as a fallback for first boot.
  * At runtime the tablet pushes config to the camera on UDP :5557, and
    the camera re-requests config every 30s so edits are never stale.
  * Detections carry machine-frame (x_m, y_m) + pre-classified zone.

Usage (from detect.gridfront.io root, with the 2.x venv active):

    .venv2x/Scripts/python.exe -m pipeline.standalone.build_standalone_v2 \\
        --camera-id cam-0 --dest-ip 169.254.1.56 --confirm-flash
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from pathlib import Path

import depthai as dai

from pipeline.standalone.script_runtime import SCRIPT_SOURCE

logger = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parents[2]
DEFAULT_BLOB = REPO / "models" / "gridfront-scout-v1.blob"
DEFAULT_MODEL_JSON = REPO / "models" / "gridfront-scout-v1.json"
DEFAULT_CONFIG = REPO / "config.json"
# Agent-synced firmware intent (E3 reflash lane). The cloud's desired
# perception (model_id/confidence) is a REFLASH-LANE concern — confidence +
# model are baked into the .blob/.dap at flash time, NOT hot-pushed over
# :5557 (ARCHITECTURE §2.4 / §7.3). The sync-agent mirrors the cloud's
# desired into this file (the build-host analogue of the tablet's
# `pending_model`), and this build host consumes it to drive the reflash.
# After a successful flash the realised state is recorded back as the
# `active` block, exactly mirroring the tablet's pending_model→active_model
# lifecycle (android/.../LocalAssetServer.kt, ConfigStore.kt).
DEFAULT_FIRMWARE_INTENT = REPO / "firmware_intent.json"

_SAFETY_LABEL_NAMES = {
    # gridfront-scout-v1 (construction-site classes)
    "person", "excavator", "wheel-loader", "dozer",
    "crane", "dump-truck", "grader", "compactor",
    # COCO fallback (stock yolov6nr1 for general detection)
    "bicycle", "car", "motorcycle", "bus", "truck",
}


def _safety_indices(labels: list[str], override: set[str] | None = None) -> list[int]:
    allow = override if override else _SAFETY_LABEL_NAMES
    return sorted(i for i, name in enumerate(labels) if name in allow)


def _extract_pose_and_zones(cfg: dict, camera_id: str) -> tuple[float, float, float, list[dict], float, float]:
    """Pull initial pose, zones, and machine footprint out of config.json.

    Returns (pos_x_m, pos_y_m, yaw_deg, zones, machine_len_m, machine_wid_m).
    Zone shape is [{"id", "zone", "severity_code", "r"}] where r is
    distance from the machine edge — the OAK's classify() does point-to-
    rectangle distance using (machine_len, machine_wid) as the rectangle.
    """
    pos_x = 0.0
    pos_y = 0.0
    yaw_deg = 0.0
    for cam in cfg.get("installed_cameras", []):
        if cam.get("id") == camera_id:
            pos = cam.get("position_m") or [0.0, 0.0, 0.0]
            # position_m is [lateral, height, forward] (matches machine_profiles
            # mount conventions and the host-side SpatialFusion). The on-OAK
            # script's machine frame is 2D top-down, so we feed it lateral +
            # forward — height is not used for zone classification.
            if len(pos) >= 3:
                pos_x = float(pos[0])
                pos_y = float(pos[2])
            elif len(pos) >= 2:
                pos_x = float(pos[0])
                pos_y = float(pos[1])
            yaw_deg = float(cam.get("yaw_deg", 0.0))
            break

    fp = cfg.get("machine_footprint_m") or {}
    machine_len = float(fp.get("length", 8.0))
    machine_wid = float(fp.get("width",  2.5))

    zones: list[dict] = []
    raw = cfg.get("zones") or []
    if isinstance(raw, dict):
        danger = raw.get("danger_m")
        warning = raw.get("warning_m")
        if isinstance(danger, (int, float)):
            zones.append({"id": "red-inner", "zone": "red", "severity_code": 3, "r": float(danger)})
        if isinstance(warning, (int, float)):
            zones.append({"id": "yellow-outer", "zone": "yellow", "severity_code": 2, "r": float(warning)})
    elif isinstance(raw, list):
        for z in raw:
            if not isinstance(z, dict):
                continue
            r = z.get("r_m")
            if not isinstance(r, (int, float)):
                continue
            label = str(z.get("label", z.get("zone", z.get("color", "yellow")))).lower()
            if label == "danger":
                label = "red"
            elif label == "warning":
                label = "yellow"
            elif label == "clear":
                label = "outside"
            code = int(z.get("severity_code", z.get("zone_code",
                       3 if label == "red" else 2 if label == "yellow" else 1)))
            zones.append({"id": str(z.get("id", "")),
                          "zone": label,
                          "severity_code": code,
                          "r": float(r)})

    return pos_x, pos_y, yaw_deg, zones, machine_len, machine_wid


def _load_firmware_intent(path: Path) -> dict:
    """Read the agent-synced firmware_intent (E3 reflash lane).

    The file mirrors the tablet's pending_model/active_model split. Shape::

        {
          "desired": { "model_id": "gridfront-scout-v1", "confidence": 0.45 },
          "active":  { "model_id": "yolov6n-coco",       "confidence": 0.30,
                       "flashed_at": "2026-06-22T..Z" }
        }

    ``desired`` is what the cloud wants flashed (the build-host analogue of
    ``pending_model``); ``active`` is what is currently running (written back
    by this build host after a successful flash, like ``active_model``). A
    flat ``{"model_id":..,"confidence":..}`` doc is also accepted and treated
    as ``desired``. Returns ``{}`` when the file is absent or unreadable so a
    missing intent is a no-op (CLI flags / model-meta defaults win).
    """
    if not path.is_file():
        return {}
    try:
        with open(path) as f:
            doc = json.load(f)
    except Exception as e:
        logger.warning("firmware_intent at %s unreadable (%s) — ignoring.", path, e)
        return {}
    if not isinstance(doc, dict):
        return {}
    # Normalise a flat doc into the desired/active shape.
    if "desired" not in doc and ("model_id" in doc or "confidence" in doc):
        doc = {"desired": doc}
    return doc


def _resolve_model_from_intent(
    intent: dict,
    *,
    blob_arg: str,
    meta_arg: str,
    blob_was_default: bool,
    meta_was_default: bool,
) -> tuple[Path, Path, str | None, float | None]:
    """Apply a firmware_intent's desired model_id/confidence over the args.

    Returns (blob_path, meta_path, resolved_model_id, desired_confidence).

    Resolution rules (mirrors how pending_model drives a reflash):
      * desired.model_id selects the blob + meta to flash. It maps through the
        model registry (MODELS[id].blob_path); the meta JSON is the blob path
        with a .json suffix (the repo's sidecar convention — see
        nn_archive_builder.ensure_archive). An explicit --blob/--meta on the
        CLI still wins (operator override beats the synced intent).
      * desired.confidence is returned for the caller to stamp into the model
        meta the NN node reads (review H-5: confidence lives in the model
        metadata's confidence_threshold, NOT config.json), so a cloud-desired
        confidence drives the reflash without editing the model file on disk.
    """
    desired = intent.get("desired") or {}
    if not isinstance(desired, dict):
        desired = {}

    model_id = desired.get("model_id")
    blob_path = Path(blob_arg)
    meta_path = Path(meta_arg)
    resolved_id: str | None = None

    if model_id:
        # Import lazily so the diag scripts that call build_pipeline directly
        # don't pay for the registry import.
        try:
            from pipeline.model_registry import MODELS
        except Exception as e:
            logger.warning("model registry import failed (%s) — "
                           "cannot resolve desired model_id=%s.", e, model_id)
            MODELS = {}
        mdef = MODELS.get(model_id)
        if mdef is None:
            logger.warning("firmware_intent desired model_id=%s not in registry "
                           "— keeping blob/meta from args.", model_id)
        elif not mdef.blob_path:
            logger.warning("firmware_intent desired model_id=%s has no local "
                           "blob_path (source=%s) — standalone bake needs a "
                           ".blob; keeping args.", model_id, mdef.source)
        else:
            resolved_id = model_id
            registry_blob = (REPO / mdef.blob_path)
            registry_meta = registry_blob.with_suffix(".json")
            # CLI override wins over the synced intent.
            if blob_was_default:
                blob_path = registry_blob
            if meta_was_default:
                meta_path = registry_meta
            logger.info("firmware_intent: desired model_id=%s → blob=%s meta=%s",
                        model_id, blob_path.name, meta_path.name)

    conf = desired.get("confidence")
    desired_conf: float | None = None
    if conf is not None:
        try:
            desired_conf = float(conf)
        except Exception:
            logger.warning("firmware_intent desired confidence=%r not numeric "
                           "— ignoring.", conf)
            desired_conf = None
        else:
            if not (0.0 <= desired_conf <= 1.0):
                logger.warning("firmware_intent desired confidence=%.3f out of "
                               "[0,1] — ignoring.", desired_conf)
                desired_conf = None

    return blob_path, meta_path, resolved_id, desired_conf


def _record_active_after_flash(path: Path, intent: dict,
                               *, model_id: str | None, confidence: float | None) -> None:
    """Promote the just-flashed desired → active in firmware_intent.

    Mirrors the tablet writing active_model once the camera comes back on the
    new firmware (LocalAssetServer.kt). Best-effort: a write failure must not
    fail the flash, which already succeeded.
    """
    try:
        active = dict(intent.get("active") or {})
        if model_id is not None:
            active["model_id"] = model_id
        if confidence is not None:
            active["confidence"] = confidence
        active["flashed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        out = dict(intent)
        out["active"] = active
        with open(path, "w") as f:
            json.dump(out, f, indent=2)
        logger.info("firmware_intent: recorded active=%s after flash.", active)
    except Exception as e:
        logger.warning("could not record active firmware_intent at %s (%s) — "
                       "flash already succeeded.", path, e)


def _bake_script(*, dest_ip, dest_port, config_port, camera_id,
                 labels, units, pos_x, pos_y, yaw_deg, zones,
                 machine_len_m: float, machine_wid_m: float,
                 target_fps: float, config_src_ip: str = "",
                 allow_classes: set[str] | None = None) -> str:
    src = SCRIPT_SOURCE
    repl = {
        "__DEST_IP__":             dest_ip,
        "__DEST_PORT__":           str(dest_port),
        "__CONFIG_PORT__":         str(config_port),
        "__CONFIG_SRC_IP__":       config_src_ip,
        "__CAMERA_ID__":           camera_id,
        "__LABELS_JSON__":         json.dumps(labels),
        "__SAFETY_INDICES_JSON__": json.dumps(_safety_indices(labels, allow_classes)),
        "__UNITS__":               units,
        "__INIT_POS_X__":          f"{pos_x:.3f}",
        "__INIT_POS_Y__":          f"{pos_y:.3f}",
        "__INIT_YAW_DEG__":        f"{yaw_deg:.3f}",
        "__INIT_ZONES_JSON__":     json.dumps(zones),
        "__INIT_MACHINE_LEN_M__":  f"{machine_len_m:.3f}",
        "__INIT_MACHINE_WID_M__":  f"{machine_wid_m:.3f}",
        "__INIT_TARGET_FPS__":     f"{target_fps:.2f}",
    }
    for k, v in repl.items():
        src = src.replace(k, v)
    return src


def build_pipeline(*, blob_path: Path, model_meta: dict,
                   dest_ip: str, dest_port: int, config_port: int,
                   camera_id: str,
                   pos_x: float, pos_y: float, yaw_deg: float,
                   zones: list[dict],
                   machine_len_m: float, machine_wid_m: float,
                   units: str, fps: int, target_fps: float,
                   calib_json: Path, config_src_ip: str = "",
                   allow_classes: set[str] | None = None) -> dai.Pipeline:
    p = dai.Pipeline()
    p.setOpenVINOVersion(dai.OpenVINO.VERSION_2022_1)

    calib = dai.CalibrationHandler(str(calib_json))
    p.setCalibrationData(calib)

    input_size = model_meta["nn_config"]["input_size"]
    w, h = (int(x) for x in input_size.split("x"))
    classes = int(model_meta["nn_config"]["NN_specific_metadata"]["classes"])
    conf_thresh = float(model_meta["nn_config"]["NN_specific_metadata"]["confidence_threshold"])
    iou_thresh = float(model_meta["nn_config"]["NN_specific_metadata"]["iou_threshold"])
    coords = int(model_meta["nn_config"]["NN_specific_metadata"]["coordinates"])
    labels = list(model_meta["mappings"]["labels"])

    cam = p.createColorCamera()
    cam.setBoardSocket(dai.CameraBoardSocket.RGB)
    cam.setResolution(dai.ColorCameraProperties.SensorResolution.THE_1080_P)
    cam.setPreviewSize(w, h)
    cam.setInterleaved(False)
    # Luxonis depthai-zoo YOLOv8/v6 blobs are trained with Ultralytics,
    # which uses RGB. Sending BGR to these blobs silently produces
    # zero detections (confidences never clear the threshold).
    cam.setColorOrder(dai.ColorCameraProperties.ColorOrder.RGB)
    # YOLO input is square; 1080p sensor is 16:9. Without this, the
    # default center-crop would discard the left/right sides of the
    # frame and shrink effective FOV for detection.
    cam.setPreviewKeepAspectRatio(False)
    cam.setFps(fps)

    mono_l = p.createMonoCamera()
    mono_r = p.createMonoCamera()
    mono_l.setBoardSocket(dai.CameraBoardSocket.LEFT)
    mono_r.setBoardSocket(dai.CameraBoardSocket.RIGHT)
    mono_l.setResolution(dai.MonoCameraProperties.SensorResolution.THE_400_P)
    mono_r.setResolution(dai.MonoCameraProperties.SensorResolution.THE_400_P)
    mono_l.setFps(fps)
    mono_r.setFps(fps)

    stereo = p.createStereoDepth()
    stereo.setDefaultProfilePreset(dai.node.StereoDepth.PresetMode.HIGH_DENSITY)
    stereo.initialConfig.setMedianFilter(dai.MedianFilter.KERNEL_7x7)
    stereo.setLeftRightCheck(True)
    # ExtendedDisparity pushes stereo min depth from ~35cm to ~17cm, so a
    # person standing 1ft from the camera is still inside the valid depth
    # range instead of returning all-zero pixels.
    stereo.setExtendedDisparity(True)
    stereo.setSubpixel(False)
    stereo.setDepthAlign(dai.CameraBoardSocket.RGB)
    mono_l.out.link(stereo.left)
    mono_r.out.link(stereo.right)

    anchors_list = [float(a) for a in
                    model_meta["nn_config"]["NN_specific_metadata"].get("anchors", [])]
    anchor_masks = {k: list(v) for k, v in
                    model_meta["nn_config"]["NN_specific_metadata"].get("anchor_masks", {}).items()}

    nn = p.createYoloSpatialDetectionNetwork()
    nn.setBlobPath(str(blob_path))
    nn.setConfidenceThreshold(conf_thresh)
    nn.setNumClasses(classes)
    nn.setCoordinateSize(coords)
    nn.setAnchors(anchors_list)
    nn.setAnchorMasks(anchor_masks)
    nn.setIouThreshold(iou_thresh)
    nn.setBoundingBoxScaleFactor(0.5)
    # Lower bound was 300mm, which discards most torso pixels when the
    # subject is at ~1ft and skews the averaged depth out to 2-3ft. With
    # ExtendedDisparity on the stereo min is ~170mm, so 100mm gives a
    # safe margin without admitting noise pixels.
    nn.setDepthLowerThreshold(100)
    nn.setDepthUpperThreshold(25_000)
    nn.input.setBlocking(False)

    cam.preview.link(nn.input)
    stereo.depth.link(nn.inputDepth)

    # Re-IDs detections across frames so a person gets a stable track_id
    # rather than a fresh one every frame. ZERO_TERM_COLOR_HISTOGRAM
    # matches by bbox IoU + color histogram of the cropped region, so the
    # frame inputs are required (passthrough keeps them synced with the
    # detection messages they came from).
    # nn.passthrough is RGB888p (Ultralytics YOLO needs RGB input — see
    # cam.setColorOrder above), but ObjectTracker only accepts NV12,
    # YUV420p, or BGR888p. Convert with a tiny ImageManip so the tracker
    # gets a frame format it understands, otherwise it silently emits
    # zero Tracklets and the whole tracking path goes dead.
    manip = p.createImageManip()
    manip.initialConfig.setFrameType(dai.ImgFrame.Type.BGR888p)
    manip.setMaxOutputFrameSize(w * h * 3)
    nn.passthrough.link(manip.inputImage)

    tracker = p.createObjectTracker()
    tracker.setTrackerType(dai.TrackerType.ZERO_TERM_COLOR_HISTOGRAM)
    tracker.setTrackerIdAssignmentPolicy(dai.TrackerIdAssignmentPolicy.SMALLEST_ID)
    tracker.setMaxObjectsToTrack(20)
    safety = _safety_indices(labels, allow_classes)
    if safety:
        tracker.setDetectionLabelsToTrack(safety)
    manip.out.link(tracker.inputTrackerFrame)
    manip.out.link(tracker.inputDetectionFrame)
    nn.out.link(tracker.inputDetections)

    script = p.createScript()
    # Leon CSS runs the Ethernet LwIP stack on OAK-D PoE. Scripts default
    # to Leon MSS, which has no network access — `import socket` alone
    # crashes the VM there. Pin to CSS so sendto()/recvfrom() reach the wire.
    script.setProcessor(dai.ProcessorType.LEON_CSS)
    script.setScript(_bake_script(
        dest_ip=dest_ip, dest_port=dest_port, config_port=config_port,
        camera_id=camera_id, labels=labels, units=units,
        pos_x=pos_x, pos_y=pos_y, yaw_deg=yaw_deg, zones=zones,
        machine_len_m=machine_len_m, machine_wid_m=machine_wid_m,
        target_fps=target_fps, config_src_ip=config_src_ip,
        allow_classes=allow_classes,
    ))
    tracker.out.link(script.inputs["nn"])

    return p


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--camera-id",     default="cam-0",
                    help="Which installed_cameras[] entry to bake as fallback pose + zones.")
    ap.add_argument("--dest-ip",       default="169.254.1.56")
    ap.add_argument("--dest-port",     type=int, default=5556)
    ap.add_argument("--config-port",   type=int, default=5557,
                    help="Bidirectional config port: camera listens for pushes, sends requests to same port on tablet.")
    ap.add_argument("--units",         default="m", choices=("m", "ft"))
    ap.add_argument("--fps",           type=int, default=15,
                    help="Camera + NN inference rate. Locked at flash time.")
    ap.add_argument("--target-fps",    type=float, default=10.0,
                    help="Initial UDP send rate cap to the tablet. The tablet "
                         "may override this at runtime via the config push. "
                         "Set to 0 to send every inference frame.")
    ap.add_argument("--blob",          default=str(DEFAULT_BLOB))
    ap.add_argument("--meta",          default=str(DEFAULT_MODEL_JSON))
    ap.add_argument("--config",        default=str(DEFAULT_CONFIG),
                    help="Tablet config.json — used to seed the fallback pose + zones.")
    ap.add_argument("--firmware-intent", default=str(DEFAULT_FIRMWARE_INTENT),
                    help="Agent-synced firmware_intent.json (E3 reflash lane). Its "
                         "desired.model_id/confidence drive which model + confidence "
                         "this reflash bakes (the build-host analogue of pending_model). "
                         "Explicit --blob/--meta override it. Missing file = no-op.")
    ap.add_argument("--config-src-ip", default="",
                    help="Source IP the OAK accepts :5557 config from (review C-2 "
                         "allowlist). Defaults to --dest-ip (the P4/hub that serves "
                         "config back is the LAN authority). Empty disables the "
                         "allowlist — bench loopback only.")
    ap.add_argument("--confirm-flash", action="store_true",
                    help="Flash the baked pipeline. Without this flag, the "
                         "script dry-runs: builds, saves .dap, and exits.")
    ap.add_argument("--oak-ip",        default="169.254.1.222")
    ap.add_argument("--dap",           default=str(REPO / "pipeline" / "standalone" / "gridfront-scout-v2.dap"))
    ap.add_argument("--calib",         default=str(REPO / "calib_oak.json"),
                    help="Calibration JSON to embed (required — stereo crashes without it in standalone)")
    ap.add_argument("--only-classes",  default="",
                    help="Comma-separated class names to keep, overriding the default safety set. "
                         "Example: --only-classes person")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    # ── E3 reflash lane: resolve the agent-synced firmware_intent ────────
    # A cloud-desired model_id/confidence (mirrored into firmware_intent.json
    # by the sync-agent) drives WHICH model + confidence this reflash bakes.
    # This runs before loading the blob/meta so the desired model_id can
    # redirect them; explicit --blob/--meta still win.
    intent = _load_firmware_intent(Path(args.firmware_intent))
    blob, meta_path, resolved_model_id, desired_conf = _resolve_model_from_intent(
        intent,
        blob_arg=args.blob,
        meta_arg=args.meta,
        blob_was_default=(args.blob == str(DEFAULT_BLOB)),
        meta_was_default=(args.meta == str(DEFAULT_MODEL_JSON)),
    )

    if not blob.is_file():
        logger.error("Blob missing: %s", blob); return 1
    calib = Path(args.calib)
    if not calib.is_file():
        logger.error("Calibration JSON missing: %s — extract with "
                     "dai.Device(info).readCalibration2().eepromToJsonFile(...)",
                     calib); return 1
    with open(meta_path) as f:
        meta = json.load(f)

    # Stamp the desired confidence into the model meta the NN node reads.
    # Confidence is a baked (reflash-lane) value — it lives in the model
    # metadata's confidence_threshold (review H-5), which build_pipeline reads
    # at :164 and applies via nn.setConfidenceThreshold. Overriding it here
    # (in-memory only — we do NOT rewrite the on-disk model file) lets a
    # cloud-desired confidence drive the reflash without editing models/.
    if desired_conf is not None:
        try:
            nnmeta = meta["nn_config"]["NN_specific_metadata"]
            old_conf = nnmeta.get("confidence_threshold")
            nnmeta["confidence_threshold"] = desired_conf
            logger.info("firmware_intent: confidence_threshold %.3f → %.3f (baked).",
                        float(old_conf) if old_conf is not None else float("nan"),
                        desired_conf)
        except Exception as e:
            logger.warning("could not apply desired confidence to model meta (%s).", e)

    cfg_path = Path(args.config)
    if cfg_path.is_file():
        with open(cfg_path) as f:
            cfg = json.load(f)
        pos_x, pos_y, yaw_deg, zones, machine_len_m, machine_wid_m = _extract_pose_and_zones(
            cfg, args.camera_id,
        )
        logger.info(
            "Baking fallback from %s: pos=(%.2f, %.2f) yaw=%.1f° zones=%d footprint=%.1fx%.1fm",
            cfg_path.name, pos_x, pos_y, yaw_deg, len(zones), machine_len_m, machine_wid_m,
        )
    else:
        logger.warning("No config.json at %s — baking empty fallback (tablet must push on boot).", cfg_path)
        pos_x, pos_y, yaw_deg, zones = 0.0, 0.0, 0.0, []
        machine_len_m, machine_wid_m = 8.0, 2.5

    allow_classes: set[str] | None = None
    if args.only_classes.strip():
        allow_classes = {c.strip() for c in args.only_classes.split(",") if c.strip()}
        logger.info("Class filter override: only %s will pass safety gate.",
                    sorted(allow_classes))

    # The OAK accepts :5557 config ONLY from this source (review C-2). Default
    # to the P4/hub we send detections to — it is the LAN config authority.
    config_src_ip = args.config_src_ip if args.config_src_ip else args.dest_ip

    logger.info("Building pipeline from blob %s (no device connection)...", blob.name)
    pipeline = build_pipeline(
        blob_path=blob, model_meta=meta,
        dest_ip=args.dest_ip, dest_port=args.dest_port, config_port=args.config_port,
        camera_id=args.camera_id,
        pos_x=pos_x, pos_y=pos_y, yaw_deg=yaw_deg, zones=zones,
        machine_len_m=machine_len_m, machine_wid_m=machine_wid_m,
        units=args.units, fps=args.fps, target_fps=args.target_fps,
        calib_json=calib, config_src_ip=config_src_ip, allow_classes=allow_classes,
    )
    logger.info("Pipeline ready. Detections→%s:%d, Config↔:%d (accept from %s), camera_id=%s",
                args.dest_ip, args.dest_port, args.config_port,
                config_src_ip or "ANY(allowlist off)", args.camera_id)
    if resolved_model_id:
        logger.info("Baked perception (reflash lane): model_id=%s", resolved_model_id)

    logger.info("Saving .dap sidecar to %s ...", args.dap)
    dai.DeviceBootloader.saveDepthaiApplicationPackage(args.dap, pipeline, True, "gridfront-scout")
    logger.info("Saved (%d bytes).", Path(args.dap).stat().st_size)

    if not args.confirm_flash:
        logger.info("Dry-run — re-run with --confirm-flash to bake.")
        return 0

    logger.warning("====================================================")
    logger.warning("  Expecting OAK in BOOTLOADER state at %s.", args.oak_ip)
    logger.warning("  If it's currently in SDK mode, power-cycle it now.")
    logger.warning("  Waiting up to 120s...")
    logger.warning("====================================================")

    info = dai.DeviceInfo(args.oak_ip)
    bl = None
    deadline = time.time() + 120
    tries = 0
    while time.time() < deadline and bl is None:
        tries += 1
        try:
            bl = dai.DeviceBootloader(info)
            logger.info("Attached bootloader on try #%d", tries)
        except Exception:
            pass

    if bl is None:
        logger.error("OAK not in BOOTLOADER at %s after %d tries.", args.oak_ip, tries)
        return 1

    try:
        logger.info("Flashing pipeline (compressed)...")
        progress = lambda pct: logger.info("flash progress: %.1f%%", pct * 100.0)
        ok, msg = bl.flash(progress, pipeline, compress=True, applicationName="gridfront-scout")
        if not ok:
            logger.error("Flash failed: %s", msg)
            return 1
        logger.info("Flash complete. Power-cycle the camera to boot standalone.")
        # E3: promote desired → active in firmware_intent now the reflash
        # landed (mirrors the tablet writing active_model post-reflash). Only
        # when an intent actually drove this build, and best-effort.
        if intent and (resolved_model_id is not None or desired_conf is not None):
            _record_active_after_flash(
                Path(args.firmware_intent), intent,
                model_id=resolved_model_id, confidence=desired_conf,
            )
    except Exception:
        logger.exception("Flash crashed"); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
