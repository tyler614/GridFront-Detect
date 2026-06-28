"""DepthAI 3.x port of flash_cam_minimal.

If THIS boots to FLASH_BOOTED with UDP arriving on the tablet, then the
standalone-with-camera crash was a 2.x bug and we proceed to port the
full pipeline. If it still crashes, we have a hardware/firmware fault
that neither SDK version can work around.

Usage: .venv3x/Scripts/python.exe -m pipeline.standalone.flash_cam_minimal_v3
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
    sock.sendto(b'boot cam_min_v3', (DEST_IP, DEST_PORT))
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
    try:
        sock.sendto(b'hb cam_min_v3 ' + str(seq).encode() + b' f=' + got.encode(),
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

    script = p.create(dai.node.Script)
    script.setProcessor(dai.ProcessorType.LEON_CSS)
    script.setScript(HEARTBEAT
                     .replace("__DEST_IP__", dest_ip)
                     .replace("__DEST_PORT__", str(dest_port)))

    cam = p.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_A)
    preview = cam.requestOutput((512, 288), dai.ImgFrame.Type.BGR888p, fps=15)
    preview.link(script.inputs["frame"])
    script.inputs["frame"].setBlocking(False)
    script.inputs["frame"].setMaxSize(1)

    # 3.x `DeviceInfo(ip)` is just a placeholder — DeviceBootloader needs a
    # DeviceInfo returned from discovery, otherwise it rejects the attach with
    # "Device not in UNBOOTED/BOOTLOADER/FLASH_BOOTED state".
    logging.info("Discovering OAK at %s...", oak_ip)
    bl = None
    deadline = time.time() + 60
    while time.time() < deadline and bl is None:
        for d in dai.Device.getAllAvailableDevices():
            if d.name == oak_ip:
                try:
                    bl = dai.DeviceBootloader(d)
                    logging.info("Attached (state=%s bl=%s)", d.state, bl.getVersion())
                except Exception as e:
                    logging.info("attach failed: %s", e)
                break
        if bl is None:
            time.sleep(2)
    if bl is None:
        logging.error("Couldn't find/attach OAK at %s within 60s.", oak_ip)
        return 1

    logging.info("Flashing cam_minimal_v3 (DepthAI %s)...", dai.__version__)
    ok, msg = bl.flash(lambda pct: logging.info("flash: %.1f%%", pct * 100),
                       p, compress=True, applicationName="gridfront-cam-min-v3")
    logging.info("Flash done: ok=%s msg=%r", ok, msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
