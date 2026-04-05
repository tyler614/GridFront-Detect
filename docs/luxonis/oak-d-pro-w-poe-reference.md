# OAK-D Pro W PoE — Feature & API Reference (depthai v3.5.0)

> Compiled from Luxonis documentation, 2026-04-03.
> Device: OAK-D Pro W PoE (194430100112F17D00)

---

## Hardware Specs

- **Color sensor**: OV9782 (1280x800, global shutter)
- **Stereo pair**: 2x OV9282 mono (1280x800, global shutter)
- **FOV**: 150° DFOV (wide "W" variant)
- **Processor**: Intel Myriad X (RVC2) — 4 TOPS, 1.4 TOPS for AI
- **IMU**: BNO086 (accel, gyro, rotation vector)
- **IR**: Flood light LED + laser dot projector
- **Enclosure**: IP65 (dust-tight, water jet resistant)
- **Connectivity**: GigE PoE (802.3af), 1 Gbps
- **Connectors**: M12 PoE, M8 IO

---

## 1. IR Illumination

Both controlled via `dai.Device` (runtime, not pipeline build):

```python
# Verify IR hardware
ir_drivers = device.getIrDrivers()  # → [("LM3644", 2, 0x63)]

# IR flood light — uniform illumination for night vision
device.setIrFloodLightIntensity(0.5)   # 0.0-1.0 (0-1500mA)

# IR dot projector — structured light for stereo on textureless surfaces
device.setIrLaserDotProjectorIntensity(0.3)   # 0.0-1.0

# Turn off
device.setIrFloodLightIntensity(0)
device.setIrLaserDotProjectorIntensity(0)
```

**No auto-IR mode** — implement by monitoring frame brightness.

---

## 2. Camera Controls

```python
ctrl = dai.CameraControl()

# Auto
ctrl.setAutoExposureEnable()
ctrl.setAutoFocusMode(dai.CameraControl.AutoFocusMode.CONTINUOUS_VIDEO)
ctrl.setAutoWhiteBalanceMode(dai.CameraControl.AutoWhiteBalanceMode.AUTO)
ctrl.setAutoExposureCompensation(2)     # -12 to 12, +2 for bright outdoor
ctrl.setAntiBandingMode(dai.CameraControl.AntiBandingMode.AUTO)

# Image quality
ctrl.setLumaDenoise(2)      # 0-4, good for dusty environments
ctrl.setChromaDenoise(1)     # 0-4
ctrl.setSharpness(1)         # 0-4

# Manual overrides
ctrl.setManualExposure(20000, 800)   # (exposure_us, iso)
ctrl.setManualFocus(150)              # 0-255
```

---

## 3. Stereo Depth

```python
stereo = pipeline.create(dai.node.StereoDepth)
stereo.setDefaultProfilePreset(dai.node.StereoDepth.PresetMode.HIGH_DENSITY)
stereo.setLeftRightCheck(True)        # Always enable
stereo.setSubpixel(True)             # Better accuracy at distance
stereo.setDepthAlign(dai.CameraBoardSocket.CAM_A)  # Align depth to RGB

# Post-processing filters
config = stereo.initialConfig.get()

config.postProcessing.thresholdFilter.minRange = 200      # mm
config.postProcessing.thresholdFilter.maxRange = 15000     # mm

config.postProcessing.speckleFilter.enable = True
config.postProcessing.speckleFilter.speckleRange = 50

config.postProcessing.temporalFilter.enable = True
config.postProcessing.temporalFilter.alpha = 0.4

config.postProcessing.spatialFilter.enable = True
config.postProcessing.spatialFilter.alpha = 0.5
config.postProcessing.spatialFilter.holeFillingRadius = 2

config.postProcessing.decimationFilter.decimationFactor = 2  # Half-res depth

stereo.initialConfig.set(config)
```

---

## 4. Neural Network (On-Device Inference)

### YoloSpatialDetectionNetwork (3D detection)
```python
nn = pipeline.create(dai.node.YoloSpatialDetectionNetwork)
nn.setBlobPath("models/yolov5s.blob")
nn.setConfidenceThreshold(0.5)
nn.setIouThreshold(0.5)
nn.setNumClasses(80)
nn.setCoordinateSize(4)
nn.setDepthLowerThreshold(200)      # mm
nn.setDepthUpperThreshold(15000)    # mm
nn.setBoundingBoxScaleFactor(0.5)

# Link: RGB → NN input, stereo depth → NN depth input
camRgb.video.link(nn.input)
stereo.depth.link(nn.inputDepth)
```

### Model conversion
ONNX/PyTorch → OpenVINO IR → .blob (via blobconverter or Luxonis Hub)

### Available node types
- `dai.node.NeuralNetwork` — generic inference
- `dai.node.DetectionNetwork` — object detection
- `dai.node.YoloSpatialDetectionNetwork` — YOLO + depth = 3D boxes
- `dai.node.SpatialDetectionNetwork` — MobileNet-SSD + depth
- `dai.node.SpatialLocationCalculator` — 3D coords from 2D ROIs + depth

---

## 5. Video Encoding (PoE Bandwidth)

```python
encoder = pipeline.create(dai.node.VideoEncoder)
encoder.setDefaultProfilePreset(30, dai.VideoEncoderProperties.Profile.H265_MAIN)
```

**Profiles**: H264_BASELINE, H264_MAIN, H264_HIGH, H265_MAIN, MJPEG

**Important**: Encoder requires NV12 input (not BGR):
```python
rgb_out = cam.requestOutput(size, type=dai.ImgFrame.Type.NV12, fps=30)
encoder.build(rgb_out, profile=..., quality=80, frameRate=30)
q_enc = encoder.bitstream.createOutputQueue()
```

---

## 6. Object Tracking

```python
tracker = pipeline.create(dai.node.ObjectTracker)
tracker.setTrackerType(dai.TrackerType.ZERO_TERM_COLOR_HISTOGRAM)
tracker.setTrackerIdAssignmentPolicy(dai.TrackerIdAssignmentPolicy.SMALLEST_ID)
tracker.setDetectionLabelsToTrack([0, 1, 2])  # person, hardhat, vest
```

---

## 7. IMU

```python
imu = pipeline.create(dai.node.IMU)
imu.enableIMUSensor(dai.IMUSensor.ROTATION_VECTOR, 100)     # Hz
imu.enableIMUSensor(dai.IMUSensor.ACCELEROMETER_RAW, 500)
imu.setBatchReportThreshold(1)
imu.setMaxBatchReports(10)
```

---

## 8. Other Useful Nodes

| Node | Purpose |
|------|---------|
| `EdgeDetector` | Canny/Sobel edge detection |
| `FeatureTracker` | Harris/Shi-Tomasi features |
| `PointCloud` | 3D point cloud generation |
| `ImageManip` | Resize, crop, rotate, warp |
| `Script` | On-device scripting (hostless) |
| `Sync` | Synchronize multiple streams |
| `AprilTag` | Fiducial marker detection |
| `SystemLogger` | Device health (temp, CPU, memory) |

---

## 9. Recommended Production Pipeline

For construction safety over PoE:

1. Run **YoloSpatialDetectionNetwork** on-device → only stream detection JSON
2. Encode monitoring stream as **H.265** on-device → minimal bandwidth
3. Enable **IR auto** for 24/7 operation
4. Use **temporal + spatial depth filters** for reliable distance in dusty/variable light
5. Enable **object tracking** for dwell-time in hazard zones
6. Use **IMU** for tamper/vibration detection
