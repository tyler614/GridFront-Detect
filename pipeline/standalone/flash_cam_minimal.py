"""Minimal cam+Script standalone pipeline — verify cam init without crashing.

Previous attempts used `script.setProcessor(LEON_CSS)` AND piped `cam.preview`
into the Script node. Both are anti-patterns:
  - LEON_CSS hosts the PoE network stack. Pinning Script there while a camera
    is running crashes the device at pipeline init.
  - `cam.preview` at 15 fps into a Script input is a firehose the docs warn
    explicitly against.

This version keeps the camera in the pipeline (so we prove camera init works)
but deliberately leaves it UNLINKED. Script uses the default processor and
just sends UDP heartbeats. If UDP arrives, the crash was the LEON_CSS pin.

Usage: .venv2x/Scripts/python.exe -m pipeline.standalone.flash_cam_minimal
"""
from __future__ import annotations

import logging
import sys
import time

import depthai as dai


HEARTBEAT = r"""
import socket
import time

DEST_IP   = "__DEST_IP__"
DEST_PORT = __DEST_PORT__

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    sock.sendto(b'boot cam_min', (DEST_IP, DEST_PORT))
except Exception as e:
    node.warn("boot err: " + str(e))

seq = 0
while True:
    seq += 1
    # Drain the frame queue so it doesn't stall the camera pipeline.
    try:
        frame = node.io["frame"].tryGet()
    except Exception:
        frame = None
    got = "1" if frame is not None else "0"
    try:
        sock.sendto(b'hb cam_min ' + str(seq).encode() + b' f=' + got.encode(),
                    (DEST_IP, DEST_PORT))
    except Exception as e:
        node.warn("sendto err: " + str(e))
    time.sleep(0.5)
"""


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    dest_ip = "169.254.1.56"
    dest_port = 5556
    oak_ip = "169.254.1.222"

    p = dai.Pipeline()

    # Key fix: do NOT pin Script to LEON_CSS. LEON_CSS hosts the PoE network
    # stack; running Script there while the camera pipeline is active crashes
    # standalone. Official Script examples use the default (LEON_MSS), and
    # UDP is reachable from there via the network stack running on LEON_CSS.
    script = p.createScript()
    script.setScript(HEARTBEAT
                     .replace("__DEST_IP__", dest_ip)
                     .replace("__DEST_PORT__", str(dest_port)))

    # No camera: isolating whether LEON_MSS (default) supports UDP sockets.
    # An older working-memory doc said MSS has no ethernet stack, but today's
    # research says official examples use the default. Test empirically.

    info = dai.DeviceInfo(oak_ip)
    logging.info("Spamming DeviceBootloader attach at %s...", oak_ip)
    bl = None
    deadline = time.time() + 120
    while time.time() < deadline and bl is None:
        try:
            bl = dai.DeviceBootloader(info)
        except Exception:
            pass
    if bl is None:
        logging.error("Couldn't attach bootloader.")
        return 1

    logging.info("Flashing cam_minimal...")
    ok, msg = bl.flash(lambda pct: logging.info("flash: %.1f%%", pct * 100),
                       p, compress=True, applicationName="gridfront-cam-min")
    logging.info("Flash done: ok=%s msg=%r", ok, msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
