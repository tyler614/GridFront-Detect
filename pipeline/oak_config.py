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

    resolution_rgb: str = "800p"         # 800p (OV9782 native) | 720p | 480p | 400p
    fps: int = 30
    enable_depth: bool = True            # Stereo depth for 3D spatial awareness
    depth_preset: str = "HIGH_ACCURACY" # HIGH_ACCURACY | HIGH_DENSITY | DEFAULT
    extended_disparity: bool = True
    subpixel: bool = True
    lr_check: bool = True
    nn_model_id: str = "yolov10n-coco"  # Model ID from model_registry
    nn_shaves: int = 6                  # Neural compute shaves to allocate
    enable_nn: bool = True              # Enable on-device neural network inference
    confidence_threshold: float = 0.5
    max_depth_m: float = 15.0
    min_depth_m: float = 0.2
    preview_size: tuple = (512, 288)    # NN input resolution (overridden by model)
    ir_flood_intensity: float = 0.0     # IR flood light: 0.0 (off) to 1.0 (1500mA)
    ir_dot_intensity: float = 0.0       # IR dot projector: 0.0 (off) to 1.0
    ir_auto: bool = True                # Auto-enable IR when scene is dark
    reconnect_interval_s: float = 5.0   # Seconds between reconnection attempts
