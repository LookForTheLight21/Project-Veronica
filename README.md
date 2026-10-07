# Project Veronica: Distributed Multimodal IoT Lecture Capture & Edge Telemetry System

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Hardware](https://img.shields.io/badge/Platform-Raspberry%20Pi%205%20%7C%20ESP32-red.svg)]()

> **Competition Track:** Theme 2: Education & Skill Development  
> **Sub-Theme:** Tangible, Haptic & Multi-Modal Interfaces  
> **Applicant:** Piyush Shukla

---

## 📌 Overview
Underfunded rural and Tier-2 classrooms cannot afford commercial Interactive Flat Panels (IFPs costing ₹1.5L+). **Project Veronica** is an ambient, screenless edge-IoT lecture capture appliance designed to digitize traditional chalkboards at under ₹12,000 total capital cost.

Using a physical-first workflow, teachers tap their NFC identity badge to log attendance and set the subject context. Tactile membrane/capacitive keys trigger 4K board captures and lecture video/audio recordings. Lesson notes and clips are processed on the edge, archived to Google Drive, and syndicated to student WhatsApp/Telegram groups within 60 seconds of class completion.

---

## ⚙️ Key Technical Features
- **Deterministic Tactile I/O:** Bare-metal NFC authentication (PN532 via I2C) and 16-key matrix keypad control with acoustic buzzer feedback.
- **Computational Photography Pipeline:** Multi-frame temporal blending (`fswebcam -F 5`) to eliminate chalkboard glare, dust scatter, and low-light sensor noise.
- **Hardware-Accelerated Encoding:** Real-time H.264/AAC media multiplexing via FFmpeg with non-volatile local spooling queues for offline resilience during internet outages.
- **Tamper Protection:** Critical system functions (shutdown/reboot) protected by a 4-digit physical sequence (`1-9-2-7`).
- **Telemetry & Diagnostic Portal:** Responsive glassmorphic Flask web dashboard for administrative attendance and syllabus progress tracking.

---

## 🔌 Hardware Architecture & Wiring

### 1. Desk Pod (Lectern Tier)
- **Controller:** ESP32 / Direct GPIO on Raspberry Pi 5
- **NFC Module:** NXP PN532 via I2C (`SDA`: GPIO 2 / Pin 3, `SCL`: GPIO 3 / Pin 5)
- **Keypad Matrix:** Rows: `[GPIO 6, 5, 11, 26]`, Cols: `[GPIO 10, 22, 27, 17]`
- **Acoustic Transducer:** 5V Active Buzzer (`GPIO 23`)

### 2. Overhead Compute Hub (Ceiling Tier)
- **Compute Unit:** Raspberry Pi 5 (8GB) powered by Official 27W USB-C PSU
- **Camera:** Kreo Owl 4K Pro (Sony IMX sensor connected via USB 3.0)

---

## 🚀 Setup & Installation

### 1. System Dependencies (Raspberry Pi OS - Bookworm)
```bash
sudo apt update && sudo apt install -y python3-pip python3-opencv fswebcam ffmpeg v4l2-utils
