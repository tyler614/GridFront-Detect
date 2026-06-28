"""Host-side run of the exact same NN pipeline used in standalone.

Why this exists: the Movidius Script VM gives us almost nothing to debug
with — every extra log field risks a crash that lands the OAK in
bootloader state and forces another 3-minute flash. This script runs
the *same* YOLO + stereo graph on the laptop via XLink, so we can see
what the NN is actually calling every detection, at what confidence,
and where in space it lands. Once detections look right here, we flash.

Usage (with .venv2x active):
    .venv2x/Scripts/python.exe -m pipeline.standalone.debug_live \\
        --blob models/yolov8n-coco.blob --meta models/yolov8n-coco.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import depthai as dai

REPO = Path(__file__).resolve().parents[2]


def build(blob: Path, meta: dict, fps: int) -> tuple[dai.Pipeline, list[str]]:
    w, h = (int(x) for x in meta["nn_config"]["input_size"].split("x"))
    classes = int(meta["nn_config"]["NN_specific_metadata"]["classes"])
    conf = float(meta["nn_config"]["NN_specific_metadata"]["confidence_threshold"])
    iou = float(meta["nn_config"]["NN_specific_metadata"]["iou_threshold"])
    coords = int(meta["nn_config"]["NN_specific_metadata"]["coordinates"])
    labels = list(meta["mappings"]["labels"])

    p = dai.Pipeline()
    p.setOpenVINOVersion(dai.OpenVINO.VERSION_2022_1)

    cam = p.createColorCamera()
    cam.setBoardSocket(dai.CameraBoardSocket.RGB)
    cam.setResolution(dai.ColorCameraProperties.SensorResolution.THE_1080_P)
    cam.setPreviewSize(w, h)
    cam.setInterleaved(False)
    cam.setColorOrder(dai.ColorCameraProperties.ColorOrder.RGB)
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
    stereo.setExtendedDisparity(False)
    stereo.setSubpixel(False)
    stereo.setDepthAlign(dai.CameraBoardSocket.RGB)
    mono_l.out.link(stereo.left)
    mono_r.out.link(stereo.right)

    nn = p.createYoloSpatialDetectionNetwork()
    nn.setBlobPath(str(blob))
    nn.setConfidenceThreshold(conf)
    nn.setNumClasses(classes)
    nn.setCoordinateSize(coords)
    nn.setAnchors([])
    nn.setAnchorMasks({})
    nn.setIouThreshold(iou)
    nn.setBoundingBoxScaleFactor(0.5)
    nn.setDepthLowerThreshold(300)
    nn.setDepthUpperThreshold(25_000)
    nn.input.setBlocking(False)

    cam.preview.link(nn.input)
    stereo.depth.link(nn.inputDepth)

    x_det = p.createXLinkOut()
    x_det.setStreamName("det")
    nn.out.link(x_det.input)

    return p, labels


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--blob", default=str(REPO / "models" / "yolov8n-coco.blob"))
    ap.add_argument("--meta", default=str(REPO / "models" / "yolov8n-coco.json"))
    ap.add_argument("--oak-ip", default="169.254.1.222")
    ap.add_argument("--fps", type=int, default=10)
    ap.add_argument("--min-conf", type=float, default=0.0,
                    help="Host-side filter for printing; NN still emits at its own threshold.")
    ap.add_argument("--duration", type=float, default=0.0,
                    help="Seconds to run before exiting (0 = until Ctrl-C).")
    args = ap.parse_args()

    with open(args.meta) as f:
        meta = json.load(f)

    pipeline, labels = build(Path(args.blob), meta, args.fps)
    info = dai.DeviceInfo(args.oak_ip)

    print(f"Attaching to OAK at {args.oak_ip} (pipeline: {Path(args.blob).name})...")
    with dai.Device(pipeline, info) as dev:
        q_det = dev.getOutputQueue("det", maxSize=4, blocking=False)
        print("Connected. Printing detections — press Ctrl-C to stop.\n")

        start = time.time()
        frames = 0
        last_stats = start
        while True:
            pkt = q_det.tryGet()
            if pkt is not None:
                frames += 1
                dets = pkt.detections
                shown = [d for d in dets if d.confidence >= args.min_conf]
                if shown:
                    print(f"[t={time.time()-start:6.1f}s] {len(dets):2d} dets:")
                    for d in shown:
                        name = labels[d.label] if 0 <= d.label < len(labels) else f"?{d.label}"
                        x = d.spatialCoordinates.x / 1000.0
                        y = d.spatialCoordinates.y / 1000.0
                        z = d.spatialCoordinates.z / 1000.0
                        print(f"    {name:<15} conf={d.confidence:.2f}  "
                              f"x={x:+6.2f}m y={y:+6.2f}m z={z:+6.2f}m")
            now = time.time()
            if now - last_stats >= 5.0:
                print(f"... {frames} NN frames in last {now-last_stats:.1f}s")
                frames = 0
                last_stats = now
            if args.duration and (now - start) >= args.duration:
                break
            time.sleep(0.01)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nstopped.")
        sys.exit(0)
