"""Standalone pipeline bake, DepthAI 2.x edition.

Why this exists: DepthAI 3.x Python bindings have a broken pybind
conversion for std::vector<unsigned char>, which blocks every Python flash
path (flash(), createDAP+flashDAP). This script targets DepthAI 2.29.0
where the bindings work, and uses a local YOLO .blob instead of a HubAI
slug so the pipeline can be built offline — no pre-flash device session
required, so no serialize-RPC-on-closed-device segfault.

Usage (from detect.gridfront.io root, with the 2.x venv active):

    .venv2x/Scripts/python.exe -m pipeline.standalone.build_standalone_v2 \\
        --dest-ip 169.254.1.56 --dest-port 5556 --confirm-flash

The default dest-ip is link-local (169.254.1.56) for point-to-point USB-C
from tablet → OAK: no DHCP server needed, tablet's eth0 gets 169.254.1.56/16,
OAK defaults to 169.254.1.222, they see each other on the same subnet.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import depthai as dai

from pipeline.standalone.script_runtime import SCRIPT_SOURCE

logger = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parents[2]
DEFAULT_BLOB = REPO / "models" / "gridfront-detect-v1.blob"
DEFAULT_MODEL_JSON = REPO / "models" / "gridfront-detect-v1.json"

_SAFETY_LABEL_NAMES = {"person", "excavator", "wheel-loader", "dozer",
                       "crane", "dump-truck", "grader", "compactor"}


def _safety_indices(labels: list[str]) -> list[int]:
    return sorted(i for i, name in enumerate(labels) if name in _SAFETY_LABEL_NAMES)


def _bake_script(*, dest_ip, dest_port, danger_m, warning_m,
                 half_length_m, half_width_m, labels, units) -> str:
    src = SCRIPT_SOURCE
    repl = {
        "__DEST_IP__":             dest_ip,
        "__DEST_PORT__":           str(dest_port),
        "__DANGER_M__":            f"{danger_m:.3f}",
        "__WARNING_M__":           f"{warning_m:.3f}",
        "__HALF_LENGTH_M__":       f"{half_length_m:.3f}",
        "__HALF_WIDTH_M__":        f"{half_width_m:.3f}",
        "__LABELS_JSON__":         json.dumps(labels),
        "__SAFETY_INDICES_JSON__": json.dumps(_safety_indices(labels)),
        "__UNITS__":               units,
    }
    for k, v in repl.items():
        src = src.replace(k, v)
    return src


def build_pipeline(*, blob_path: Path, model_meta: dict,
                   dest_ip: str, dest_port: int,
                   danger_m: float, warning_m: float,
                   half_length_m: float, half_width_m: float,
                   units: str, fps: int,
                   calib_json: Path) -> dai.Pipeline:
    p = dai.Pipeline()
    # OAK-D Pro W PoE bootloader is fairly recent — pin OpenVINO to the
    # version the blob was compiled with. If the blob was compiled for a
    # different version, detection outputs will be garbage or the device
    # will refuse to load it.
    p.setOpenVINOVersion(dai.OpenVINO.VERSION_2022_1)

    # In DepthAI 2.x standalone mode, the device does NOT auto-load EEPROM
    # calibration into the flashed pipeline at boot — StereoDepth then
    # crashes the pipeline during init. Embed calibration explicitly here.
    # Extract once via: dai.Device(info).readCalibration2().eepromToJsonFile(path)
    calib = dai.CalibrationHandler(str(calib_json))
    p.setCalibrationData(calib)

    input_size = model_meta["nn_config"]["input_size"]   # "512x288"
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
    cam.setColorOrder(dai.ColorCameraProperties.ColorOrder.BGR)
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
    stereo.setExtendedDisparity(False)
    stereo.setSubpixel(False)
    stereo.setDepthAlign(dai.CameraBoardSocket.RGB)
    mono_l.out.link(stereo.left)
    mono_r.out.link(stereo.right)

    nn = p.createYoloSpatialDetectionNetwork()
    nn.setBlobPath(str(blob_path))
    nn.setConfidenceThreshold(conf_thresh)
    nn.setNumClasses(classes)
    nn.setCoordinateSize(coords)
    nn.setAnchors([])           # anchor-free (YOLOv6/v8)
    nn.setAnchorMasks({})
    nn.setIouThreshold(iou_thresh)
    nn.setBoundingBoxScaleFactor(0.5)
    nn.setDepthLowerThreshold(300)     # 0.3 m
    nn.setDepthUpperThreshold(25_000)  # 25 m
    nn.input.setBlocking(False)

    cam.preview.link(nn.input)
    stereo.depth.link(nn.inputDepth)

    script = p.createScript()
    # Leon CSS runs the Ethernet LwIP stack on OAK-D PoE. Scripts default
    # to Leon MSS, which has no network access — `import socket` alone
    # crashes the VM there. Pin to CSS so sendto() reaches the wire.
    script.setProcessor(dai.ProcessorType.LEON_CSS)
    script.setScript(_bake_script(
        dest_ip=dest_ip, dest_port=dest_port,
        danger_m=danger_m, warning_m=warning_m,
        half_length_m=half_length_m, half_width_m=half_width_m,
        labels=labels, units=units,
    ))
    nn.out.link(script.inputs["nn"])

    return p


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dest-ip",       default="169.254.1.56")
    ap.add_argument("--dest-port",     type=int, default=5556)
    ap.add_argument("--danger-m",      type=float, default=3.0)
    ap.add_argument("--warning-m",     type=float, default=6.0)
    ap.add_argument("--half-length-m", type=float, default=4.2)
    ap.add_argument("--half-width-m",  type=float, default=1.25)
    ap.add_argument("--units",         default="m", choices=("m", "ft"))
    ap.add_argument("--fps",           type=int, default=15)
    ap.add_argument("--blob",          default=str(DEFAULT_BLOB))
    ap.add_argument("--meta",          default=str(DEFAULT_MODEL_JSON))
    ap.add_argument("--confirm-flash", action="store_true",
                    help="Flash the baked pipeline. Without this flag, the "
                         "script dry-runs: builds, saves .dap, and exits.")
    ap.add_argument("--oak-ip",        default="169.254.1.222")
    ap.add_argument("--dap",           default=str(REPO / "pipeline" / "standalone" / "gridfront-detect-v2.dap"))
    ap.add_argument("--calib",         default=str(REPO / "calib_oak.json"),
                    help="Calibration JSON to embed (required — stereo crashes without it in standalone)")
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

    logger.info("Building pipeline from blob %s (no device connection)...", blob.name)
    pipeline = build_pipeline(
        blob_path=blob, model_meta=meta,
        dest_ip=args.dest_ip, dest_port=args.dest_port,
        danger_m=args.danger_m, warning_m=args.warning_m,
        half_length_m=args.half_length_m, half_width_m=args.half_width_m,
        units=args.units, fps=args.fps, calib_json=calib,
    )
    logger.info("Pipeline ready. Target %s:%d, danger=%.1fm warning=%.1fm",
                args.dest_ip, args.dest_port, args.danger_m, args.warning_m)

    logger.info("Saving .dap sidecar to %s ...", args.dap)
    dai.DeviceBootloader.saveDepthaiApplicationPackage(args.dap, pipeline, True, "gridfront-detect")
    logger.info("Saved (%d bytes).", Path(args.dap).stat().st_size)

    if not args.confirm_flash:
        logger.info("Dry-run — re-run with --confirm-flash to bake.")
        return 0

    logger.warning("====================================================")
    logger.warning("  Expecting OAK in BOOTLOADER state at %s.", args.oak_ip)
    logger.warning("  If it's currently in SDK mode, power-cycle it now.")
    logger.warning("  Waiting up to 120s...")
    logger.warning("====================================================")

    # Bootloader windows can be tight (≤1s with short network-timeout configs
    # or when flashed app auto-launches quickly). Spam DeviceBootloader(info)
    # directly instead of polling discovery — far faster than getAllAvailableDevices.
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
            pass  # retry immediately

    if bl is None:
        logger.error("OAK not in BOOTLOADER at %s after %d tries.", args.oak_ip, tries)
        return 1

    try:
        logger.info("Flashing pipeline (compressed)...")
        progress = lambda pct: logger.info("flash progress: %.1f%%", pct * 100.0)
        ok, msg = bl.flash(progress, pipeline, compress=True, applicationName="gridfront-detect")
        if not ok:
            logger.error("Flash failed: %s", msg)
            return 1
        logger.info("Flash complete. Power-cycle the camera to boot standalone.")
    except Exception:
        logger.exception("Flash crashed"); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
