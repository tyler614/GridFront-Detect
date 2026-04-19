"""Flash a standalone pipeline to an OAK-D bootloader, in two stages.

Stage A: build the pipeline (auto-connects as SDK device), save it to a
.dap file while the device is connected (so serialize RPC works), then
close the device.

Stage B: wait for the user to power-cycle the OAK. When the bootloader
re-appears, attach and flash the pre-saved .dap file.

Why the split: DepthAI v3 `DeviceBootloader.flash(pipeline)` and
`createDepthaiApplicationPackage(pipeline)` both crash — the former
segfaults in getNodeLogLevel RPC after the SDK device is closed, the
latter has a broken pybind return-value binding for vector<unsigned char>.
File-based round-trip sidesteps both.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time

import depthai as dai

from pipeline.standalone.build_standalone import build_pipeline

logger = logging.getLogger(__name__)

DEFAULT_DAP_PATH = r"C:\Users\helve\detect.gridfront.io\pipeline\standalone\gridfront-detect.dap"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dest-ip",       default="192.168.68.56")
    p.add_argument("--dest-port",     type=int,   default=5556)
    p.add_argument("--danger-m",      type=float, default=3.0)
    p.add_argument("--warning-m",     type=float, default=6.0)
    p.add_argument("--half-length-m", type=float, default=4.2)
    p.add_argument("--half-width-m",  type=float, default=1.25)
    p.add_argument("--units",         default="m", choices=("m", "ft"))
    p.add_argument("--fps",           type=int, default=15)
    p.add_argument("--oak-ip",        default="169.254.1.222")
    p.add_argument("--dap",           default=DEFAULT_DAP_PATH,
                   help="Path to .dap package (created in stage A, consumed in stage B).")
    p.add_argument("--skip-save",     action="store_true",
                   help="Skip stage A (build+save). Useful if .dap already exists.")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    # ---- Stage A: build + save ----
    if not args.skip_save:
        logger.info("Building pipeline...")
        pipeline = build_pipeline(
            dest_ip=args.dest_ip, dest_port=args.dest_port,
            danger_m=args.danger_m, warning_m=args.warning_m,
            half_length_m=args.half_length_m, half_width_m=args.half_width_m,
            units=args.units, fps=args.fps,
        )
        logger.info("Targeting %s:%d, danger=%.1fm warning=%.1fm",
                    args.dest_ip, args.dest_port, args.danger_m, args.warning_m)

        logger.info("Saving .dap to %s ...", args.dap)
        dai.DeviceBootloader.saveDepthaiApplicationPackage(
            args.dap, pipeline, True, "gridfront-detect"
        )
        logger.info("Saved %d bytes.", os.path.getsize(args.dap))

        default_dev = pipeline.getDefaultDevice()
        if default_dev is not None:
            logger.info("Closing SDK device...")
            default_dev.close()

    if not os.path.isfile(args.dap):
        logger.error(".dap file missing at %s; cannot flash.", args.dap)
        return 1

    # ---- Stage B: wait for power-cycle, attach bootloader, flash ----
    logger.warning("====================================================")
    logger.warning("  POWER-CYCLE THE OAK NOW (unplug PoE, wait 3s, replug).")
    logger.warning("  Waiting up to 240s for BOOTLOADER reappearance...")
    logger.warning("====================================================")

    info = None
    deadline = time.time() + 240
    last_seen_state = None
    saw_disappearance = args.skip_save  # if we skipped stage A, device is already fresh
    stable_bootloader_since = None
    while time.time() < deadline:
        devices = dai.Device.getAllAvailableDevices()
        cand = next((d for d in devices if d.name == args.oak_ip), None)
        if cand is None:
            if last_seen_state is not None:
                saw_disappearance = True
                stable_bootloader_since = None
                logger.info("OAK disappeared — waiting for reboot...")
            last_seen_state = None
        else:
            s = str(cand.state)
            if s != last_seen_state:
                logger.info("OAK visible in state %s", s)
                last_seen_state = s
            if cand.state == dai.XLinkDeviceState.X_LINK_BOOTLOADER:
                if saw_disappearance:
                    if stable_bootloader_since is None:
                        stable_bootloader_since = time.time()
                    elif time.time() - stable_bootloader_since >= 3.0:
                        info = cand
                        break
            else:
                stable_bootloader_since = None
        time.sleep(1.5)

    if info is None:
        logger.error("Timed out waiting for fresh OAK after power-cycle.")
        return 1

    logger.info("Reading %s ...", args.dap)
    with open(args.dap, "rb") as f:
        package_bytes = f.read()
    logger.info("Loaded %d bytes.", len(package_bytes))

    try:
        logger.info("Attaching bootloader at %s...", info.name)
        bootloader = dai.DeviceBootloader(info)
        logger.info("Flashing .dap package...")
        progress = lambda pc: logger.info("flash progress: %.1f%%", pc * 100.0)
        success, msg = bootloader.flashDepthaiApplicationPackage(progress, package_bytes)
        if not success:
            logger.error("Flash failed: %s", msg)
            return 1
        logger.info("Flash complete. Power-cycle the camera to boot standalone.")
    except Exception:
        logger.exception("Flash crashed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
