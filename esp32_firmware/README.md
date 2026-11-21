# Project Veronica — Tier 1: Teacher Lectern Pod Firmware

This directory contains the production embedded C++ firmware for the **ESP32-WROOM-32D** teacher lectern controller.

---

## 📌 Firmware Profiles Available

| Firmware File | Input Method | Display | Description |
|---|---|---|---|
| **`esp32_touch_pod.ino`** *(Active)* | **3.5" Touch Screen** | **3.5" TFT (480×320 Landscape)** | 4 large buttons per slide (2×2 grid), touch gestures/swipes, 60s OLED sleep saver, Day/Night mode toggle, Wi-Fi TCP streaming to Pi 5. |
| **`esp32_lectern_pod.ino`** *(Legacy)* | **16-Key Capacitive** | *None / Status LEDs* | Original TTP229 16-key capacitive keypad code (preserved 100% in codebase, currently disabled via `KEYPAD_ENABLED = False`). |

---

## 🔌 3.5" Touchscreen Pod Hardware Pinout (`esp32_touch_pod.ino`)

Standard 3.5-inch SPI TFT LCD (ILI9488 / ST7796) with XPT2046 touch controller:

| Pin Name | ESP32 Pin | Function |
|---|---|---|
| **TFT_MOSI** | `GPIO 23` | SPI Master Out Slave In |
| **TFT_MISO** | `GPIO 19` | SPI Master In Slave Out |
| **TFT_SCLK** | `GPIO 18` | SPI Clock |
| **TFT_CS** | `GPIO 15` | LCD Chip Select |
| **TFT_DC / RS** | `GPIO 2` | LCD Data/Command Select |
| **TFT_RST** | `GPIO 4` | LCD Hardware Reset |
| **TFT_BL** | `GPIO 32` | Backlight Brightness Control (LEDC PWM for Sleep Mode) |
| **TOUCH_CS** | `GPIO 5` | XPT2046 Touch Chip Select |
| **TOUCH_IRQ** | `GPIO 27` | Touch Interrupt (Active Low) |
| **BUZZER** | `GPIO 25` | Passive Piezo Buzzer via BC547 Transistor Buffer |
| **PN532 SDA** | `GPIO 21` | NFC I2C Data (400 kHz) |
| **PN532 SCL** | `GPIO 22` | NFC I2C Clock |
| **VCC / GND** | `5V / 3.3V / GND` | Power rail (5V USB-C or regulator) |

---

## 🛠️ Arduino IDE / PlatformIO Setup

1. **Board Manager**: Install `esp32` by Espressif Systems (Board: **ESP32 Dev Module**).
2. **Required Libraries**:
   - `TFT_eSPI` by Bodmer (configured for ILI9488 / ST7796 @ 480x320)
   - `Adafruit PN532` by Adafruit
   - `Wire` & `WiFi` (Built into ESP32 core)
3. **`User_Setup.h` Configuration for TFT_eSPI**:
   Ensure `TFT_eSPI/User_Setup.h` matches the pin configuration in `Display_Config.h`.

---

## 📡 Wireless Communication with Raspberry Pi 5

The ESP32 runs standalone on the teacher's podium across the room from the ceiling-mounted Raspberry Pi 5:

```
[Teacher Pod: ESP32 + 3.5" Touchscreen]
               │
          Wi-Fi (5.8 GHz / 2.4 GHz)
               │
               ▼
[Raspberry Pi 5 Hub: 192.168.4.1:8765 TCP Socket]
               │
       ┌───────┴───────┐
       ▼               ▼
[Kreo 4K Camera]  [HDMI Projector]
```

- When a button is tapped, the ESP32 generates instant local acoustic feedback (<5ms) and sends a JSON packet to the Pi 5 over the persistent TCP socket:
  ```json
  {"event": "cmd", "action": "photo"}
  ```
- Sub-10ms round-trip latency ensures classroom actions occur instantaneously.
- The Pi 5 streams status and buzzer alerts back to the ESP32:
  ```json
  {"status": "ok", "subject": "PHYSICS", "cmd": "beep"}
  ```
