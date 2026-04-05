# Model Training Guide for GridFront Detection

## Quick Overview

```
Capture frames → Label in Roboflow → Train with Ultralytics → Convert to blob → Deploy on OAK-D
```

## Step 1: Capture Training Data

Run the capture script to save frames from your OAK-D camera:

```bash
python training/capture_frames.py --ip 192.168.1.XXX --output training/raw_frames --interval 2
```

This saves a JPG every 2 seconds. Walk around the machine, move cones, wear/remove
hardhat, drive vehicles past — capture the variety of scenes you want the model to handle.

**Aim for 500-2000 images** covering:
- Different angles and distances
- Various lighting (morning, noon, evening, overcast)
- All object types you care about (people, hardhats, vests, cones, machinery)
- Hard negatives (wall outlets, signs, things that look like machinery but aren't)

## Step 2: Label with Roboflow (Free Tier)

1. Go to https://app.roboflow.com — create free account
2. Create new project → "Object Detection"
3. Upload your captured frames
4. Draw bounding boxes around objects. Use these classes:
   - `Hardhat`, `NO-Hardhat`
   - `Safety Vest`, `NO-Safety Vest`
   - `Mask`, `NO-Mask`
   - `Person`
   - `Safety Cone`
   - `machinery`
   - `vehicle`
5. Export dataset as **YOLOv8 format** → download ZIP

**Pro tip:** Start with 100 labeled images, train, see what's wrong, then label more
of the failure cases. Iterating fast beats labeling everything upfront.

## Step 3: Train with Ultralytics

```bash
# Install (one time)
pip install ultralytics

# Train — starts from COCO pretrained weights, fine-tunes on your data
yolo detect train \
    data=path/to/your/data.yaml \
    model=yolov8n.pt \
    epochs=100 \
    imgsz=640 \
    batch=16 \
    name=gridfront-ppe-v1

# Results land in runs/detect/gridfront-ppe-v1/
# Key files: best.pt, results.png, confusion_matrix.png
```

### data.yaml format (Roboflow generates this):
```yaml
train: ../train/images
val: ../valid/images
nc: 10
names: ['Hardhat', 'Mask', 'NO-Hardhat', 'NO-Mask', 'NO-Safety Vest',
        'Person', 'Safety Cone', 'Safety Vest', 'machinery', 'vehicle']
```

### Training tips:
- **yolov8n.pt** = nano (fastest, best for OAK-D Myriad X)
- **yolov8s.pt** = small (better accuracy, still runs ~15 FPS)
- If you have a GPU, training takes 30-60 minutes. CPU works but takes hours.
- Watch the mAP50 metric — 0.7+ is good, 0.85+ is great

## Step 4: Convert to OAK-D blob

### Option A: Luxonis Tools (online, easiest)
1. Go to https://tools.luxonis.com
2. Upload your `best.pt`
3. Select YOLOv8, input size 640x640
4. Download the `.blob` file

### Option B: Command line
```bash
# Install conversion tools
pip install luxonis-ml onnx onnxsim

# Export to ONNX
yolo export model=runs/detect/gridfront-ppe-v1/weights/best.pt format=onnx imgsz=640 simplify

# Convert ONNX to blob (requires blobconverter)
pip install blobconverter
python -c "
import blobconverter
blob_path = blobconverter.from_onnx(
    model='runs/detect/gridfront-ppe-v1/weights/best.onnx',
    data_type='FP16',
    shaves=6,
)
print(f'Blob saved to: {blob_path}')
"
```

## Step 5: Deploy

1. Copy the `.blob` file to `models/` directory
2. Register it in the model registry (see below)
3. Select it in Settings → Models
4. Restart the server

### Register custom model:

In `pipeline/model_registry.py`, add:
```python
_register(ModelDef(
    id="gridfront-ppe-v1",
    name="GridFront PPE v1 (Custom)",
    slug="",  # Not used for local models
    classes=PPE_LABELS,
    input_size=(640, 640),
    description="Custom trained PPE model for your site.",
    source="local",
    blob_path="models/gridfront-ppe-v1.blob",
))
```

## Fixing Specific Problems

### False positives (wall outlet → "machinery")
Add **hard negative** images: photos of wall outlets, signs, panels — anything
that gets misdetected. Label them with NO bounding boxes (empty annotation).
The model learns "this is NOT machinery."

### Missing detections (wearing hardhat but not detected)
Add more examples of hardhats at the angles/distances where detection fails.
Vary the hardhat colors, styles, and head positions.

### Confidence too low
Lower the confidence threshold in `pipeline/oak_config.py`:
```python
confidence_threshold: float = 0.4  # was 0.5
```
Or train longer (more epochs) with more data.
