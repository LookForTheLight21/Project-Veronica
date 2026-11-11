# Project Veronica

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Raspberry Pi 5](https://img.shields.io/badge/Platform-Raspberry%20Pi%205-red.svg)]()

Project Veronica is a distributed, multimodal lecture-capture and classroom telemetry system designed for low-cost, resource-constrained educational environments. It combines a physical teacher console, edge compute on a Raspberry Pi 5, real-time classroom capture, WhatsApp/Telegram notifications, Google Drive archival, and a local Flask dashboard for diagnostics and subject tracking.

This repository contains the full system implementation for the two-tier edge architecture:

- Tier 1: ESP32 lectern pod with keypad, NFC, and buzzer
- Tier 2: Raspberry Pi 5 edge hub with camera, audio capture, dashboard, Telegram integration, and Drive upload workflows

---

## Overview

Underfunded rural and Tier-2 classrooms often cannot afford commercial interactive flat panels or expensive AV systems. Project Veronica creates a screenless, tactile-first lecture appliance that enables teachers to:

- log in with NFC badges
- switch classroom subject context with a physical input
- take instant photographs of the board
- start and stop lecture audio/video capture
- publish notes as compiled PDF bundles
- push status updates to Telegram and Google Drive
- launch a projector-facing classroom view
- monitor system health from a web dashboard

The system is intentionally designed to function as an edge-first kit: minimal infrastructure, local recording first, cloud sync later, and physical controls that work even when internet connectivity is poor.

---

## System architecture

### Tier 1 — Teacher Lectern Pod (ESP32)

The lectern pod is responsible for low-latency physical input and local feedback.

Hardware components:

- ESP32-WROOM-32D microcontroller
- TTP229 keypad scanner for 16-key matrix input
- PN532 NFC reader via I2C
- Active buzzer for confirmation and alerts
- Wi-Fi link to the Raspberry Pi 5 host

Key responsibilities:

- capture keypad events
- read NFC teacher IDs and subject actions
- send events over TCP to the Pi 5
- provide tactile feedback using the buzzer

### Tier 2 — Overhead Edge Compute Hub (Raspberry Pi 5)

The Pi 5 acts as the edge orchestration and processing hub.

Hardware components:

- Raspberry Pi 5
- Kreo Owl 4K camera or equivalent USB webcam
- USB conference microphone
- Classroom display/projector output
- Local Flask dashboard and telemetry web UI

Key responsibilities:

- receive pod events from the ESP32
- manage subject and recording state
- capture board images and multi-page notes
- compile lecture PDFs from captured frames
- stream media to Telegram and Google Drive
- expose local admin and projector endpoints
- enforce secure shutdown/reboot flow with a physical passcode

---

## Core features

- NFC-based teacher login and subject handoff
- Subject-aware note collection across classes
- Photo capture and board documentation
- Audio-only and video+audio recording modes
- Automatic PDF compilation for lecture sessions
- Local spooling and failover for offline synchronization
- Telegram notifications, reports, and admin alerting
- Google Drive archival and file upload workflow
- Flask dashboard for classroom telemetry and service status
- Secure physical shutdown/restart sequence: 1-9-2-7
- Projector view endpoint for back-row student access

---

## Repository structure

```text
Project-Veronica/
├── ARCHITECTURE.md
├── BOM.csv
├── LICENSE
├── README.md
├── main.py
├── requirements.txt
├── test_cam.py
├── veronica_schematic.kicad_sch
├── Veronica schmatic.svg
├── cad/
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
└── storage/
    ├── photos/
    ├── videos/
    └── notes/
```

The main runtime entry point is:

- `main.py` — bootstraps the system by importing the core module logic
- `modules/main.py` — primary event loop, controller logic, and service startup
- `modules/config.py` — device mappings, credentials, network configuration, and key definitions
- `modules/web_dashboard.py` — Flask dashboard and classroom endpoints

---

## Hardware and wiring

### ESP32 lectern pod

Key hardware mapping used by the project:

| Peripheral | Connection |
|---|---|
| Buzzer | GPIO 23 |
| TTP229 SCL | GPIO 18 |
| TTP229 SDO | GPIO 19 |
| PN532 SDA | GPIO 21 |
| PN532 SCL | GPIO 22 |
| Power | 3.3V / 5V rail |
| Ground | Common GND |

The TP229 keypad is configured for active-low serial key scanning, and the PN532 handles NFC identity events. The full ESP32 firmware and setup notes can be found in `esp32_firmware/`.

### Raspberry Pi 5 edge hub

The Pi 5 runs the main orchestration service and captures from the classroom sensor stack.

Configured defaults in `modules/config.py`:

- `POD_SERVER_HOST = "0.0.0.0"`
- `POD_SERVER_PORT = 8765`
- `KERO_VIDEO_DEVICE = "/dev/video0"`
- `KERO_AUDIO_DEVICE = "plughw:CARD=webcam,DEV=0"`
- `KERO_WIDTH = 3840`
- `KERO_HEIGHT = 2160`

---

## Key behavior and control mappings

The project uses both physical key input and NFC actions to drive the edge workflow.

### Mode keys

| Key | Action |
|---|---|
| 1 | PHOTO |
| 2 | VIDEO_TOGGLE |
| 3 | AUDIO_TOGGLE |
| 4 | PRIORITY_AUDIO_TOGGLE |
| 6 | STATS |
| 7 | STOP |
| 13 | CLEAR_SUBJECT |
| 14 | SECURE_SHUTDOWN |
| 15 | SECURE_RESTART |

### Subject and NFC mappings

The system maps known RFID tags to subject names and operational actions:

- `Physics`
- `Chemistry`
- `Computer Science`
- `English`
- `Math`
- `ACTION:PROJECTOR`
- `ACTION:SHUTDOWN`
- `ACTION:ADMIN_ALERT`

### Emergency security flow

A four-digit physical sequence is enforced for critical functions:

- `1-9-2-7`

This sequence is used to trigger shutdown or reboot safely from the lectern hardware interface.

---

## Software stack

The project is built with Python and edge hardware tooling:

- Python 3.11+
- Flask for the dashboard and local web endpoints
- OpenCV for image-processing and camera tasks
- FFmpeg for media capture and muxing
- GPIO access via `gpiozero` and hardware interfaces
- Google API client for Drive uploads
- Telegram bot integration for live classroom updates
- Adafruit PN532 support for NFC communication

Install dependencies with:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Quick start

### 1. Install dependencies

```bash
sudo apt update && sudo apt install -y python3-pip python3-opencv fswebcam ffmpeg v4l2-utils
pip install -r requirements.txt
```

### 2. Configure device settings

Edit `modules/config.py` to match your local classroom setup:

- Wi-Fi SSID/password for the Pi-to-ESP32 link
- Telegram bot token and chat ID
- Google Drive folder ID
- Camera and microphone device paths
- project-specific subject mapping

### 3. Launch the system

```bash
python3 main.py
```

This starts the local services, the pod receiver, the camera/audio handlers, and the Flask web dashboard.

### 4. Access the dashboard

Once running, the system exposes:

- `http://0.0.0.0:5000`
- `http://0.0.0.0:5000/projector`
- `http://0.0.0.0:5000/report`

---

## Notes and workflow

Project Veronica is optimized for a real classroom workflow:

1. Teacher taps NFC badge or uses subject key input.
2. Subject context is associated with the class session.
3. Board image captures are stored in the session photo set.
4. Teacher can record audio or video while teaching.
5. At the end of the period, the session can be finalized into a PDF or uploaded.
6. Telegram and Google Drive receive updates and archival outputs.

This enables a low-friction, physical-first experience in classrooms that do not have reliable digital infrastructure or expensive institutional equipment.

---

## Design references

The repository includes supporting design artifacts:

- `ARCHITECTURE.md` — architecture and system topology
- `BOM.csv` — bill of materials for the build
- `veronica_schematic.kicad_sch` — KiCad schematic
- `Veronica schmatic.svg` — vector schematic export
- `cad/` — CAD/physical design materials
- `esp32_firmware/` — embedded firmware and wiring guide

---

## Licensing

This project is licensed under the MIT License. See `LICENSE` for details.

---

## Contribution notes

This project is intended as a practical education-focused hardware + software prototype. Contributions are welcome if they improve:

- edge reliability
- classroom usability
- hardware compatibility
- media processing quality
- offline resilience
- low-cost deployment practice

---

## Status

This repository reflects the current implementation of the Project Veronica system with:

- ESP32 lectern hardware integration
- Raspberry Pi 5 edge orchestration
- subject- and action-aware key handling
- Telegram + Drive integration
- projector dashboard outputs
- secure physical control flow

The implementation is ready as a prototype and deployment-oriented reference architecture for classroom edge IoT capture systems.
