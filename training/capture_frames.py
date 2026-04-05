"""Capture training frames from an OAK-D camera.

Saves JPG images at a configurable interval for labeling and training.

Usage:
    # From OAK-D camera (live)
    python training/capture_frames.py --ip 192.168.1.100 --output training/raw_frames

    # From webcam (if no OAK-D available)
    python training/capture_frames.py --webcam --output training/raw_frames

    # Faster capture for action scenes
    python training/capture_frames.py --ip 192.168.1.100 --interval 0.5 --output training/raw_frames
"""

import argparse
import os
import sys
import time
from datetime import datetime


def capture_oakd(ip: str, output_dir: str, interval: float, max_frames: int):
    """Capture frames from OAK-D PoE camera."""
    try:
        import depthai as dai
    except ImportError:
        print("ERROR: depthai not installed. Run: pip install depthai==3.5.0.0")
        sys.exit(1)

    print(f"Connecting to OAK-D at {ip}...")

    pipeline = dai.Pipeline()
    cam = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_A)
    video_out = cam.requestOutput((1920, 1080), type=dai.ImgFrame.Type.BGR888p)
    q_rgb = video_out.createOutputQueue()

    device_info = dai.DeviceInfo(ip)
    with dai.Device(pipeline, device_info) as device:
        print(f"Connected! Saving frames to {output_dir}/ every {interval}s")
        print("Press Ctrl+C to stop\n")

        count = 0
        while count < max_frames:
            frame = q_rgb.get()
            if frame is None:
                continue

            img = frame.getCvFrame()
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            filename = f"frame_{ts}.jpg"
            filepath = os.path.join(output_dir, filename)

            import cv2
            cv2.imwrite(filepath, img, [cv2.IMWRITE_JPEG_QUALITY, 95])
            count += 1
            print(f"  [{count}] Saved {filename}")

            time.sleep(interval)

    print(f"\nDone! Captured {count} frames in {output_dir}/")


def capture_webcam(output_dir: str, interval: float, max_frames: int):
    """Capture frames from a USB webcam (fallback)."""
    try:
        import cv2
    except ImportError:
        print("ERROR: opencv-python not installed. Run: pip install opencv-python")
        sys.exit(1)

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("ERROR: Could not open webcam")
        sys.exit(1)

    print(f"Webcam opened. Saving frames to {output_dir}/ every {interval}s")
    print("Press Ctrl+C to stop\n")

    count = 0
    try:
        while count < max_frames:
            ret, img = cap.read()
            if not ret:
                continue

            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            filename = f"frame_{ts}.jpg"
            filepath = os.path.join(output_dir, filename)

            cv2.imwrite(filepath, img, [cv2.IMWRITE_JPEG_QUALITY, 95])
            count += 1
            print(f"  [{count}] Saved {filename}")

            time.sleep(interval)
    finally:
        cap.release()

    print(f"\nDone! Captured {count} frames in {output_dir}/")


def main():
    parser = argparse.ArgumentParser(description="Capture training frames")
    parser.add_argument("--ip", help="OAK-D camera IP address")
    parser.add_argument("--webcam", action="store_true", help="Use USB webcam instead")
    parser.add_argument("--output", default="training/raw_frames", help="Output directory")
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds between captures")
    parser.add_argument("--max", type=int, default=5000, help="Maximum frames to capture")
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)

    if args.webcam:
        capture_webcam(args.output, args.interval, args.max)
    elif args.ip:
        capture_oakd(args.ip, args.output, args.interval, args.max)
    else:
        print("ERROR: Provide --ip for OAK-D or --webcam for USB camera")
        sys.exit(1)


if __name__ == "__main__":
    main()
