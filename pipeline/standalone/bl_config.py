"""Bootloader config dump + repair.

Inspects current bootloader config (network timeout, appMem,
staticIpv4, etc.) and optionally bumps the network/watchdog
timeout and flashes the latest bootloader. Useful when
previously working pipelines start crashing at flash-boot —
often caused by the bootloader killing cam/stereo init before
it finishes.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import timedelta

import depthai as dai


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--oak-ip", default="169.254.1.222")
    ap.add_argument("--timeout-sec", type=int, default=60)
    ap.add_argument("--flash-bootloader", action="store_true",
                    help="Upgrade/refresh the bootloader itself.")
    ap.add_argument("--factory-reset", action="store_true",
                    help="Wipe app partition (leaves bootloader).")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    info = dai.DeviceInfo(args.oak_ip)
    bl = None
    deadline = time.time() + 60
    # allowFlashingBootloader unlocks flashBootloader() — harmless for the
    # read-only paths so we just always enable it.
    while time.time() < deadline and bl is None:
        try:
            bl = dai.DeviceBootloader(info, True)
        except Exception:
            pass
    if bl is None:
        logging.error("Couldn't attach bootloader at %s", args.oak_ip)
        return 1
    logging.info("Attached. bootloader version: %s",
                 bl.getVersion())

    cfg = bl.readConfig()
    logging.info("Current config: network timeout=%s, watchdog timeout=%s",
                 getattr(cfg, "getNetworkTimeout", lambda: "?")(),
                 getattr(cfg, "getAppMemSize", lambda: "?")())
    cfg.setNetworkTimeout(timedelta(seconds=args.timeout_sec))
    ok, msg = bl.flashConfig(cfg)
    logging.info("flashConfig(timeout=%ds): ok=%s msg=%r", args.timeout_sec, ok, msg)

    if args.flash_bootloader:
        logging.info("Upgrading bootloader...")
        ok2, msg2 = bl.flashBootloader(
            lambda pct: logging.info("bl flash: %.1f%%", pct * 100))
        logging.info("flashBootloader: ok=%s msg=%r", ok2, msg2)

    if args.factory_reset:
        logging.info("Clearing app flash partition...")
        try:
            ok3, msg3 = bl.flashClear()
            logging.info("flashClear: ok=%s msg=%r", ok3, msg3)
        except Exception as e:
            logging.warning("flashClear failed: %s", e)

    return 0


if __name__ == "__main__":
    sys.exit(main())
