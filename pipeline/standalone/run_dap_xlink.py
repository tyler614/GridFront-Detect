"""Run the flashed .dap pipeline over XLink (host connection).

The standalone flash keeps landing in BOOTLOADER state, which means the
app boots, something crashes, and the device watchdog reverts. In
flashed mode those crash logs go nowhere — there's no host attached.

This script loads the same .dap into a live XLink session so Script
node `node.warn()` / `node.error()` output streams back to the host.
Whatever silently kills standalone boot will show up here.

Usage:
    .venv2x/Scripts/python.exe -m pipeline.standalone.run_dap_xlink
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import depthai as dai

from pipeline.standalone.build_standalone_v2 import (
    build_pipeline,
    _extract_pose_and_zones,
)

REPO = Path(__file__).resolve().parents[2]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--blob", default=str(REPO / "models" / "yolov8n-coco.blob"))
    ap.add_argument("--meta", default=str(REPO / "models" / "yolov8n-coco.json"))
    ap.add_argument("--calib", default=str(REPO / "calib_oak.json"))
    ap.add_argument("--config", default=str(REPO / "config.json"))
    # BENCH-ONLY: this tool runs the pipeline over XLink (host-attached) and
    # NEVER flashes, so the baked id never reaches a production camera. The
    # default is a non-serial BENCH placeholder, NOT a GridFront serial — pass
    # --camera-id explicitly if a specific id is needed for a bench test.
    ap.add_argument("--camera-id", default="BENCH-XLINK")
    ap.add_argument("--dest-ip", default="169.254.1.56")
    ap.add_argument("--oak-ip", default="169.254.1.222")
    ap.add_argument("--duration", type=float, default=30.0)
    args = ap.parse_args()

    with open(args.meta) as f:
        meta = json.load(f)
    with open(args.config) as f:
        cfg = json.load(f)
    pos_x, pos_y, yaw_deg, zones, mlen, mwid = _extract_pose_and_zones(cfg, args.camera_id)
    print(f"Pose=({pos_x},{pos_y}) yaw={yaw_deg} zones={len(zones)} machine={mlen}x{mwid}")

    pipeline = build_pipeline(
        blob_path=Path(args.blob), model_meta=meta,
        dest_ip=args.dest_ip, dest_port=5556, config_port=5557,
        camera_id=args.camera_id,
        pos_x=pos_x, pos_y=pos_y, yaw_deg=yaw_deg, zones=zones,
        machine_len_m=mlen, machine_wid_m=mwid,
        units="m", fps=15, target_fps=10.0, calib_json=Path(args.calib),
    )

    info = dai.DeviceInfo(args.oak_ip)
    print(f"Attaching to {args.oak_ip} (XLink, pipeline streamed)...")
    with dai.Device(pipeline, info) as dev:
        dev.setLogLevel(dai.LogLevel.TRACE)
        dev.setLogOutputLevel(dai.LogLevel.TRACE)

        def on_log(msg):
            lvl = getattr(msg, "level", "?")
            payload = getattr(msg, "payload", str(msg))
            print(f"  [{lvl}] {payload}")

        dev.addLogCallback(on_log)

        print("Connected. Tailing device logs...\n")
        t0 = time.time()
        while time.time() - t0 < args.duration:
            time.sleep(0.2)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
