# GridFront Scout

GridFront Scout is the tablet kiosk + OAK-D standalone camera system for
showing a live proximity radar around industrial equipment.

This branch, `oak-standalone`, is focused on the Oukitel RT3 Pro tablet and
one or more OAK-D Pro W PoE cameras. The tablet is the operator interface and
configuration source of truth. The OAK runs the perception pipeline on-device
and sends compact detection packets to the tablet.

## Current Scope

- Android kiosk app for Oukitel RT3 Pro, Android 14.
- Full-screen WebView served from bundled assets at `http://127.0.0.1:8080/`.
- OAK-D standalone firmware for neural detection, stereo depth, object
  tracking, machine-frame transform, and zone classification.
- Direct USB-C Ethernet link today:
  - tablet `eth0`: `169.254.1.56`
  - OAK: `169.254.1.222`
- Wi-Fi debugging remains available because the tablet USB-C port is occupied
  by the OAK/Ethernet chain.

## Runtime Data Flow

1. `MainActivity` starts the local tablet services.
2. `EthernetProvisioner` configures tablet `eth0` for link-local OAK traffic.
3. `ConfigStore` owns persisted machine, camera, zone, model, and rate config.
4. `ConfigSync` listens on UDP `5557` and pushes current config to cameras.
5. The OAK firmware receives config on UDP `5557`.
6. The OAK sends detection JSON packets to the tablet on UDP `5556`.
7. `UdpListener` stores the latest detection packet and fans out SSE updates.
8. `LocalAssetServer` serves `assets/www/index.html` and local `/api/*`.
9. The WebView renders the radar, settings UI, connection state, and controls.

The important ports are:

- `8080`: tablet-local HTTP server for the WebView and local API.
- `5556`: OAK-to-tablet detection packets.
- `5557`: bidirectional tablet/OAK config sync.
- `5555`: optional ADB over Wi-Fi on the tablet.

## Key Files

- `android/app/src/main/java/io/gridfront/scout/MainActivity.kt`
  starts the kiosk app, WebView, UDP listener, config sync, Ethernet
  provisioning, and foreground service.
- `android/app/src/main/java/io/gridfront/scout/LocalAssetServer.kt`
  serves the WebView and owns the tablet-local `/api/*` surface.
- `android/app/src/main/java/io/gridfront/scout/UdpListener.kt`
  receives OAK detection packets on UDP `5556`.
- `android/app/src/main/java/io/gridfront/scout/ConfigStore.kt`
  stores tablet-owned machine, camera, zone, model, and runtime config.
- `android/app/src/main/java/io/gridfront/scout/ConfigSync.kt`
  sends config to OAK cameras and answers camera `config_request` packets.
- `android/app/src/main/java/io/gridfront/scout/EthernetProvisioner.kt`
  root-provisions the USB-C Ethernet interface for the direct OAK link.
- `android/app/src/main/assets/www/index.html`
  contains the current cab radar and settings UI.
- `pipeline/standalone/build_standalone_v2.py`
  builds or flashes the OAK standalone pipeline from local model assets.
- `pipeline/standalone/script_runtime.py`
  is the Script node source that runs on the OAK.
- `docs/tablet-oak-roadmap.md`
  tracks current rough edges and next work.

## Common Commands

Build the Android debug APK:

```powershell
android\gradlew.bat -p android assembleDebug
```

Build a dry-run OAK `.dap` without flashing:

```powershell
.venv2x\Scripts\python.exe -m pipeline.standalone.build_standalone_v2 --dap temp\probe.dap
```

Flash the OAK after confirming the target and model:

```powershell
.venv2x\Scripts\python.exe -m pipeline.standalone.build_standalone_v2 --confirm-flash
```

Check tablet Wi-Fi ADB when available:

```powershell
C:\Users\helve\Android\Sdk\platform-tools\adb.exe devices -l
```

Query the running tablet app through ADB:

```powershell
C:\Users\helve\Android\Sdk\platform-tools\adb.exe -s 192.168.68.62:5555 shell "curl -s http://127.0.0.1:8080/api/camera/status"
```

## Known Paper Cuts

- `WebServerService` still polls the old Flask health endpoint at
  `127.0.0.1:5555`; the current standalone tablet health is behind
  `LocalAssetServer` on port `8080`.
- The current WebView app is intentionally bundled as one large
  `index.html`. It works, but future UI work should eventually split it into
  smaller owned modules.
- In-page keyboard reliability, app slowness profiling, boot branding, and
  multi-camera polish are tracked in `docs/tablet-oak-roadmap.md`.

## Local Artifacts

Generated and machine-local artifacts are ignored, including virtualenvs,
DepthAI caches, build outputs, logs, screenshots, `.dap` files, model blobs,
and `temp/`. Avoid committing live tablet keys, generated probe files, or local
debug screenshots.
