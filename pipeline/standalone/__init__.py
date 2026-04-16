"""Standalone OAK-D pipeline.

Bakes the YOLO + SpatialDetectionNetwork pipeline into the camera's flash
along with a Script node that classifies detections into DANGER/WARNING/
CLEAR zones and broadcasts the result via UDP. No host required.

Pairs with `esp32-display/esp32-display.ino` — the cab display reads the
same UDP packet shape it gets today from `display_broadcaster.py`.
"""
