"""Depth map to 3D position conversion using camera intrinsics.

Pure numpy implementation — no depthai dependency required.
"""

import math
from dataclasses import dataclass

import numpy as np


@dataclass
class CameraIntrinsics:
    """Pin-hole camera intrinsic parameters."""

    fx: float  # Focal length X (pixels)
    fy: float  # Focal length Y (pixels)
    cx: float  # Principal point X (pixels)
    cy: float  # Principal point Y (pixels)
    width: int
    height: int


# OAK-D Pro W defaults (400p depth mode, 640x400 output)
OAK_D_PRO_W_400P = CameraIntrinsics(
    fx=320.0,
    fy=320.0,
    cx=320.0,
    cy=200.0,
    width=640,
    height=400,
)


def pixel_to_3d(
    px: float, py: float, depth_m: float, intrinsics: CameraIntrinsics
) -> tuple:
    """Back-project a pixel coordinate + depth to a 3D point in camera frame.

    Camera frame convention (OpenCV / OAK-D standard):
        x — right is positive
        y — down is positive in pixel space, but we flip to up-positive for output
        z — forward (depth) is positive

    Returns:
        (x_m, y_m, z_m) in metres, camera-local.
    """
    x_m = (px - intrinsics.cx) * depth_m / intrinsics.fx
    # Flip y so that "up" is positive in the output coordinate system.
    y_m = -(py - intrinsics.cy) * depth_m / intrinsics.fy
    z_m = depth_m
    return (x_m, y_m, z_m)


def sample_depth(
    depth_map: np.ndarray,
    bbox: tuple,
    patch_size: int = 5,
    method: str = "median",
) -> float:
    """Sample depth inside a bounding box, rejecting outliers.

    Args:
        depth_map: HxW depth image in metres (float) or millimetres (uint16).
                   If dtype is uint16, values are assumed to be mm and converted.
        bbox: (x1, y1, x2, y2) normalised 0-1.
        patch_size: Side length of the central sampling patch.
        method: "median" (default) or "mean".

    Returns:
        Depth in metres, or 0.0 if no valid samples.
    """
    h, w = depth_map.shape[:2]

    x1, y1, x2, y2 = bbox
    # Convert normalised coords to pixel coords.
    px1 = int(x1 * w)
    py1 = int(y1 * h)
    px2 = int(x2 * w)
    py2 = int(y2 * h)

    # Centre of the bbox.
    cx = (px1 + px2) // 2
    cy = (py1 + py2) // 2

    half = patch_size // 2
    # Clamp patch to image bounds.
    r_min = max(0, cy - half)
    r_max = min(h, cy + half + 1)
    c_min = max(0, cx - half)
    c_max = min(w, cx + half + 1)

    patch = depth_map[r_min:r_max, c_min:c_max].astype(np.float64)

    # If the source was uint16 millimetres, convert to metres.
    if depth_map.dtype == np.uint16:
        patch = patch / 1000.0

    # Filter out invalid values (0, NaN, inf).
    valid = patch[(patch > 0) & np.isfinite(patch)]
    if valid.size == 0:
        return 0.0

    if method == "mean":
        return float(np.mean(valid))
    return float(np.median(valid))


def distance_3d(x: float, y: float, z: float) -> float:
    """Euclidean distance from the camera origin."""
    return math.sqrt(x * x + y * y + z * z)
