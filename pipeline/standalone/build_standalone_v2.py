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


def _bake_script(*, dest_ip, dest_port, config_port, camera_id,
                 labels, units, pos_x, pos_y, yaw_deg, zones,
                 machine_len_m: float, machine_wid_m: float,
                 target_fps: float, allow_classes: set[str] | None = None) -> str:
    src = SCRIPT_SOURCE
    repl = {
        "__DEST_IP__":             dest_ip,
        "__DEST_PORT__":           str(dest_port),
        "__CONFIG_PORT__":         str(config_port),
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
                   calib_json: Path,
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
        target_fps=target_fps, allow_classes=allow_classes,
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

    blob = Path(args.blob)
    if not blob.is_file():
        logger.error("Blob missing: %s", blob); return 1
    calib = Path(args.calib)
    if not calib.is_file():
        logger.error("Calibration JSON missing: %s — extract with "
                     "dai.Device(info).readCalibration2().eepromToJsonFile(...)",
                     calib); return 1
    with open(args.meta) as f:
        meta = json.load(f)

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

    logger.info("Building pipeline from blob %s (no device connection)...", blob.name)
    pipeline = build_pipeline(
        blob_path=blob, model_meta=meta,
        dest_ip=args.dest_ip, dest_port=args.dest_port, config_port=args.config_port,
        camera_id=args.camera_id,
        pos_x=pos_x, pos_y=pos_y, yaw_deg=yaw_deg, zones=zones,
        machine_len_m=machine_len_m, machine_wid_m=machine_wid_m,
        units=args.units, fps=args.fps, target_fps=args.target_fps,
        calib_json=calib, allow_classes=allow_classes,
    )
    logger.info("Pipeline ready. Detections→%s:%d, Config↔:%d, camera_id=%s",
                args.dest_ip, args.dest_port, args.config_port, args.camera_id)

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
    except Exception:
        logger.exception("Flash crashed"); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
