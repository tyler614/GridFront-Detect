"""Test both: compress=False flash AND bootMemory (RAM boot) of cam_minimal.

Two experiments, in order:
1. Flash cam_minimal uncompressed. If this boots where compressed failed,
   the bootloader's decompression is the bug.
2. If flash still fails, use bootMemory() to run the same package in RAM
   and attach Device() for log capture — we finally see WHY the pipeline
   crashes post-boot.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

import depthai as dai


HEARTBEAT = r"""
import socket
import time

DEST_IP   = "169.254.1.56"
DEST_PORT = 5556

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    sock.sendto(b'boot cam_bm', (DEST_IP, DEST_PORT))
except Exception as e:
    node.warn("boot err: " + str(e))

seq = 0
while True:
    seq += 1
    try:
        frame = node.io["frame"].tryGet()
    except Exception:
        frame = None
    got = "1" if frame is not None else "0"
    node.warn("hb " + str(seq) + " f=" + got)
    try:
        sock.sendto(b'hb cam_bm ' + str(seq).encode() + b' f=' + got.encode(),
                    (DEST_IP, DEST_PORT))
    except Exception as e:
        node.warn("sendto err: " + str(e))
    time.sleep(0.5)
"""


def build_pipeline() -> dai.Pipeline:
    p = dai.Pipeline()
    script = p.createScript()
    script.setProcessor(dai.ProcessorType.LEON_CSS)
    script.setScript(HEARTBEAT)

    cam = p.createColorCamera()
    cam.setBoardSocket(dai.CameraBoardSocket.CAM_A)
    cam.setResolution(dai.ColorCameraProperties.SensorResolution.THE_1080_P)
    cam.setPreviewSize(512, 288)
    cam.setInterleaved(False)
    cam.setFps(15)
    cam.preview.link(script.inputs["frame"])
    script.inputs["frame"].setBlocking(False)
    script.inputs["frame"].setQueueSize(1)
    return p


def attach_bootloader(oak_ip: str, deadline_sec: float = 120.0):
    info = dai.DeviceInfo(oak_ip)
    deadline = time.time() + deadline_sec
    while time.time() < deadline:
        try:
            bl = dai.DeviceBootloader(info)
            logging.info("attached bl=%s", bl.getVersion())
            return bl
        except Exception:
            pass
    raise RuntimeError("couldn't attach bootloader")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("flash_nocompress", "boot_memory"),
                    required=True)
    ap.add_argument("--oak-ip", default="169.254.1.222")
    args = ap.parse_args()

    p = build_pipeline()

    if args.mode == "flash_nocompress":
        logging.info("Attaching bootloader (up to 2 min)...")
        bl = attach_bootloader(args.oak_ip)
        logging.info("Flashing pipeline with compress=False...")
        ok, msg = bl.flash(lambda pct: logging.info("flash %.1f%%", pct*100),
                           p, compress=False,
                           applicationName="gridfront-cam-nocomp")
        logging.info("Flash done: ok=%s msg=%r", ok, msg)
        return 0 if ok else 1

    if args.mode == "boot_memory":
        logging.info("Building app package...")
        pkg = dai.DeviceBootloader.createDepthaiApplicationPackage(
            p, compress=False, applicationName="gridfront-cam-bm")
        logging.info("Package size: %d bytes", len(pkg))

        logging.info("Attaching bootloader...")
        bl = attach_bootloader(args.oak_ip)
        logging.info("Booting package from RAM (bootMemory)...")
        try:
            bl.bootMemory(pkg)
        except Exception as e:
            logging.error("bootMemory threw: %r", e)
            # fall through — device may still boot
        # bootloader session closes once device starts app
        # Now try to attach Device for logs.
        time.sleep(5)
        logging.info("Attempting Device attach for log capture...")
        info = dai.DeviceInfo(args.oak_ip)
        try:
            dev = dai.Device(info)
            dev.setLogLevel(dai.LogLevel.TRACE)
            dev.setLogOutputLevel(dai.LogLevel.TRACE)

            def on_log(m):
                lvl = getattr(m, "level", "?")
                payload = getattr(m, "payload", str(m))
                print(f"  [{lvl}] {payload}")
            dev.addLogCallback(on_log)
            logging.info("Attached. Streaming logs for 30s...")
            t0 = time.time()
            while time.time() - t0 < 30:
                time.sleep(0.2)
            dev.close()
        except Exception as e:
            logging.error("Device attach failed: %r", e)
            return 1
        return 0

    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
