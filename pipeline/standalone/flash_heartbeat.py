"""Minimal standalone pipeline: Script-only UDP heartbeat.

Proves the network+boot path in isolation. No cameras, no NN, no stereo.
If heartbeats arrive on the tablet, the OAK is booting its flashed app and
the Script-node UDP stack works — and any silence from the full pipeline is
a fault inside cameras / stereo / NN, not the boot chain.

Usage (OAK in BOOTLOADER state, either plugged into laptop or tablet):

    .venv2x/Scripts/python.exe -m pipeline.standalone.flash_heartbeat \\
        --dest-ip 169.254.1.56 --dest-port 5556
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

import depthai as dai

logger = logging.getLogger(__name__)

HEARTBEAT_SRC = r"""
import socket
import time

DEST_IP   = "__DEST_IP__"
DEST_PORT = __DEST_PORT__

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
seq = 0
while True:
    seq += 1
    payload = b'hb ' + str(seq).encode()
    try:
        sock.sendto(payload, (DEST_IP, DEST_PORT))
    except Exception as e:
        node.warn("sendto err: " + str(e))
    time.sleep(0.5)
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dest-ip",   default="169.254.1.56")
    ap.add_argument("--dest-port", type=int, default=5556)
    ap.add_argument("--oak-ip",    default="169.254.1.222")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    p = dai.Pipeline()
    script = p.createScript()
    # Leon CSS runs the Ethernet stack on OAK-D PoE. Script defaults to MSS,
    # which has no network access — pin to CSS so socket.sendto() reaches
    # the wire. Discovered empirically: `import socket` alone crashes the
    # script VM when it's running on MSS.
    script.setProcessor(dai.ProcessorType.LEON_CSS)
    src = HEARTBEAT_SRC.replace("__DEST_IP__", args.dest_ip) \
                       .replace("__DEST_PORT__", str(args.dest_port))
    script.setScript(src)

    logger.info("Spamming DeviceBootloader attach at %s for up to 120s...", args.oak_ip)
    info = dai.DeviceInfo(args.oak_ip)
    bl = None
    deadline = time.time() + 120
    tries = 0
    while time.time() < deadline and bl is None:
        tries += 1
        try:
            bl = dai.DeviceBootloader(info)
            logger.info("Attached bootloader on try #%d", tries)
        except Exception as e:
            if tries % 50 == 0:
                logger.info("attach try #%d still failing (%s)", tries, type(e).__name__)
    if bl is None:
        logger.error("Never caught bootloader window after %d tries.", tries)
        return 1

    if info is None:
        logger.error("OAK not found in BOOTLOADER state at %s.", args.oak_ip)
        return 1

    try:
        # First, lengthen the network timeout so we don't race future flashes.
        try:
            from datetime import timedelta
            cfg = bl.readConfig()
            cfg.setNetworkTimeout(timedelta(seconds=30))
            ok_c, msg_c = bl.flashConfig(cfg)
            logger.info("Network timeout restored to 30s: ok=%s msg=%r", ok_c, msg_c)
        except Exception as e:
            logger.warning("Couldn't restore network timeout: %s", e)
        logger.info("Flashing heartbeat pipeline...")
        ok, msg = bl.flash(lambda pct: logger.info("flash progress: %.1f%%", pct*100),
                           p, compress=True, applicationName="gridfront-heartbeat")
        if not ok:
            logger.error("Flash failed: %s", msg); return 1
        logger.info("Flash complete. Power-cycle the OAK.")
    except Exception:
        logger.exception("Flash crashed"); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
