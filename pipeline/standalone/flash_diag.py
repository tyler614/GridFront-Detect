"""Staged diagnostic flash — add one node family at a time and see what boots.

Stages:
  cam            — ColorCamera only + Script heartbeat
  stereo_raw     — + Mono + StereoDepth (defaults only)
  stereo_align   — stereo_raw + setDepthAlign(RGB) (for NN spatial coords)
  stereo_preset  — stereo_align + HIGH_DENSITY preset + LRCheck + median filter
  nn             — stereo_preset + YoloSpatialDetectionNetwork

Script always sends UDP heartbeats at 2 pps regardless of input. If heartbeats
arrive on the tablet, that stage booted. If silence, that stage's new node
crashed the pipeline during init.

Usage (OAK in BOOTLOADER, from scout.gridfront.io root, 2.x venv):
  .venv2x/Scripts/python.exe -m pipeline.standalone.flash_diag \\
      --stage cam --dest-ip 169.254.1.56 --dest-port 5556
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import depthai as dai

logger = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parents[2]
DEFAULT_BLOB = REPO / "models" / "gridfront-scout-v1.blob"
DEFAULT_MODEL_JSON = REPO / "models" / "gridfront-scout-v1.json"

HEARTBEAT_SRC = r"""
import socket
import time

DEST_IP   = "__DEST_IP__"
DEST_PORT = __DEST_PORT__
STAGE     = "__STAGE__"

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
# Boot-alive packet BEFORE any input polling — proves pipeline init completed.
try:
    sock.sendto(b'boot ' + STAGE.encode(), (DEST_IP, DEST_PORT))
except Exception as e:
    node.warn("boot sendto err: " + str(e))

seq = 0
while True:
    seq += 1
    payload = b'hb ' + STAGE.encode() + b' ' + str(seq).encode()
    try:
        sock.sendto(payload, (DEST_IP, DEST_PORT))
    except Exception as e:
        node.warn("sendto err: " + str(e))
    time.sleep(0.5)
"""


def build(stage: str, *, dest_ip: str, dest_port: int,
          blob_path: Path, model_meta: dict,
          calib_json: Path | None = None) -> dai.Pipeline:
    p = dai.Pipeline()
    # OpenVINO version only needs pinning when a NN blob is loaded.
    if stage == "nn":
        p.setOpenVINOVersion(dai.OpenVINO.VERSION_2022_1)

    # In DepthAI 2.x standalone mode, the EEPROM calibration is NOT auto-loaded
    # into the flashed pipeline at boot. StereoDepth needs it explicitly baked
    # in, otherwise the pipeline crashes during node init.
    if calib_json is not None and calib_json.is_file():
        calib = dai.CalibrationHandler(str(calib_json))
        p.setCalibrationData(calib)
        logger.info("Embedded calibration from %s", calib_json)

    script = p.createScript()
    script.setProcessor(dai.ProcessorType.LEON_CSS)
    src = (HEARTBEAT_SRC
           .replace("__DEST_IP__", dest_ip)
           .replace("__DEST_PORT__", str(dest_port))
           .replace("__STAGE__", stage))
    script.setScript(src)

    if stage in ("cam", "stereo_raw", "stereo_align", "stereo_preset", "nn"):
        cam = p.createColorCamera()
        cam.setBoardSocket(dai.CameraBoardSocket.RGB)
        cam.setResolution(dai.ColorCameraProperties.SensorResolution.THE_1080_P)
        cam.setPreviewSize(512, 288)
        cam.setInterleaved(False)
        cam.setColorOrder(dai.ColorCameraProperties.ColorOrder.BGR)
        cam.setFps(15)

    if stage in ("stereo_raw", "stereo_align", "stereo_preset", "nn"):
        mono_l = p.createMonoCamera()
        mono_r = p.createMonoCamera()
        mono_l.setBoardSocket(dai.CameraBoardSocket.LEFT)
        mono_r.setBoardSocket(dai.CameraBoardSocket.RIGHT)
        mono_l.setResolution(dai.MonoCameraProperties.SensorResolution.THE_400_P)
        mono_r.setResolution(dai.MonoCameraProperties.SensorResolution.THE_400_P)
        mono_l.setFps(15)
        mono_r.setFps(15)

        stereo = p.createStereoDepth()
        if stage in ("stereo_align", "stereo_preset", "nn"):
            stereo.setDepthAlign(dai.CameraBoardSocket.RGB)
        if stage in ("stereo_preset", "nn"):
            stereo.setDefaultProfilePreset(dai.node.StereoDepth.PresetMode.HIGH_DENSITY)
            stereo.initialConfig.setMedianFilter(dai.MedianFilter.KERNEL_7x7)
            stereo.setLeftRightCheck(True)
            stereo.setExtendedDisparity(False)
            stereo.setSubpixel(False)
        mono_l.out.link(stereo.left)
        mono_r.out.link(stereo.right)
        # Give stereo.depth a consumer so it isn't dangling. Script never
        # actually reads from this input — it's just there for routing.
        stereo.depth.link(script.inputs["depth"])
        script.inputs["depth"].setBlocking(False)
        script.inputs["depth"].setQueueSize(1)

    if stage == "nn":
        classes = int(model_meta["nn_config"]["NN_specific_metadata"]["classes"])
        conf_thresh = float(model_meta["nn_config"]["NN_specific_metadata"]["confidence_threshold"])
        iou_thresh = float(model_meta["nn_config"]["NN_specific_metadata"]["iou_threshold"])
        coords = int(model_meta["nn_config"]["NN_specific_metadata"]["coordinates"])

        nn = p.createYoloSpatialDetectionNetwork()
        nn.setBlobPath(str(blob_path))
        nn.setConfidenceThreshold(conf_thresh)
        nn.setNumClasses(classes)
        nn.setCoordinateSize(coords)
        nn.setAnchors([])
        nn.setAnchorMasks({})
        nn.setIouThreshold(iou_thresh)
        nn.setBoundingBoxScaleFactor(0.5)
        nn.setDepthLowerThreshold(300)
        nn.setDepthUpperThreshold(25_000)
        nn.input.setBlocking(False)
        cam.preview.link(nn.input)
        stereo.depth.link(nn.inputDepth)

    return p


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stage",     choices=("cam", "stereo_raw", "stereo_align", "stereo_preset", "nn"), required=True)
    ap.add_argument("--dest-ip",   default="169.254.1.56")
    ap.add_argument("--dest-port", type=int, default=5556)
    ap.add_argument("--oak-ip",    default="169.254.1.222")
    ap.add_argument("--blob",      default=str(DEFAULT_BLOB))
    ap.add_argument("--meta",      default=str(DEFAULT_MODEL_JSON))
    ap.add_argument("--calib",     default="calib_oak.json",
                    help="Calibration JSON to embed in pipeline")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    meta = {}
    if args.stage == "nn":
        with open(args.meta) as f:
            meta = json.load(f)
        if not Path(args.blob).is_file():
            logger.error("Blob missing: %s", args.blob); return 1

    logger.info("Building %s pipeline targeting %s:%d...",
                args.stage, args.dest_ip, args.dest_port)
    p = build(args.stage, dest_ip=args.dest_ip, dest_port=args.dest_port,
              blob_path=Path(args.blob), model_meta=meta,
              calib_json=Path(args.calib))

    logger.info("Spamming DeviceBootloader attach at %s for up to 120s...", args.oak_ip)
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
        logger.error("Never caught bootloader after %d tries.", tries)
        return 1

    try:
        logger.info("Flashing stage=%s pipeline (compressed)...", args.stage)
        ok, msg = bl.flash(lambda pct: logger.info("flash progress: %.1f%%", pct*100),
                           p, compress=True, applicationName=f"gridfront-diag-{args.stage}")
        if not ok:
            logger.error("Flash failed: %s", msg); return 1
        logger.info("Flash complete. Power-cycle the OAK.")
    except Exception:
        logger.exception("Flash crashed"); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
