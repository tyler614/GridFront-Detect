"""Recover an OAK whose flashed app is crash-rebooting.

When a bad standalone app is on the OAK, every power-cycle bounces it
between bootloader and crashing-app every few seconds. This kills any
flash mid-stream. Fix: spam-attach bootloader, immediately call
flashClear() to wipe the bad app, THEN flash the new pipeline.

Usage (from detect.gridfront.io root, with .venv2x active):
    python -m pipeline.standalone.flash_recover \
        --blob models/yolov6nr1-coco.blob \
        --meta models/yolov6nr1-coco.json \
        --dap pipeline/standalone/yolov6nr1-coco.dap
"""
from __future__ import annotations
import argparse
import logging
import sys
import time
from pathlib import Path

import depthai as dai

from pipeline.standalone.build_standalone_v2 import (
    build_pipeline, _extract_pose_and_zones,
    _discover_oak_mxid, _serial_from_mxid,
)
import json

logger = logging.getLogger(__name__)
REPO = Path(__file__).resolve().parents[2]


def attach(oak_ip: str, deadline: float) -> dai.DeviceBootloader | None:
    info = dai.DeviceInfo(oak_ip)
    tries = 0
    while time.time() < deadline:
        tries += 1
        try:
            bl = dai.DeviceBootloader(info)
            logger.info("Attached bootloader on try #%d", tries)
            return bl
        except Exception:
            pass
    logger.error("Could not attach bootloader at %s after %d tries", oak_ip, tries)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--oak-ip",     default="169.254.1.222")
    ap.add_argument("--blob",       required=True)
    ap.add_argument("--meta",       required=True)
    ap.add_argument("--dap",        required=True)
    ap.add_argument("--config",     default=str(REPO / "config.json"))
    ap.add_argument("--camera-id",  default=None,
                    help="OPTIONAL manual override for the baked camera identity. When "
                         "omitted (the default), the GridFront serial (last 6 chars of "
                         "the connected OAK's MXID, uppercased) is derived at flash time "
                         "and baked — same default-derives-serial behavior as the "
                         "production build_standalone_v2 path. Do NOT hardcode cam-0.")
    ap.add_argument("--dest-ip",    default="169.254.1.56")
    ap.add_argument("--dest-port",  type=int, default=5556)
    ap.add_argument("--config-port",type=int, default=5557)
    ap.add_argument("--units",      default="m")
    ap.add_argument("--fps",        type=int, default=15)
    ap.add_argument("--target-fps", type=float, default=10.0)
    ap.add_argument("--calib",      default=str(REPO / "calib_oak.json"))
    ap.add_argument("--only-classes", default="",
                    help="Comma-separated class names to keep (e.g. 'person').")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    with open(args.meta) as f:
        meta = json.load(f)
    with open(args.config) as f:
        cfg = json.load(f)
    # Pose key: only valid when an explicit id selects a config entry. When
    # deriving the serial there is no slot key, so pose falls back to empty
    # (the tablet pushes the real pose over :5557 on boot).
    pose_key = args.camera_id if args.camera_id else ""
    pos_x, pos_y, yaw_deg, pitch_deg, zones, mlen, mwid = _extract_pose_and_zones(cfg, pose_key)

    allow_classes: set[str] | None = None
    if args.only_classes.strip():
        allow_classes = {c.strip() for c in args.only_classes.split(",") if c.strip()}
        logger.info("Class filter: only %s", sorted(allow_classes))

    logger.warning("============================================================")
    logger.warning("  Power-cycle the OAK now. Spam-attaching for 180s...")
    logger.warning("============================================================")

    deadline = time.time() + 180

    # Phase 0: derive the GridFront serial from the connected device BEFORE
    # building (so the baked __CAMERA_ID__ is the serial, not a slot id). This
    # mirrors build_standalone_v2's default-derives-serial flash path so that if
    # flash_recover is ever used to re-bake a PRODUCTION camera it stamps the
    # serial, not cam-0. A manual --camera-id still overrides verbatim. Discovery
    # is local XLink/Ethernet enumeration — no network/platform call.
    camera_mxid = ""
    camera_id = args.camera_id
    if camera_id is None:
        mxid, _bl0 = _discover_oak_mxid(args.oak_ip, timeout_s=60.0)
        if _bl0 is None or not mxid:
            logger.error("Could not discover OAK MXID at %s to derive the serial. "
                         "Power-cycle into BOOTLOADER, or pass --camera-id to override.",
                         args.oak_ip)
            return 1
        camera_mxid = mxid
        camera_id = _serial_from_mxid(mxid)
        logger.info("Derived GridFront serial: GF_SERIAL=%s (GF_MXID=%s)", camera_id, camera_mxid)
        try: del _bl0   # drop discovery handle; phase-1 attach() re-grabs the bootloader
        except Exception: pass
        time.sleep(2)
    else:
        logger.info("Manual --camera-id override: baking id=%s", camera_id)

    pipeline = build_pipeline(
        blob_path=Path(args.blob), model_meta=meta,
        dest_ip=args.dest_ip, dest_port=args.dest_port,
        config_port=args.config_port, camera_id=camera_id, camera_mxid=camera_mxid,
        pos_x=pos_x, pos_y=pos_y, yaw_deg=yaw_deg, pitch_deg=pitch_deg, zones=zones,
        machine_len_m=mlen, machine_wid_m=mwid,
        units=args.units, fps=args.fps, target_fps=args.target_fps,
        calib_json=Path(args.calib), allow_classes=allow_classes,
    )

    # Phase 1: clear the broken app so OAK stops re-rebooting.
    bl = attach(args.oak_ip, deadline)
    if bl is None:
        return 1
    try:
        logger.info("Clearing existing flashed app...")
        ok, msg = bl.flashClear()
        if ok:
            logger.info("flashClear ok")
        else:
            logger.warning("flashClear returned: %s — continuing anyway", msg)
    except Exception:
        logger.exception("flashClear raised — continuing anyway")

    # The flashClear above usually drops the bootloader handle. Re-attach.
    try:
        del bl
    except Exception:
        pass
    time.sleep(2)

    # Phase 2: power-cycle (or wait) and re-attach for the real flash.
    deadline2 = time.time() + 120
    logger.warning("Re-attaching bootloader for flash. Power-cycle if needed...")
    bl = attach(args.oak_ip, deadline2)
    if bl is None:
        logger.error("Could not re-attach after clear")
        return 1

    progress = lambda pct: logger.info("flash progress: %.1f%%", pct * 100.0)
    last_err: Exception | None = None
    for attempt in range(1, 6):
        try:
            logger.info("Flash attempt %d (compressed): %s ...",
                        attempt, Path(args.blob).name)
            ok, msg = bl.flash(progress, pipeline, compress=True,
                               applicationName="gridfront-scout")
            if not ok:
                logger.error("Flash failed: %s", msg)
                last_err = RuntimeError(msg)
            else:
                logger.info("Flash complete. Power-cycle the camera to boot standalone.")
                return 0
        except Exception as e:
            last_err = e
            logger.warning("Flash attempt %d crashed: %s", attempt, e)

        try: del bl
        except Exception: pass
        time.sleep(3)
        logger.warning("Re-attaching for retry %d ...", attempt + 1)
        bl = attach(args.oak_ip, time.time() + 90)
        if bl is None:
            break

    logger.error("All flash attempts exhausted. Last error: %s", last_err)
    return 1


if __name__ == "__main__":
    sys.exit(main())
