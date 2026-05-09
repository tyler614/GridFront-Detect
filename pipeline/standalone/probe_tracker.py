"""Host-mode probe: run the standalone tracker pipeline directly on the OAK
without flashing. Crashes/errors surface as Python exceptions or device logs
instead of being swallowed by the silent flash failure mode.

The OAK currently has a (broken) flashed app, so this script first wipes
the flash via flashClear() — same trick as flash_recover.py — then uploads
the pipeline in host mode and watches the Script node's node.warn output.

Usage (with .venv2x active, OAK on laptop's PoE injector, power-cycled):
    python -m pipeline.standalone.probe_tracker
"""
from __future__ import annotations
import json
import logging
import sys
import time
from pathlib import Path

import depthai as dai

from pipeline.standalone.build_standalone_v2 import (
    build_pipeline, _extract_pose_and_zones,
)

REPO = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)


def attach_bootloader(ip: str, deadline: float) -> dai.DeviceBootloader | None:
    info = dai.DeviceInfo(ip)
    tries = 0
    while time.time() < deadline:
        tries += 1
        try:
            bl = dai.DeviceBootloader(info)
            logger.info("Attached bootloader on try #%d", tries)
            return bl
        except Exception:
            pass
    logger.error("Could not attach bootloader after %d tries", tries)
    return None


def attach_device(pipeline: dai.Pipeline, ip: str, deadline: float) -> dai.Device | None:
    info = dai.DeviceInfo(ip)
    tries = 0
    last_err = None
    while time.time() < deadline:
        tries += 1
        try:
            return dai.Device(pipeline, info)
        except Exception as e:
            last_err = e
    logger.error("Could not attach device after %d tries. Last err: %s", tries, last_err)
    return None


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    with open(REPO / "models/gridfront-scout-v1.json") as f:
        meta = json.load(f)
    with open(REPO / "config.json") as f:
        cfg = json.load(f)
    pos_x, pos_y, yaw_deg, zones, mlen, mwid = _extract_pose_and_zones(cfg, "cam-0")

    pipeline = build_pipeline(
        blob_path=REPO / "models/gridfront-scout-v1.blob",
        model_meta=meta,
        dest_ip="169.254.1.56",
        dest_port=5556,
        config_port=5557,
        camera_id="cam-0",
        pos_x=pos_x, pos_y=pos_y, yaw_deg=yaw_deg, zones=zones,
        machine_len_m=mlen, machine_wid_m=mwid,
        units="m", fps=15, target_fps=10.0,
        calib_json=REPO / "calib_oak.json",
        allow_classes={"person"},
    )

    # Tap nn.out and tracker.out so we can count what each emits without
    # changing the standalone topology. Walk the pipeline graph to find
    # nodes by class so we don't depend on createX returning order.
    nn_node = None
    tracker_node = None
    for node in pipeline.getAllNodes():
        cls = node.__class__.__name__
        if cls == "YoloSpatialDetectionNetwork":
            nn_node = node
        elif cls == "ObjectTracker":
            tracker_node = node
    if nn_node is None or tracker_node is None:
        logger.error("Could not find NN/Tracker nodes (got NN=%s tracker=%s)",
                     nn_node, tracker_node)
        return 1

    xout_nn = pipeline.createXLinkOut()
    xout_nn.setStreamName("probe_nn")
    nn_node.out.link(xout_nn.input)

    xout_tk = pipeline.createXLinkOut()
    xout_tk.setStreamName("probe_tracklets")
    tracker_node.out.link(xout_tk.input)

    logger.warning("Power-cycle the OAK now. Spam-attaching bootloader...")
    bl = attach_bootloader("169.254.1.222", time.time() + 180)
    if bl is None:
        return 1
    try:
        ok, msg = bl.flashClear()
        logger.info("flashClear ok=%s msg=%s", ok, msg)
    except Exception:
        logger.exception("flashClear raised — continuing")
    try: del bl
    except Exception: pass
    time.sleep(2)

    logger.warning("Re-attaching as Device for host-mode pipeline upload...")
    device = attach_device(pipeline, "169.254.1.222", time.time() + 90)
    if device is None:
        return 1

    logger.info("Pipeline UPLOAD SUCCESS. Watching device logs for 25s ...")
    device.setLogLevel(dai.LogLevel.WARN)
    device.setLogOutputLevel(dai.LogLevel.WARN)
    log_buf: list[str] = []
    def on_log(msg):
        log_buf.append(f"[{msg.level.name} {msg.nodeIdName}] {msg.payload}")
    device.addLogCallback(on_log)

    nn_q = device.getOutputQueue("probe_nn", maxSize=4, blocking=False)
    tk_q = device.getOutputQueue("probe_tracklets", maxSize=4, blocking=False)

    nn_count = 0
    nn_total_dets = 0
    tk_count = 0
    tk_total_tracklets = 0
    deadline = time.time() + 25
    last_summary = time.time()
    while time.time() < deadline:
        nn_msg = nn_q.tryGet()
        if nn_msg is not None:
            nn_count += 1
            nn_total_dets += len(nn_msg.detections)
        tk_msg = tk_q.tryGet()
        if tk_msg is not None:
            tk_count += 1
            tk_total_tracklets += len(tk_msg.tracklets)

        now = time.time()
        if now - last_summary >= 2.0:
            print(f"[PROBE] nn_msgs={nn_count} dets={nn_total_dets} | "
                  f"tracklet_msgs={tk_count} tracklets={tk_total_tracklets}",
                  flush=True)
            last_summary = now
        if log_buf:
            for line in log_buf:
                print(line, flush=True)
            log_buf.clear()
        time.sleep(0.05)

    print(f"[PROBE FINAL] nn_msgs={nn_count} dets={nn_total_dets} | "
          f"tracklet_msgs={tk_count} tracklets={tk_total_tracklets}",
          flush=True)
    device.close()
    logger.info("Probe complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
