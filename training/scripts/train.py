"""Train YOLOv11n on the merged GridFront Detect dataset.

Usage:
    python training/scripts/train.py
"""

from ultralytics import YOLO


def main():
    model = YOLO("yolo11n.pt")  # YOLOv11 nano, pretrained on COCO

    results = model.train(
        data="training/merged/data.yaml",
        epochs=100,
        imgsz=640,
        batch=32,           # RTX 3060 12GB — bigger batch = faster training
        device=0,           # GPU 0
        workers=4,          # Windows-safe
        patience=20,        # Early stopping if no improvement for 20 epochs
        save=True,
        save_period=10,     # Checkpoint every 10 epochs
        project="training/runs",
        name="gridfront-detect-v1",
        exist_ok=True,
        # Augmentation
        hsv_h=0.015,
        hsv_s=0.7,
        hsv_v=0.4,
        degrees=10.0,
        translate=0.1,
        scale=0.5,
        flipud=0.0,         # No vertical flip — construction scenes have consistent up/down
        fliplr=0.5,
        mosaic=1.0,
        mixup=0.1,
    )

    print(f"\nTraining complete!")
    print(f"Best model: training/runs/gridfront-detect-v1/weights/best.pt")


if __name__ == "__main__":
    main()
