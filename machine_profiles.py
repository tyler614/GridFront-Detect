"""
GridFront Detect — Machine Profile Definitions
Real-world dimensions and camera mount positions for supported equipment types.
"""

MACHINE_PROFILES = {
    "wheel_loader": {
        "name": "Wheel Loader",
        "example": "CAT 950 GC",
        "dimensions": {"length_m": 8.4, "width_m": 2.5, "height_m": 3.4},
        "default_zones": {"danger_m": 3.5, "warning_m": 6.0, "max_range_m": 12.0},
        "camera_mounts": [
            {"id": "front", "label": "Front", "position": [0, 2.8, 4.2], "rotation": [0, 0, 0]},
            {"id": "rear", "label": "Rear", "position": [0, 2.5, -4.2], "rotation": [0, 180, 0]},
            {"id": "left", "label": "Left", "position": [-1.25, 2.8, 0], "rotation": [0, -90, 0]},
            {"id": "right", "label": "Right", "position": [1.25, 2.8, 0], "rotation": [0, 90, 0]},
        ],
        "camera_spec": {"hfov_deg": 127, "depth_hfov_deg": 73, "vfov_deg": 58, "max_depth_m": 15},
    },
    "excavator": {
        "name": "Excavator",
        "example": "CAT 320",
        "dimensions": {"length_m": 9.5, "width_m": 2.9, "height_m": 3.0},
        "default_zones": {"danger_m": 4.0, "warning_m": 7.0, "max_range_m": 12.0},
        "camera_mounts": [
            {"id": "front", "label": "Front", "position": [0, 2.8, 1.5], "rotation": [0, 0, 0]},
            {"id": "rear", "label": "Rear", "position": [0, 2.5, -1.5], "rotation": [0, 180, 0]},
            {"id": "left", "label": "Left", "position": [-1.45, 2.8, 0], "rotation": [0, -90, 0]},
            {"id": "right", "label": "Right", "position": [1.45, 2.8, 0], "rotation": [0, 90, 0]},
        ],
        "camera_spec": {"hfov_deg": 127, "depth_hfov_deg": 73, "vfov_deg": 58, "max_depth_m": 15},
    },
    "dozer": {
        "name": "Dozer",
        "example": "CAT D6",
        "dimensions": {"length_m": 4.7, "width_m": 2.7, "height_m": 3.1},
        "default_zones": {"danger_m": 3.0, "warning_m": 5.5, "max_range_m": 10.0},
        "camera_mounts": [
            {"id": "front", "label": "Front", "position": [0, 2.8, 2.35], "rotation": [0, 0, 0]},
            {"id": "rear", "label": "Rear", "position": [0, 2.5, -2.35], "rotation": [0, 180, 0]},
            {"id": "left", "label": "Left", "position": [-1.35, 2.8, 0], "rotation": [0, -90, 0]},
            {"id": "right", "label": "Right", "position": [1.35, 2.8, 0], "rotation": [0, 90, 0]},
        ],
        "camera_spec": {"hfov_deg": 127, "depth_hfov_deg": 73, "vfov_deg": 58, "max_depth_m": 15},
    },
    "dump_truck": {
        "name": "Dump Truck",
        "example": "CAT 740",
        "dimensions": {"length_m": 10.6, "width_m": 3.5, "height_m": 3.7},
        "default_zones": {"danger_m": 4.5, "warning_m": 8.0, "max_range_m": 15.0},
        "camera_mounts": [
            {"id": "front", "label": "Front", "position": [0, 3.2, 5.3], "rotation": [0, 0, 0]},
            {"id": "rear", "label": "Rear", "position": [0, 2.8, -5.3], "rotation": [0, 180, 0]},
            {"id": "left", "label": "Left", "position": [-1.75, 3.0, 0], "rotation": [0, -90, 0]},
            {"id": "right", "label": "Right", "position": [1.75, 3.0, 0], "rotation": [0, 90, 0]},
        ],
        "camera_spec": {"hfov_deg": 127, "depth_hfov_deg": 73, "vfov_deg": 58, "max_depth_m": 15},
    },
}

DETECTION_CLASSES = {
    "person": {"label": "Person", "default_priority": "critical", "icon": "person"},
    "excavator": {"label": "Excavator", "default_priority": "warning", "icon": "excavator"},
    "dump_truck": {"label": "Dump Truck", "default_priority": "warning", "icon": "truck"},
    "dozer": {"label": "Dozer", "default_priority": "warning", "icon": "dozer"},
    "wheel_loader": {"label": "Wheel Loader", "default_priority": "warning", "icon": "loader"},
    "cone": {"label": "Traffic Cone", "default_priority": "info", "icon": "cone"},
    "barrier": {"label": "Barrier", "default_priority": "info", "icon": "barrier"},
}


def get_machine_profile(machine_type):
    """Return a single machine profile by type key, or None if not found."""
    return MACHINE_PROFILES.get(machine_type)


def get_all_profiles():
    """Return all machine profiles."""
    return MACHINE_PROFILES


def get_detection_classes():
    """Return all detection class definitions."""
    return DETECTION_CLASSES
