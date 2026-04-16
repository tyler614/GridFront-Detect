"""Build a standalone DepthAI pipeline and (optionally) flash it.

Usage:
    # Dry-run: build the pipeline graph + verify, do NOT flash:
    python -m pipeline.standalone.build_standalone --dry-run

    # Flash the pipeline to the connected OAK-D's onboard flash. After
    # this, power-cycling the camera with no host attached boots the
    # baked pipeline and starts broadcasting UDP to DEST_IP:DEST_PORT.
    python -m pipeline.standalone.build_standalone \\
        --dest-ip 192.168.68.56 --dest-port 5556 --confirm-flash

WHY THIS IS A PROTOTYPE: standalone bake is destructive — the camera
won't reconnect to the host SDK in the same way until you reflash with
the regular pipeline. NEVER run --confirm-flash on the production OAK
without a recovery path. Default behaviour is dry-run for safety.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

import depthai as dai

from pipeline.model_registry import COCO_LABELS, get_model
from pipeline.standalone.script_runtime import SCRIPT_SOURCE

# Standalone needs a model whose weights are pullable by the camera at
# build time — use the HubAI-hosted YOLO that the live pipeline already
# runs. Local-blob models would require shipping the .blob into flash via
# the NNArchive path; punt that until standalone basics are validated.
_STANDALONE_MODEL_ID = "yolov6n-coco"

logger = logging.getLogger(__name__)

# Mirror of _SAFETY_LABELS in pipeline/oak_driver.py — kept as COCO
# indices so the Script node can do an O(1) set lookup per detection.
_SAFETY_LABEL_NAMES = {"person", "bicycle", "car", "motorbike", "bus", "truck"}


def _safety_indices(labels: list[str]) -> list[int]:
    return sorted(i for i, name in enumerate(labels) if name in _SAFETY_LABEL_NAMES)


def _bake_script(
    *,
    dest_ip: str,
    dest_port: int,
    danger_m: float,
    warning_m: float,
    half_length_m: float,
    half_width_m: float,
    labels: list[str],
    units: str,
) -> str:
    """Substitute build-time config into the Script node source."""
    src = SCRIPT_SOURCE
    repl = {
        "__DEST_IP__":             dest_ip,
        "__DEST_PORT__":           str(dest_port),
        "__DANGER_M__":            f"{danger_m:.3f}",
        "__WARNING_M__":           f"{warning_m:.3f}",
        "__HALF_LENGTH_M__":       f"{half_length_m:.3f}",
        "__HALF_WIDTH_M__":        f"{half_width_m:.3f}",
        "__LABELS_JSON__":         json.dumps(labels),
        "__SAFETY_INDICES_JSON__": "set(" + json.dumps(_safety_indices(labels)) + ")",
        "__UNITS__":               units,
    }
    for k, v in repl.items():
        src = src.replace(k, v)
    return src


def build_pipeline(
    *,
    dest_ip: str,
    dest_port: int,
    danger_m: float,
    warning_m: float,
    half_length_m: float,
    half_width_m: float,
    units: str,
    fps: int,
) -> dai.Pipeline:
    """Construct the standalone pipeline graph.

    Mirrors the live pipeline in oak_driver.py, but replaces the host
    XLink output with a Script node that classifies + UDP-broadcasts.
    """
    p = dai.Pipeline()

    cam_rgb = p.create(dai.node.Camera).build()
    mono_l = p.create(dai.node.MonoCamera)
    mono_r = p.create(dai.node.MonoCamera)
    mono_l.setBoardSocket(dai.CameraBoardSocket.CAM_B)
    mono_r.setBoardSocket(dai.CameraBoardSocket.CAM_C)

    stereo = p.create(dai.node.StereoDepth)
    mono_l.out.link(stereo.left)
    mono_r.out.link(stereo.right)

    nn = p.create(dai.node.SpatialDetectionNetwork)
    model = get_model(_STANDALONE_MODEL_ID)
    if model is None or not model.slug:
        raise RuntimeError(
            f"Standalone build needs a HubAI-resolvable model; '{_STANDALONE_MODEL_ID}'"
            " is missing or has no slug. Update model_registry."
        )
    nn.build(cam_rgb, stereo, model.slug, fps=fps)
    labels = list(model.classes) if model.classes else COCO_LABELS

    script = p.create(dai.node.Script)
    script.setScript(_bake_script(
        dest_ip=dest_ip,
        dest_port=dest_port,
        danger_m=danger_m,
        warning_m=warning_m,
        half_length_m=half_length_m,
        half_width_m=half_width_m,
        labels=labels,
        units=units,
    ))
    nn.out.link(script.inputs["nn"])

    return p


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest-ip",       default="192.168.68.56")
    parser.add_argument("--dest-port",     type=int,   default=5556)
    parser.add_argument("--danger-m",      type=float, default=3.0)
    parser.add_argument("--warning-m",     type=float, default=6.0)
    parser.add_argument("--half-length-m", type=float, default=4.2)
    parser.add_argument("--half-width-m",  type=float, default=1.25)
    parser.add_argument("--units",         default="m", choices=("m", "ft"))
    parser.add_argument("--fps",           type=int, default=15)
    parser.add_argument("--dry-run",       action="store_true",
                        help="Build the pipeline and exit; do not flash.")
    parser.add_argument("--confirm-flash", action="store_true",
                        help="ACK that flashing the OAK is destructive. Required.")
    parser.add_argument("--oak-ip", default="169.254.1.222",
                        help="Link-local IP of the PoE OAK to flash.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    pipeline = build_pipeline(
        dest_ip=args.dest_ip,
        dest_port=args.dest_port,
        danger_m=args.danger_m,
        warning_m=args.warning_m,
        half_length_m=args.half_length_m,
        half_width_m=args.half_width_m,
        units=args.units,
        fps=args.fps,
    )
    logger.info("Pipeline built. Targeting %s:%d, danger=%.1fm warning=%.1fm",
                args.dest_ip, args.dest_port, args.danger_m, args.warning_m)

    if args.dry_run or not args.confirm_flash:
        logger.info("Dry-run — not flashing. Re-run with --confirm-flash to bake.")
        return 0

    # Flash the assembled pipeline to onboard flash via the bootloader.
    # NB: this competes with the running Flask pipeline for the device —
    # stop the Flask server first or the connect() below will fail.
    logger.warning("Flashing standalone pipeline to OAK-D onboard flash...")
    try:
        # v3 DeviceBootloader accepts an IP/name string directly — no
        # DeviceInfo lookup needed for a known PoE address.
        logger.info("Targeting OAK at %s", args.oak_ip)
        bootloader = dai.DeviceBootloader(args.oak_ip)
        progress = lambda p: logger.info("flash progress: %.1f%%", p * 100.0)
        success, msg = bootloader.flash(progress, pipeline)
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
