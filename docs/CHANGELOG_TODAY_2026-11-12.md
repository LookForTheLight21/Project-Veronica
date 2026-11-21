# Project Veronica — Daily Engineering Changelog
**Date:** November 12, 2026  
**Document:** ESP32 3.5" Touch Pod Migration, C++ Firmware Architecture & Display Integration  
**Target Architecture:** Raspberry Pi 5 Overhead Core + ESP32 Wireless Desk Pod (480×320 SPI TFT)

---

## 1. Executive Summary

Today's focus established the complete transition from the legacy physical keypad to an intelligent **3.5-inch 480×320 Landscape Touchscreen Pod** mounted on the teacher's podium. This was paired with the physical verification and pin-mapping of the **3.5" RPi Display (ILI9486 + XPT2046)** hardware for direct ESP32 integration, eliminating physical cabling constraints while maintaining full backwards compatibility.

---

## 2. What Has Been ADDED

### 2.1 Physical ESP32 C++ Touch Firmware (`esp32_firmware/esp32_touch_pod.ino`)
* **Pure C++ Bare-Metal Driver**: Written natively using `TFT_eSPI` and `XPT2046_Touchscreen` for standalone ESP32 operation with **zero browser or HTML dependencies**.
* **3-Slide Horizontal Carousel (4 Buttons Per Slide)**:
  * **Slide 1 (Capture & Core Tools)**: *Optical Scan*, *Compile & Send*, *4K Stream (Rec)*, *Voice Note (Rec)*.
  * **Slide 2 (Presentation & Diagnostic)**: *Wall Projector*, *Standby / Sleep*, *Telemetry Report*, *Reboot Pod Hub*.
  * **Slide 3 (Subject Context Matrix)**: *Physics*, *Chemistry*, *Mathematics*, *Computer Science*.
* **Live Recording HUD Overlay (`drawRecordingHUD`)**:
  * Real-time `MM:SS` duration ticker tracking active lecture recording.
  * Pulsing red status beacon and resolution tag (`3840x2160 @ 30 FPS H.264`).
  * Giant `430px × 76px` high-visibility tactile **`TERMINATE & ARCHIVE RECORDING`** stop button.
  * Automatic suppression of screen timeout during active recording sessions.
* **NFC Teacher Greeting Flash Card (`drawNFCWelcomeCard`)**:
  * Full-screen high-gloss pop-up card displaying teacher identity (e.g., *Prof. H. C. Verma · Department of Physics*).
  * Synthesized melodic dual-tone chime (`beep(1, 60, 20, 2200); beep(1, 100, 20, 3000)`).
* **Anti-Misuse Console Interlock Guard (`showInterlockAlert`)**:
  * Prevents student tampering by locking Slide 1 capture tools until a teacher NFC badge or subject is unlocked.
  * Low-frequency warning acoustic alert (`800Hz`) and visual authentication modal.
* **Display Sleep & Slide-to-Unlock**:
  * Screen blanks to pitch black (`#000000`) and cuts backlight PWM after 60 seconds of inactivity to protect the TFT backlight.
  * Smooth slide-to-unlock gesture resumes operation instantly.
* **Dual Theme Engine (Day & Night Mode)**:
  * Full palette inversion between obsidian dark mode (`#07090E`) and pure daylight white (`#FFFFFF`).

### 2.2 Hardware Pin Configuration & Verification (`esp32_firmware/Display_Config.h`)
* Verified and configured the **3.5" RPi Display (ILI9486 + XPT2046)** SPI module for ESP32 connection:
  * `5V` (Pins 2/4) &rarr; ESP32 `VIN` (Backlight & 3.3V LDO)
  * `GND` (Pins 6/9/14/20/25) &rarr; ESP32 `GND`
  * `LCD_SCK / TP_SCK` (Pin 23) &rarr; ESP32 `GPIO 18` (VSPI SCK)
  * `LCD_SI / MOSI` (Pin 19) &rarr; ESP32 `GPIO 23` (VSPI MOSI)
  * `TP_SO / MISO` (Pin 21) &rarr; ESP32 `GPIO 19` (VSPI MISO - Touch feedback)
  * `LCD_CS` (Pin 24) &rarr; ESP32 `GPIO 15`
  * `LCD_RS / DC` (Pin 18) &rarr; ESP32 `GPIO 2`
  * `LCD_RST` (Pin 22) &rarr; ESP32 `GPIO 4`
  * `TP_CS` (Pin 26) &rarr; ESP32 `GPIO 5`
* Leaves dedicated GPIOs free for `PN532/RC522` RFID reader (`GPIO 21`, `GPIO 22`) and Buzzer (`GPIO 25`).

### 2.3 Interactive Web Digital Twin / Simulator (`/pod` &rarr; `templates/pod_touch.html`)
* **1:1 Hardware Emulator**: Serves an exact pixel-matched digital twin on `http://localhost:5000/pod` for classroom demonstrations and judge presentations without needing physical hardware connected.
* **Hardware Bezel Simulation Buttons**:
  * `🏷️ Tap NFC (Physics)` — Simulates teacher RFID badge tap.
  * `🧪 Chemistry` — Simulates instant subject change.
  * `🛡️ Lockout` — Tests anti-misuse interlock mode.

### 2.4 Server Routing & Protocol Linkage
* Added `@app.route("/pod")` and `@app.route("/pod_touch")` to both `preview_server.py` and `modules/web_dashboard.py`.
* Added TCP socket command dispatching (`cmd` event) in `modules/hardware.py` and `modules/main.py` allowing wireless execution of touch actions over TCP port 8765.

---

## 3. What Has Been MODIFIED

* **Touchscreen Flexbox Viewport Re-engineering**:
  * Fixed an issue where percentage-based tracks compressed multiple slides into 4 squished columns.
  * Enforced strict physical dimensions: `.slider-viewport` locked to `480px × 240px`, `.slider-track` locked to `1440px` (`min-width: 1440px; flex-shrink: 0`), and `.slide-page` locked with `flex: 0 0 480px; flex-shrink: 0`.
* **Legacy Pod Scripting (`esp32_firmware/esp32_lectern_pod.ino`)**:
  * Maintained physical keypad pin mapping intact while deactivating active matrix polling in favor of the new touch pod architecture.

---

## 4. Hardware Selection Assessment

| Module | Interface | Pins Needed | Touch IC | Status |
| :--- | :--- | :--- | :--- | :--- |
| **SIMKEIM Red Board** | 8-Bit Parallel | 13+ GPIOs | None (Analog ADC mux) | **REJECTED** (Pin exhaustion, ADC jitter) |
| **3.5" RPi Blue Board** | High-Speed SPI | 8 GPIOs | **XPT2046** Dedicated | **SELECTED & APPROVED** (Zero jitter, standard 3.3V logic) |

---

## 5. Verification Status

* **Firmware Syntax & Header Checks**: `esp32_touch_pod.ino` and `Display_Config.h` validated.
* **Preview Server**: Successfully serving on port 5000 with HTTP 200 response.
* **Touch Emulator**: All 3 slides, recording HUD modal, teacher NFC card, and anti-misuse interlock verified operational.

