# GridFront Detect

Android kiosk app for the Oukitel RT3 Pro tablet.
Displays a real-time radar view of detected persons around industrial equipment.

## Architecture

- WebView-based app wrapping the radar web UI
- Device Owner mode for kiosk lockdown
- Connects to OAK-D camera detection pipeline via WiFi or receives data via BLE from Thingy:91 X
- Uploads detection events to GridFront platform via SIM card (LTE) or WiFi

## Target Device

- Oukitel RT3 Pro
- Android 14 (SDK 34)
- 800x1280, 240dpi
