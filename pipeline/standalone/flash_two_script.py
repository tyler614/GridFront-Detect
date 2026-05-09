"""Two-Script architecture test for OAK-D Pro W PoE standalone.

Hypothesis: Camera + Script-on-LEON_CSS crashes standalone. But we need
LEON_CSS for UDP (LEON_MSS has no network stack). Solution: split into two
Script nodes.

  Camera → Script_MSS (no socket import; reads frames, emits counter)
           → Script_CSS (no camera input; reads counter, sends UDP)

Each node stays on a processor that can handle its job, no conflict.

Usage: .venv2x/Scripts/python.exe -m pipeline.standalone.flash_two_script
"""
from __future__ import annotations

import logging
import sys
import time

import depthai as dai


# Script_MSS: just drains camera frames so the cam pipeline has a consumer.
# Deliberately NO `import socket` — LEON_MSS has no ethernet stack.
MSS_SRC = r"""
while True:
    frame = node.io["frame"].get()
"""

# Script_CSS: independent UDP heartbeat, no input link.
# Mirrors the known-working single-Script heartbeat pattern.
CSS_SRC = r"""
import socket
import time

DEST_IP   = "169.254.1.56"
DEST_PORT = 5556

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    sock.sendto(b'boot two_script_v3', (DEST_IP, DEST_PORT))
except Exception as e:
    node.warn("boot err: " + str(e))

seq = 0
while True:
    seq = seq + 1
    try:
        sock.sendto(b'hb two_script_v3 ' + str(seq).encode(), (DEST_IP, DEST_PORT))
    except Exception as e:
        node.warn("sendto err: " + str(e))
    time.sleep(0.5)
"""


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    oak_ip = "169.254.1.222"

    p = dai.Pipeline()

    cam = p.createColorCamera()
    cam.setBoardSocket(dai.CameraBoardSocket.CAM_A)
    cam.setResolution(dai.ColorCameraProperties.SensorResolution.THE_1080_P)
    cam.setPreviewSize(128, 128)
    cam.setInterleaved(False)
    cam.setFps(5)

    script_mss = p.createScript()
    # Default processor = LEON_MSS; no socket import so it can't crash on
    # network-stack init.
    script_mss.setScript(MSS_SRC)

    script_css = p.createScript()
    script_css.setProcessor(dai.ProcessorType.LEON_CSS)
    script_css.setScript(CSS_SRC)

    # Camera → Script_MSS (frame drain). Script_MSS and Script_CSS run
    # completely independently — no inter-Script link.
    cam.preview.link(script_mss.inputs["frame"])
    script_mss.inputs["frame"].setBlocking(False)
    script_mss.inputs["frame"].setQueueSize(1)

    info = dai.DeviceInfo(oak_ip)
    logging.info("Attaching bootloader at %s...", oak_ip)
    bl = None
    deadline = time.time() + 120
    while time.time() < deadline and bl is None:
        try:
            bl = dai.DeviceBootloader(info)
        except Exception:
            pass
    if bl is None:
        logging.error("Couldn't attach bootloader")
        return 1
    logging.info("attached bl=%s", bl.getVersion())

    logging.info("Flashing two-script pipeline...")
    ok, msg = bl.flash(lambda pct: logging.info("flash: %.1f%%", pct * 100),
                       p, compress=True,
                       applicationName="gridfront-two-script")
    logging.info("Flash done: ok=%s msg=%r", ok, msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
