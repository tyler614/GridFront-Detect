"""Camera configuration for OAK-D Pro W PoE."""

from dataclasses import dataclass


@dataclass
class OakConfig:
    """All tunables for the OAK-D pipeline.

    Defaults are optimised for construction-site safety detection:
    1080p RGB at 15 FPS balances quality and bandwidth over PoE,
    HIGH_ACCURACY depth with extended disparity for reliable distance
    measurement out to 15 m.
    """

    resolution_rgb: str = "1080p"       # 1080p | 4k | 720p
    fps: int = 15
    depth_preset: str = "HIGH_ACCURACY" # HIGH_ACCURACY | HIGH_DENSITY | DEFAULT
    extended_disparity: bool = True
    subpixel: bool = True
    lr_check: bool = True
    nn_model: str = "mobilenet-ssd"     # Model name from depthai model zoo
    nn_shaves: int = 6                  # Neural compute shaves to allocate
    confidence_threshold: float = 0.5
    max_depth_m: float = 15.0
    min_depth_m: float = 0.2
    preview_size: tuple = (300, 300)    # NN input resolution
    reconnect_interval_s: float = 5.0   # Seconds between reconnection attempts
