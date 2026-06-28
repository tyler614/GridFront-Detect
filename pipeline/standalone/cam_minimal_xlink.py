"""Run the exact cam_minimal pipeline over XLink with log streaming.

If this runs without crashing (UDP won't arrive — laptop isn't the tablet IP
— but Script heartbeat logs via node.warn will show), then the pipeline graph
itself is fine and the flash-boot path is specifically what's broken.
"""
from __future__ import annotations

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
    sock.sendto(b'boot cam_min', (DEST_IP, DEST_PORT))
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
    node.warn("HB " + str(seq) + " f=" + got)
    try:
        sock.sendto(b'hb cam_min ' + str(seq).encode() + b' f=' + got.encode(),
                    (DEST_IP, DEST_PORT))
    except Exception as e:
        node.warn("sendto err: " + str(e))
    time.sleep(0.5)
"""


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    oak_ip = "169.254.1.222"

    p = dai.Pipeline()
    script = p.createScript()
    script.setScript(HEARTBEAT)

    cam = p.createColorCamera()
    cam.setBoardSocket(dai.CameraBoardSocket.CAM_A)
    cam.setResolution(dai.ColorCameraProperties.SensorResolution.THE_1080_P)
    cam.setPreviewSize(128, 128)
    cam.setInterleaved(False)
    cam.setFps(5)
    cam.preview.link(script.inputs["frame"])
    script.inputs["frame"].setBlocking(False)
    script.inputs["frame"].setQueueSize(1)

    info = dai.DeviceInfo(oak_ip)
    logging.info("Attaching Device in XLink mode...")
    with dai.Device(p, info) as dev:
        dev.setLogLevel(dai.LogLevel.TRACE)
        dev.setLogOutputLevel(dai.LogLevel.TRACE)

        def on_log(m):
            lvl = getattr(m, "level", "?")
            payload = getattr(m, "payload", str(m))
            print(f"  [{lvl}] {payload}")

        dev.addLogCallback(on_log)
        logging.info("Connected. Streaming logs for 15s...")
        t0 = time.time()
        while time.time() - t0 < 15:
            time.sleep(0.2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
