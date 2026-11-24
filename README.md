# Project Veronica

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Raspberry Pi 5](https://img.shields.io/badge/Platform-Raspberry%20Pi%205-red.svg)]()

Project Veronica is a distributed classroom capture and edge-control system for resource-constrained schools. It combines a tactile ESP32 lectern pod with a Raspberry Pi 5 orchestration hub to capture board content, record lectures, compile notes, and publish results locally or to cloud services.

The system is designed for unreliable networks, limited infrastructure, and situations where a physical control surface remains usable when a browser or network is unavailable.

---

## Overview

A typical deployment provides:

- NFC teacher login and subject context switching
- 3.5-inch touch-screen controls on an ESP32 pod
- Legacy TTP229 keypad and PN532 NFC support
- Chalkboard photo capture with 5-frame noise reduction
- Live camera preview for dashboard, projector, and back-row viewing
- Video-and-audio and audio-only lecture recording
- Multi-page PDF lecture-note compilation
- Telegram photo, document, notification, and report delivery
- Google Drive archival with offline upload spooling
- A Flask dashboard, projector view, report ledger, kiosk UI, and diagnostic admin portal
- Secure physical shutdown/restart confirmation
- Dynamic runtime configuration through `config.json`
- Hardware-independent preview and demonstration mode

---

## Current architecture

### Tier 1 — ESP32 lectern pod

The primary current pod interface is a standalone **3.5-inch Robocrazе?** style touch display (480×320) using an ESP32-WROOM-32D. It provides:

- A three-slide landscape touch interface
- Capture, compile, record, subject, and system controls
- Live recording duration and resolution feedback
- NFC teacher greeting cards
- Subject unlock and anti-misuse prompts
- TFT display sleep, wake, and day/night themes
- Active-buzzer acoustic feedback
- Wireless TCP JSON communication with the Pi

A legacy keypad firmware remains available for TTP229, PN532, and buzzer installations.

### Tier 2 — Raspberry Pi 5 edge hub

The Pi 5 receives pod events and orchestrates the complete classroom workflow:

- TCP pod receiver on port `8765`
- Kreo Owl 4K USB camera and conference microphone
- Live MJPEG camera stream
- FFmpeg H.264/AAC MP4 and M4A audio recording
- PIL-based multi-page PDF compilation
- Subject-aware session state and automatic handover
- Telegram and Google Drive integration
- Local media storage and offline upload retry
- Principal-led activity reporting
- Full-screen Chromium kiosk operation

---

## Touch pod

The primary firmware is:

```text
esp32_firmware/esp32_touch_pod/esp32_touch_pod.ino
```

Supporting display configuration is in:

```text
esp32_firmware/esp32_touch_pod/Display_Config.h
```

The touch interface contains three horizontal slides:

| Slide | Controls |
|---|---|
| Capture and core tools | NFC, Optical Scan, Compile & Send, 4K Stream, Voice Note, Terminate & Archive |
| Presentation and diagnostics | Wall Projector, Standby / sleep, Telemetry Report, Reboot Pod Hub |
| Subject matrix | Physics, Chemistry, Mathematics, Computer Science |

The pod also supports direct subject switching and teacher NFC handover.

Hardware setup, display pin mapping, library installation, XPT2046 calibration, flashing, and troubleshooting are documented in:

- `docs/ESP32_DISPLAY_SETUP_GUIDE.md`
- `esp32_firmware/README.md`

---

## Raspberry Pi features

### Capture and publishing

- Raw photographs are stored under `storage/photos/`
- Session PDFs are stored under `storage/notes/`
- MP4/M4A recordings are stored under `storage/videos/`
- Captured photos generate immediate Telegram previews
- Session handover automatically compiles the previous subject's pages
- The final PDF is delivered through Telegram and uploaded to Google Drive
- Raw JPEG uploads are avoided unless explicitly required

### Live camera

The `/video_feed` endpoint provides a multipart MJPEG stream with no-content-delay frame delivery. The camera worker:

- Supports 4K at 3840×2160
- Supports 1080p high-FPS mode
- Allows runtime resolution switching through `/api/camera/resolution`
- Releases `/dev/video0` during FFmpeg recording to avoid V4L2 conflicts
- Applies a 50 Hz anti-flicker setting for regions using 50 Hz mains
- Writes a shared JPEG frame for projector and dashboard preview

### Automatic session handover

Changing subject context or teacher NFC automatically:

1. Collects photographs for the previous context
2. Compiles a multi-page PDF
3. Publishes the PDF through Telegram
4. Starts the upload to Google Drive
5. Resets the active session for the new context

A 20-minute inactivity watchdog also compiles and publishes the current session when no new activity is detected.

### Offline reliability

Google Drive uploads are queued in `pending_uploads.json` when the network or OAuth credentials are unavailable. A background spooler retries pending uploads every 30 seconds once connectivity is restored.

---

## Web interfaces

| Route | Purpose |
|---|---|
| `/` | Command-center dashboard |
| `/pi` or `/kiosk` | Full-screen 480×320 Raspberry Pi kiosk dashboard |
| `/pod` or `/pod_touch` | Touch-pod web emulator |
| `/projector` | High-contrast classroom projector view |
| `/report` | Principal/audit ledger and usage report |
| `/login` | Technician and principal login |
| `/admin` | Engineering and diagnostic control hub |
| `/video_feed` | Live MJPEG camera stream |
| `/api/status` | Real-time pod, camera, recording, network, and resource status |
| `/api/stream` | Server-sent status events |
| `/api/latest_asset` | Latest photo, PDF, and recording state |
| `/api/report_data` | Aggregate subjects, photos, videos, and audit records |
| `/api/report/download` | Download the activity report as JSON |
| `/api/camera/resolution` | Switch between 4K and 1080p camera modes |
| `/cmd/<action>` | Trigger photo, record, stop, subject, stats, compile, or reboot actions |
| `/trigger` | Form-compatible control trigger |
| `/media/<folder>/<filename>` | Serve stored photos, PDFs, and videos |

### Authentication

The diagnostic portal supports two roles:

- Technician: `Chorie / 1234`
- Principal: `principal / 1234`

The principal role is restricted to the reporting workflow and requires the active pilot classroom context.

> The credentials above are development defaults. Change them through the admin configuration interface before deployment.

---

## Diagnostic tools

The `/admin` portal provides:

- Runtime configuration read and save operations
- Google Drive credential upload and OAuth verification
- Telegram test-message dispatch
- Buzzer test tones with custom timing and frequency
- ESP32 pod connectivity checks
- Camera hardware testing
- Real-time microphone capture and dBFS analysis
- Diagnostic audio playback
- Bookmark/site management
- Temporary JPEG cache purging
- Upload-spool compaction
- Engine restart and safe power-off operations
- Local storage, CPU, memory, temperature, uptime, and disk information

The preview server exposes a hardware-free approximation of these flows for UI testing.

---

## Repository structure

```text
Project-Veronica/
├── main.py                         # Top-level Python launcher
├── preview_server.py               # Hardware-free preview server
├── launch_kiosk.sh                 # Chromium kiosk launcher
├── veronica-kiosk.service          # systemd kiosk service
├── requirements.txt                # Python dependencies
├── config.json                     # Persistent runtime configuration
├── activity_log.json               # Local activity ledger
├── pending_uploads.json            # Offline upload queue
├── ARCHITECTURE.md                 # System architecture notes
├── BOM.csv                         # Bill of materials
├── veronica_schematic.kicad_sch    # KiCad schematic
├── Veronica schmatic.svg           # Schematic SVG export
├── modules/
│   ├── main.py                     # Edge-hub orchestration loop
│   ├── hardware.py                 # TCP pod receiver and buzzer control
│   ├── camera.py                   # Capture, recording, and PDF compilation
│   ├── web_dashboard.py            # Flask pages and APIs
│   ├── config.py                   # Constants and dynamic configuration engine
│   ├── state.py                    # Thread-safe runtime state
│   ├── activity_logger.py          # Usage and subject audit records
│   ├── telegram_bot.py             # Telegram API integration
│   ├── drive_upload.py             # Google Drive API and upload spooling
│   └── system_utils.py             # Reports and system operations
├── esp32_firmware/
│   ├── esp32_touch_pod/            # Primary 3.5-inch TFT touch firmware
│   ├── esp32_sensor_pod/           # Sensor pod implementation
│   ├── esp32_lectern_pod.ino       # Legacy lectern firmware
│   ├── display_diagnostic_test/    # Display diagnostic firmware
│   └── legacy_archive/             # Older firmware variants
├── templates/
│   ├── index.html                  # Command-center dashboard
│   ├── pi_dashboard.html           # 480×320 Pi kiosk dashboard
│   ├── pod_touch.html              # 3.5-inch touch-pod emulator
│   ├── projector.html              # Classroom projector view
│   ├── report.html                 # Principal ledger
│   ├── admin.html                  # Diagnostic control portal
│   └── login.html                  # Technician/principal login
├── preview/                        # Preview copies of web templates
├── storage/
│   ├── photos/                     # Captured board photographs
│   ├── videos/                     # MP4 and M4A recordings
│   └── notes/                      # Compiled PDF documents
├── docs/
│   ├── ESP32_DISPLAY_SETUP_GUIDE.md
│   ├── CHANGELOG_2026-11-11.md
│   ├── CHANGELOG_TODAY_2026-11-12.md
│   └── ...                         # Additional setup and design notes
└── cad/                            # Enclosure and physical design assets
```

Key entry points:

- `main.py` launches the pod receiver, Telegram listener, spool worker, watchdog, Flask server, and keep-alive loop.
- `modules/main.py` contains the event handlers and edge-hub orchestration.
- `modules/config.py` loads persistent settings from `config.json`.
- `preview_server.py` serves the complete interface using simulated state.

---

## Hardware

### Primary ESP32 touch pod

- ESP32-WROOM-32D
- Robocrazе? 3.5-inch ILI9486 TFT with XPT2046 touch
- PN532 NFC reader in I²C mode
- Active buzzer
- 480×320 landscape display
- TCP over Wi-Fi

The display uses SPI for the TFT and touch controller. Detailed signal mapping is in `docs/ESP32_DISPLAY_SETUP_GUIDE.md`.

### Raspberry Pi 5 edge hub

- Raspberry Pi 5
- Kreo Owl 4K USB camera or compatible V4L2 camera
- USB conference microphone
- HDMI projector or classroom display
- Optional GPIO or kiosk display

Default pod listener settings:

```text
POD_SERVER_HOST=0.0.0.0
POD_SERVER_PORT=8765
KERO_VIDEO_DEVICE=/dev/video0
KERO_WIDTH=3840
KERO_HEIGHT=2160
KERO_FPS=30
```

---

## Software dependencies

The Python runtime uses:

- Flask
- Requests
- psutil
- Pillow
- Google API Python Client
- Google OAuth libraries

Install the requirements:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

System utilities commonly required on Raspberry Pi OS:

```bash
sudo apt update
sudo apt install -y python3-pip python3-opencv ffmpeg fswebcam v4l2-utils alsa-utils
```

Other ESP32 libraries required by the touch firmware include TFT_eSPI, Adafruit PN532, Adafruit BusIO, and ArduinoJson.

---

## Quick start

### 1. Install the Pi dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
sudo apt install -y ffmpeg fswebcam v4l2-utils alsa-utils
```

### 2. Configure the deployment

Create or edit `config.json`, or update values through `/admin`:

- Wi-Fi credentials
- Pod host and TCP port
- Telegram bot token and chat ID
- Google Drive folder ID
- Google OAuth or service credentials
- Camera and microphone devices
- Subject and NFC mappings
- Inactivity timeout
- Administrator credentials
- Useful-site bookmarks

### 3. Flash the ESP32 pod

Use `esp32_firmware/esp32_touch_pod/esp32_touch_pod.ino` for the primary touch display. Follow `docs/ESP32_DISPLAY_SETUP_GUIDE.md` for board selection, TFT_eSPI pin configuration, libraries, calibration, and Wi-Fi settings.

Legacy keypad firmware is available at `esp32_firmware/esp32_lectern_pod.ino`.

### 4. Launch Veronica

```bash
python3 main.py
```

The console reports the pod listener, web dashboard, projector view, and report route.

### 5. Open the interfaces

```text
http://<pi-ip>:5000/
http://<pi-ip>:5000/pi
http://<pi-ip>:5000/pod
http://<pi-ip>:5000/projector
http://<pi-ip>:5000/report
http://<pi-ip>:5000/login
http://<pi-ip>:5000/admin
```

### 6. Run hardware-free preview mode

```bash
python3 preview_server.py
```

Preview routes include:

```text
http://localhost:5000/
http://localhost:5000/pod
http://localhost:5000/pi
http://localhost:5000/projector
http://localhost:5000/report
http://localhost:5000/login
http://localhost:5000/admin
```

If port `5000` is busy, the preview server falls back to port `8080`.

---

## Raspberry Pi kiosk mode

`launch_kiosk.sh` starts the Flask backend, waits for it to become available, disables screen blanking, and launches Chromium in kiosk mode.

Install the systemd service with:

```bash
sudo cp veronica-kiosk.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now veronica-kiosk.service
```

The service uses `/home/pi/Project Veronica/launch_kiosk.sh` as its working deployment path. Adjust it if the repository is located elsewhere.

---

## Typical workflow

1. A teacher authenticates with NFC or opens the touch-pod interface.
2. The active subject is selected in the subject matrix.
3. Optical Scan captures a denoised board image.
4. The image appears on the live projector and is queued for the active subject session.
5. Audio-only or video-and-audio recording begins when required.
6. The teacher can compile a PDF during class or terminate the current context.
7. Subject handover or inactivity triggers automatic PDF compilation and publication.
8. Telegram and Google Drive receive the completed lecture notes.
9. The principal view reports subject, photo, video, audio, and session activity.

---

## Security notes

- Critical shutdown and restart actions require the configured physical passcode: `1-9-2-7`.
- Default web credentials are not production credentials and should be replaced.
- OAuth credentials, Telegram tokens, and Wi-Fi secrets should not be committed publicly.
- The HTTP service has no TLS by default; isolate the classroom network or place it behind an authenticated reverse proxy when exposed beyond the local LAN.

---

## Design and changelog references

- `ARCHITECTURE.md` — system topology and data flow
- `docs/CHANGELOG_2026-11-11.md` — distributed architecture and module refactor notes
- `docs/CHANGELOG_TODAY_2026-11-12.md` — touch-pod migration and display integration notes
- `docs/ESP32_DISPLAY_SETUP_GUIDE.md` — complete ESP32 TFT setup guide
- `BOM.csv` — hardware bill of materials
- `veronica_schematic.kicad_sch` — KiCad electrical schematic
- `Veronica schmatic.svg` — schematic export
- `cad/` — enclosure and physical design assets

---

## Licensing

This project is licensed under the MIT License. See `LICENSE` for details.

## Status

The repository contains an active Raspberry Pi/ESP32 edge prototype with live camera tooling, PDF and recording workflows, Telegram/Drive automation, touch-screen hardware support, Pi kiosk support, a preview server, and a principal/technician web interface. This is an education-focused reference implementation rather than a finished commercial AV platform.
