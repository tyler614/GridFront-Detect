"""Build a Luxonis NNArchive (.tar.xz) from a raw OpenVINO .blob + sidecar.

Background — DepthAI v3 deprecated raw .blob loading on
SpatialDetectionNetwork. The YOLO decode metadata (n_classes, anchors,
iou/conf thresholds, output tensor names) used to be set with per-field
methods like ``setNumClasses``; those methods are gone. The supported way
to load a local model is now ``dai.NNArchive(path)`` — a tar.xz containing
``model.blob`` plus a ``config.json`` describing the model schema.

Our training/export pipeline (run on Tyler's training rig) emits the
old-style ``<name>.blob`` + ``<name>.json`` (Luxonis blobconverter
format). This module wraps that pair into a v3 NNArchive on demand.
The archive is cached next to the blob and only rebuilt if the blob or
sidecar is newer than the cache.

If you want to skip the runtime build entirely, run this module as a
script — it will build the archive ahead of time:

    python -m pipeline.nn_archive_builder models/gridfront-detect-v1.blob
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tarfile
import tempfile
from typing import Optional

import depthai as dai

logger = logging.getLogger(__name__)


def ensure_archive(blob_path: str, sidecar_path: Optional[str] = None) -> str:
    """Return the path to a Luxonis NNArchive built from ``blob_path``.

    The sidecar defaults to the blob path with ``.json`` swapped in. The
    archive is cached at ``<blob>.tar.xz`` and rebuilt if either source
    file is newer than the cache.
    """
    blob_path = os.path.abspath(blob_path)
    if not os.path.isfile(blob_path):
        raise FileNotFoundError(f"Model blob not found: {blob_path}")

    if sidecar_path is None:
        sidecar_path = os.path.splitext(blob_path)[0] + ".json"
    if not os.path.isfile(sidecar_path):
        raise FileNotFoundError(
            f"Sidecar metadata not found alongside blob: {sidecar_path}"
        )

    archive_path = os.path.splitext(blob_path)[0] + ".tar.xz"

    if _cache_is_fresh(archive_path, [blob_path, sidecar_path]):
        return archive_path

    model_name = os.path.splitext(os.path.basename(blob_path))[0]
    config = _build_config(blob_path, sidecar_path, model_name)
    _pack(blob_path, config, archive_path)
    logger.info("Built NNArchive: %s (%d bytes)", archive_path, os.path.getsize(archive_path))
    return archive_path


def _cache_is_fresh(cache: str, sources: list[str]) -> bool:
    if not os.path.isfile(cache):
        return False
    cache_mtime = os.path.getmtime(cache)
    return all(os.path.getmtime(s) <= cache_mtime for s in sources)


def _build_config(blob_path: str, sidecar_path: str, model_name: str) -> dict:
    """Translate Luxonis v2 blobconverter sidecar -> NNArchive v1.0 config."""
    with open(sidecar_path) as f:
        side = json.load(f)

    nn_meta = side["nn_config"]["NN_specific_metadata"]
    classes = side["mappings"]["labels"]
    n_classes = nn_meta["classes"]
    if len(classes) != n_classes:
        raise ValueError(
            f"Sidecar inconsistency: {len(classes)} labels but n_classes={n_classes}"
        )

    # Pull real input/output tensor names + shapes from the blob itself,
    # so we never drift from what the network actually exposes.
    blob = dai.OpenVINO.Blob(blob_path)

    inputs = []
    for name, t in blob.networkInputs.items():
        # OpenVINO blob dims are stored as [W, H, C, N]; convert to NCHW.
        n, c, h, w = _dims_to_nchw(t.dims)
        inputs.append({
            "name": name,
            "dtype": "uint8",
            "input_type": "image",
            "shape": [n, c, h, w],
            "layout": "NCHW",
            "preprocessing": {
                # YOLO trained on 0..1 RGB; OAK feeds 0..255 BGR planar.
                "mean": [0.0, 0.0, 0.0],
                "scale": [255.0, 255.0, 255.0],
                "reverse_channels": True,
                "interleaved_to_planar": False,
                "dai_type": "BGR888p",
            },
        })

    out_specs = []
    yolo_output_names = []
    for name, t in blob.networkOutputs.items():
        n, c, h, w = _dims_to_nchw(t.dims)
        out_specs.append({
            "name": name,
            "dtype": "float16",
            "shape": [n, c, h, w],
            "layout": "NCHW",
        })
        yolo_output_names.append(name)

    # We currently only export YOLOv6r2-style anchor-free heads from the
    # training pipeline. If a future model uses a different family,
    # extend this dispatch rather than special-casing the caller.
    head = {
        "parser": "YOLO",
        "metadata": {
            "classes": classes,
            "n_classes": n_classes,
            "iou_threshold": float(nn_meta["iou_threshold"]),
            "conf_threshold": float(nn_meta["confidence_threshold"]),
            "anchors": nn_meta.get("anchors", []),
            "subtype": "yolov6r2",
            "yolo_outputs": yolo_output_names,
        },
        "outputs": yolo_output_names,
    }

    return {
        "config_version": "1.0",
        "model": {
            "metadata": {
                "name": model_name,
                "path": "model.blob",
                "precision": "int8",
            },
            "inputs": inputs,
            "outputs": out_specs,
            "heads": [head],
        },
    }


def _dims_to_nchw(dims) -> tuple[int, int, int, int]:
    """Convert an OpenVINO blob dim tuple ([W,H,C,N]) to NCHW."""
    d = list(dims) + [1] * (4 - len(dims))
    w, h, c, n = d[0], d[1], d[2], d[3]
    return n, c, h, w


def _pack(blob_path: str, config: dict, out_path: str) -> None:
    tmpdir = tempfile.mkdtemp(prefix="nnarchive_")
    try:
        shutil.copy(blob_path, os.path.join(tmpdir, "model.blob"))
        with open(os.path.join(tmpdir, "config.json"), "w") as f:
            json.dump(config, f, indent=2)
        with tarfile.open(out_path, "w:xz") as tar:
            tar.add(os.path.join(tmpdir, "model.blob"), arcname="model.blob")
            tar.add(os.path.join(tmpdir, "config.json"), arcname="config.json")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) != 2:
        print("Usage: python -m pipeline.nn_archive_builder <path/to/model.blob>")
        sys.exit(1)
    out = ensure_archive(sys.argv[1])
    print(out)
