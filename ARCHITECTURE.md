# System Architecture & Technical Design Document: Project Veronica

## 1. System Topology & Data Flow

```text
                  ┌────────────────────────────────────────┐
                  │          Teacher Podium Pod            │
                  │   [PN532 NFC Module]  [Keypad Array]   │
                  └───────────────────┬────────────────────┘
                                      │
                        (Deterministic Low-Latency Bus)
                                      │
                                      ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                   Overhead Edge Compute Hub (Pi 5)                       │
│                                                                          │
│  ┌─────────────────────────┐          ┌───────────────────────────────┐  │
│  │    Hardware Subsystem   │          │        Media Pipeline         │  │
│  │ • lgpio state machine   │          │ • fswebcam (-F 5 blending)    │  │
│  │ • 1-9-2-7 Security Lock │          │ • FFmpeg (H.264/AAC Mux)      │  │
│  └────────────┬────────────┘          └───────────────┬───────────────┘  │
│               │                                       │                  │
│               ▼                                       ▼                  │
│  ┌─────────────────────────┐          ┌───────────────────────────────┐  │
│  │    Diagnostics Portal   │          │     Offline Spooling Buffer   │  │
│  │    • Port 5000 FlaskUI  │          │     • Edge failover queue     │  │
│  └─────────────────────────┘          └───────────────┬───────────────┘  │
└───────────────────────────────────────────────────────┼──────────────────┘
                                                        │
                                             (Wi-Fi / Mobile Uplink)
                                                        │
                         ┌──────────────────────────────┴──────────────────────────────┐
                         ▼                                                             ▼
             [Google Drive Storage]                                         [Instant Student Push]
             (Month/Subject Archival)                                       (Telegram & WhatsApp)
