# Project Veronica — Tier 1: Teacher Lectern Pod Firmware

This folder contains the firmware for the **ESP32-WROOM-32D** desk console.

---

## 📌 Wiring Diagram

| Peripheral | ESP32 Pin | Details |
|---|---|---|
| **Buzzer** | `GPIO 23` | Active 5V Piezo driven via NPN BC547 transistor buffer |
| **TTP229 SCL** | `GPIO 18` | Serial Clock (Output from ESP32) |
| **TTP229 SDO** | `GPIO 19` | Serial Data Out (Input, Active-LOW) |
| **PN532 SDA** | `GPIO 21` | I2C Data (400kHz) |
| **PN532 SCL** | `GPIO 22` | I2C Clock |
| **VCC** | `3.3V / 5V` | 5V for Buzzer, 3.3V for PN532 and TTP229 |
| **GND** | `GND` | Common Ground |

> ⚠️ **Important TTP229 Note**: Bridge pads **3 and 7** on the TTP229 P1 jumper pad with solder to enable 16-key active-low serial output mode.

---

## 🛠️ Arduino IDE Setup

1. **Board Manager**: Install `esp32` by Espressif Systems (Tools -> Board -> ESP32 Dev Module).
2. **Libraries Needed**:
   - `Adafruit PN532` by Adafruit (Install via Library Manager)
   - `Wire` (Built-in)
   - `WiFi` (Built-in)
3. **Upload Settings**:
   - Baud Rate: `115200`
   - Flash Frequency: `80MHz`
   - Upload Speed: `921600`

---

## 📡 Network Setup with Raspberry Pi 5

In `esp32_lectern_pod.ino`, update lines 32–35 to match your network:
```cpp
const char* WIFI_SSID     = "Veronica_AP";       // Pi 5 Hotspot or Classroom Wi-Fi
const char* WIFI_PASSWORD = "veronica_access";   // Wi-Fi Password
const char* PI5_HOST      = "192.168.4.1";       // Pi 5 IP address
const uint16_t PI5_PORT   = 8765;                // Matches POD_SERVER_PORT in config.py
```

Once powered, the ESP32 automatically links with the Raspberry Pi 5. All key presses and NFC card scans are streamed instantly over TCP with `<10ms` latency.

