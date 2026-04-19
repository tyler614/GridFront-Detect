# GridFront Detect — ESP32 Cab Display

Firmware for the **LilyGo T4-S3** (2.41" AMOLED) that mirrors the radar view from the Detect Flask app. Receives detection packets over UDP and renders them on the AMOLED; HTTP-registers itself with the server so the server knows where to send packets.

## One-time setup

```bash
cp secrets.h.example secrets.h
# Edit secrets.h with your WiFi SSID/password and server IP
```

## Build + flash (from this folder)

```bash
# Compile
arduino-cli compile --fqbn esp32:esp32:esp32s3:PSRAM=opi,USBMode=hwcdc,CDCOnBoot=cdc,FlashSize=16M,PartitionScheme=default_16MB esp32-display.ino

# Upload (replace COM8 with your port)
arduino-cli upload --fqbn esp32:esp32:esp32s3:PSRAM=opi,USBMode=hwcdc,CDCOnBoot=cdc,FlashSize=16M,PartitionScheme=default_16MB -p COM8 esp32-display.ino

# Watch serial
arduino-cli monitor -p COM8 -c baudrate=115200
```

## Data flow

```
OAK-D → Ethernet → laptop Flask (app.py)
                        │
                        ├── /api/register-display  ← ESP registers here on boot
                        │
                        └── UDP :5556  →  ESP (radar render)
```

The ESP registers its IP with the server every 15s; the server pushes detection state as JSON over UDP at the pipeline tick rate.
