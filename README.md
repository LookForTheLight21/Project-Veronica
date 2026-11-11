# Project Veronica

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Raspberry Pi 5](https://img.shields.io/badge/Platform-Raspberry%20Pi%205-red.svg)]()

Project Veronica is a distributed, multimodal classroom capture and edge-control system built for low-cost, resource-constrained schools. It combines a physical lectern interface with a Raspberry Pi-based orchestration layer to record teacher activity, compile classroom notes, manage subject context, and publish live classroom data to local dashboards, Telegram, and Google Drive.

The system is designed around a practical classroom reality: limited infrastructure, unreliable network access, and the need for tactile operation when digital systems fail. Veronica is intentionally built as an edge-first prototype that works with local capture first and cloud synchronization later.

---

## Overview

Project Veronica was designed for schools and teachers who need a low-cost digital teaching surface without a full commercial interactive panel installation. The system allows a teacher to:

- log in with NFC badges
- switch subject context with physical input
- capture board images and notes
- record audio or video lecture content
- compile captured session pages into PDF notes
- publish updates to Telegram and Google Drive
- launch a projector-facing classroom view
- monitor the system through a local dashboard and diagnostics portal
- trigger secure shutdown or reboot with a physical passcode

This repository contains the full implementation of the two-tier architecture, including the embedded logic for the teacher pod, the edge hub orchestrator, dashboard templates, diagnostic tools, and deployment-related design assets.

---

## System architecture

### Tier 1 — Teacher lectern pod (ESP32)

The ESP32-based lectern pod handles low-latency physical interaction and immediate feedback.

Hardware components:

- ESP32-WROOM-32D microcontroller
- TTP229 keypad scanner
- PN532 NFC reader
- Active/passive buzzer
- Wi-Fi radio link to the Pi 5

Responsibilities:

- receive keypad inputs
- read NFC teacher IDs and action tags
- send event data to the Raspberry Pi via TCP
- provide local tactile confirmation using the buzzer

### Tier 2 — Edge compute hub (Raspberry Pi 5)

The Raspberry Pi 5 acts as the orchestration and processing hub for the entire classroom workflow.

Hardware components:

- Raspberry Pi 5
- Kreo Owl 4K camera or compatible USB camera
- USB conference microphone
- local projector display output
- Flask-based dashboard and diagnostics interface

Responsibilities:

- receive pod events from the ESP32
- manage subject context and recording state
- capture board images and notes
- compile multi-page lecture PDFs
- stream content and notifications to Telegram and Drive
- expose local classroom and admin web endpoints
- handle secure shutdown/reboot flow with a physical passcode

---

## Current feature set

The repository includes the following operational features and workflows:

- NFC-based teacher login and subject handoff
- subject-aware session tracking across classes
- photo capture and board-note accumulation
- audio-only and video + audio lecture recording
- automatic or manual PDF compilation from session captures
- offline spooling and upload retry workflow for Drive/Telegram
- Telegram notifications, classroom reports, and admin alerts
- Google Drive archival and file upload support
- Flask dashboard and local web endpoints
- projector view for classroom display
- secure physical shutdown/restart flow using the 1-9-2-7 sequence
- dynamic configuration engine for field technician updates
- local preview server for simulation and UI testing without hardware

---

## Repository structure

```text
Project-Veronica/
├── ARCHITECTURE.md
├── BOM.csv
├── LICENSE
├── README.md
├── config.json
├── main.py
├── preview_server.py
├── requirements.txt
├── test_cam.py
├── veronica_schematic.kicad_sch
├── Veronica schmatic.svg
├── cad/
├── docs/
├── esp32_firmware/
├── modules/
│   ├── __init__.py
│   ├── activity_logger.py
│   ├── camera.py
│   ├── config.py
│   ├── drive_upload.py
│   ├── hardware.py
│   ├── main.py
│   ├── state.py
│   ├── system_utils.py
│   ├── telegram_bot.py
│   └── web_dashboard.py
├── preview/
├── storage/
│   ├── photos/
│   ├── videos/
│   └── notes/
├── templates/
│   ├── admin.html
│   ├── index.html
│   ├── login.html
│   ├── projector.html
│   ├── report.html
│   └── sample_board.svg
└── __pycache__/
```

Key runtime entry points:

- `main.py` — top-level launcher for the system
- `modules/main.py` — orchestration loop, event handling, pod receiver, startup routines
- `modules/config.py` — default runtime settings, hardware mappings, dynamic config engine
- `modules/web_dashboard.py` — Flask dashboard, admin portal, projector route, command endpoints
- `preview_server.py` — local simulation server for previewing UI and diagnostics without hardware
- `templates/` — web templates for dashboard, projector, login, admin, and report views

---

## Hardware and wiring

### ESP32 lectern pod

Core mapping used by the system:

| Peripheral | Connection |
|---|---|
| Buzzer | GPIO 23 |
| TTP229 SCL | GPIO 18 |
| TTP229 SDO | GPIO 19 |
| PN532 SDA | GPIO 21 |
| PN532 SCL | GPIO 22 |
| Power | 3.3V / 5V rail |
| Ground | Common GND |

The pod communicates with the Pi over Wi-Fi and drives short tactile response codes during subject changes, recording events, and system alerts.

### Raspberry Pi 5 edge hub

Default camera and media parameters defined in `modules/config.py` include:

- `POD_SERVER_HOST = "0.0.0.0"`
- `POD_SERVER_PORT = 8765`
- `KERO_VIDEO_DEVICE = "/dev/video0"`
- `KERO_AUDIO_DEVICE = "plughw:CARD=webcam,DEV=0"`
- `KERO_WIDTH = 3840`
- `KERO_HEIGHT = 2160`
- `KERO_FPS = 30`

---

## Key input and action mapping

### Mode keys

| Key | Action |
|---|---|
| 1 | PHOTO |
| 2 | VIDEO_TOGGLE |
| 3 | AUDIO_TOGGLE |
| 4 | PRIORITY_AUDIO_TOGGLE |
| 6 | STATS |
| 7 | STOP |
| 8 | COMPILE_PDF |
| 13 | CLEAR_SUBJECT |
| 14 | SECURE_SHUTDOWN |
| 15 | SECURE_RESTART |

### Subject and NFC mappings

The system recognizes subject-based NFC tags and action tags such as:

- `Physics`
- `Chemistry`
- `Computer Science`
- `English`
- `Math`
- `ACTION:PROJECTOR`
- `ACTION:SHUTDOWN`
- `ACTION:ADMIN_ALERT`

### Emergency security flow

A four-digit physical sequence is enforced for critical actions:

- `1-9-2-7`

This sequence is used to confirm a shutdown or reboot request from the lectern interface and prevents accidental destructive operations.

---

## Dynamic configuration and field updates

The project now includes a dynamic configuration engine in `modules/config.py` that persists environment-specific settings in a root-level `config.json` file.

This allows a technician to update values without editing source code directly, including:

- Wi-Fi SSID and password
- pod host and port
- Telegram token and chat ID
- allowed users
- Google Drive folder ID
- camera and audio device configuration
- recording timeout values
- subject and action mappings
- admin credentials

The runtime configuration is loaded from `config.json` on import, and can also be saved and reloaded via the diagnostic admin route.

---

## Web dashboard and admin features

The project exposes a local web stack for classroom and admin control.

### Endpoints

- `/` — command center dashboard
- `/projector` — full-screen projector view for back-row students
- `/report` — principal / audit report page
- `/login` — technician and principal login UI
- `/admin` — engineering and diagnostic control portal
- `/api/latest_asset` — latest photo, PDF, recording state, and telemetry JSON
- `/api/admin/config` — read runtime configuration
- `/api/admin/save_config` — update config values dynamically
- `/api/admin/test_buzzer` — dispatch a hardware test tone
- `/api/admin/test_telegram` — send a Telegram verification ping
- `/cmd/<action>` — REST triggers for photo, video, audio, subject switching, stats, and reboot actions
- `/media/<folder>/<filename>` — local media asset routing for photos, notes, and videos

### Authentication

The live admin portal recognizes:

- technician login: `Chorie / 1234`
- principal login: `principal / 1234`

---

## Local preview mode

A standalone `preview_server.py` is included to simulate the operational UI without hardware dependencies.

This is useful for:

- UI review
- local dashboard development
- testing admin flows and endpoints
- validating simulated classroom state without Raspberry Pi hardware

Run it with:

```bash
python3 preview_server.py
```

Then open:

- `http://localhost:5000/`
- `http://localhost:5000/projector`
- `http://localhost:5000/report`
- `http://localhost:5000/login`
- `http://localhost:5000/admin`

---

## Software stack

The project is built around Python and edge hardware tooling:

- Python 3.11+
- Flask for dashboard and API services
- OpenCV and camera processing utilities
- FFmpeg for media capture and muxing
- Pillow for image workflows
- Google API client for Drive integration
- `requests`, `psutil`, and supporting Python libs
- GPIO and hardware integration for the ESP32 and Pi stack
- Telegram bot integration for notifications and alerts

Install dependencies with:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

System packages often needed on the Raspberry Pi:

```bash
sudo apt update
sudo apt install -y python3-pip python3-opencv ffmpeg v4l2-utils
```

---

## Quick start

### 1. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure the deployment

Edit `config.json` or the runtime values in `modules/config.py` to match your classroom setup:

- Wi-Fi SSID and password
- Raspberry Pi pod server settings
- Telegram token and chat ID
- Google Drive folder ID
- camera and microphone device paths
- admin and technician credentials
- subject mapping and action tags

### 3. Launch the main system

```bash
python3 main.py
```

### 4. Access the classroom interfaces

Once running, the system exposes the following local endpoints:

- `http://0.0.0.0:5000`
- `http://0.0.0.0:5000/projector`
- `http://0.0.0.0:5000/report`
- `http://0.0.0.0:5000/admin`

---

## Operational workflow

A typical teaching session follows this flow:

1. Teacher taps an NFC badge or presses a subject key on the lectern.
2. Subject context is associated with the active class session.
3. Teacher captures board images and notes during instruction.
4. Audio or video recording is started based on classroom needs.
5. Session content is compiled into a PDF or uploaded to Drive.
6. Telegram and local dashboards continue to reflect classroom status.
7. A secure physical passcode can be used to shut down or reboot the system when necessary.

This creates a low-friction, physical-first teaching experience optimized for classrooms that do not have expensive proprietary AV systems or strong network infrastructure.

---

## Design references

Additional project artifacts are included in the repository:

- `ARCHITECTURE.md` — architecture and design notes
- `BOM.csv` — bill of materials
- `veronica_schematic.kicad_sch` — KiCad schematic
- `Veronica schmatic.svg` — vector diagram export
- `cad/` — design and enclosure references
- `esp32_firmware/` — embedded pod firmware and wiring-related files
- `docs/` — supporting documentation and deployment notes

---

## Licensing

This project is licensed under the MIT License. See `LICENSE` for details.

---

## Contribution notes

This project is intended as a practical, education-focused hardware + software prototype. Contributions are welcome in areas such as:

- edge reliability and fault tolerance
- classroom usability and control ergonomics
- hardware compatibility
- media processing quality
- offline resilience
- low-cost deployment patterns

---

## Status

The current repository reflects the active implementation of the Project Veronica system, including:

- ESP32 lectern pod integration
- Raspberry Pi 5 orchestration loop
- dynamic configuration engine
- live dashboard and admin control interface
- projector and reporting endpoints
- Telegram and Drive automation
- subject-aware note capture and PDF output
- secure physical control sequence
- local preview / simulation tooling

This is a working prototype and reference architecture for an edge-first classroom capture and telemetry platform.
