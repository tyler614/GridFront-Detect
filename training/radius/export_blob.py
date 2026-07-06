"""Export a trained Radius checkpoint to an RVC2 blob + registry sidecar.

Path: YOLOv6 .pt -> ONNX (v6 deploy export) -> blob via Luxonis tools
(legacy pipeline). Requirements pinned by research:
  * OpenVINO 2021.4 (2022.1 measured slightly slower on RVC2)
  * 6 shaves (stereo + encoder share SHAVEs in the full pipeline)
  * superblob OFF (superblobs fail on DepthAI 2.x with BlobReader error)
  * input 640x384 to match the deployed preview

Easiest reliable route: upload the .pt at https://tools.luxonis.com
(select YOLOv6, shape 640 384, RVC2) — it performs the v5-style head
re-export the DepthAI 2.x YoloSpatialDetectionNetwork parser needs.
This script automates the same via the luxonis/tools CLI if installed:
    pip install "tools @ git+https://github.com/luxonis/tools"

Usage:
    python export_blob.py runs/radius_s2/weights/best_ckpt.pt --version v1
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
MODELS = REPO / "models"

RADIUS_CLASSES = [
    "person", "excavator", "wheel-loader", "dozer", "crane",
    "dump-truck", "grader", "compactor", "cone",
]


def main(ckpt: Path, version: str, w: int, h: int, shaves: int) -> None:
    out_dir = HERE / "export" / f"radius-{version}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Path: YOLOv6's own ONNX exporter (no mmcv) -> blobconverter cloud
    # compile (FP16, OpenVINO 2021.4). The luxonis `tools` CLI needs mmcv,
    # which does not build on Windows — this route is dependency-light and
    # headless. YOLOv6 R2+ heads are anchor-free decoded outputs; DepthAI
    # 2.x YoloSpatialDetectionNetwork parses them with anchors=[] metadata
    # (same as the zoo yolov6n blob). BENCH-VERIFY detections before flash.
    y6 = HERE / "third_party" / "YOLOv6"
    onnx_path = out_dir / f"radius-{version}.onnx"
    cmd = [sys.executable, str(y6 / "deploy" / "ONNX" / "export_onnx.py"),
           "--weights", str(ckpt), "--img-size", str(h), str(w),
           "--batch-size", "1", "--simplify", "--device", "cpu"]
    print("+", " ".join(cmd))
    r = subprocess.run(cmd, cwd=y6)
    if r.returncode != 0:
        sys.exit("YOLOv6 ONNX export failed")
    exported = ckpt.with_suffix(".onnx")
    if not exported.exists():
        cands = list(ckpt.parent.glob("*.onnx"))
        if not cands:
            sys.exit("no ONNX produced")
        exported = max(cands, key=lambda p: p.stat().st_mtime)
    exported.replace(onnx_path)

    import blobconverter
    blob = Path(blobconverter.from_onnx(
        model=str(onnx_path),
        data_type="FP16",
        shaves=shaves,
        version="2021.4",
        optimizer_params=["--mean_values=[0,0,0]",
                          "--scale_values=[255,255,255]"],
        output_dir=str(out_dir),
    ))
    dest_blob = MODELS / f"radius-{version}.blob"
    shutil.copy2(blob, dest_blob)

    sidecar = {
        "model": {"blob": dest_blob.name},
        "nn_config": {
            "output_format": "detection",
            "NN_family": "YOLO",
            "input_size": f"{w}x{h}",
            "NN_specific_metadata": {
                "classes": len(RADIUS_CLASSES),
                "coordinates": 4,
                "anchors": [],
                "anchor_masks": {},
                "iou_threshold": 0.45,
                # NN floor stays low; runtime threshold lives in the Script
                # node (build_standalone_v2 bakes 0.30 regardless).
                "confidence_threshold": 0.3,
            },
        },
        "mappings": {"labels": RADIUS_CLASSES},
        "version": 1,
        "radius": {
            "version": version,
            "family": "yolov6n",
            "export": {"openvino": "2021.4", "shaves": shaves,
                       "superblob": False},
        },
    }
    (MODELS / f"radius-{version}.json").write_text(
        json.dumps(sidecar, indent=4), encoding="utf-8")
    print(f"wrote {dest_blob} + sidecar. Next: uncomment radius registration "
          f"in pipeline/model_registry.py, run eval gate, then flash.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("ckpt", type=Path)
    ap.add_argument("--version", required=True)
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=384)
    ap.add_argument("--shaves", type=int, default=6)
    a = ap.parse_args()
    main(a.ckpt, a.version, a.width, a.height, a.shaves)
