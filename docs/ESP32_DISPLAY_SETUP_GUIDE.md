# Project Veronica — ESP32 Lectern Pod Complete Setup Guide

**Hardware:** ESP32-WROOM-32D (38-Pin) + Robocraze TIFDP0018 (3.5" Touchscreen ILI9486 + XPT2046)  
**Firmware:** `esp32_firmware/esp32_touch_pod.ino`  
**Last Updated:** November 21, 2026

---

## 1. What You Need

### Hardware Components

| Item | Qty | Notes |
| :--- | :--- | :--- |
| **ESP32-WROOM-32D** (38-pin board) | 1 | Standard 38-pin DevKit board matching your pinout diagram |
| **Robocraze TIFDP0018 3.5" Display** | 1 | 480×320 SPI TFT with XPT2046 resistive touch |
| **Male-to-Female DuPont jumper wires** | 8 | Connects display 26-pin socket to ESP32 |
| **PN532 NFC Module V3** (I2C mode) | 1 | 4 wires soldered (`SCL`, `SDA`, `VCC`, `GND`) |
| **Active Buzzer Module** | 1 | 3-pin module (`I/O`, `VCC`, `GND`) |
| **USB Micro-B cable** | 1 | For flashing & powering the ESP32 |

---

## 2. Physical Wiring

### 2.1 Robocraze TIFDP0018 ➔ ESP32 Connections (8 Wires)

Connect 8 DuPont wires between the TIFDP0018 socket and your ESP32:

```
 TIFDP0018 (26-Pin Socket)                       ESP32 (38-Pin WROOM)
 ┌───────────────────────────────┐              ┌──────────────────────┐
 │ Pin 2  (5V)                   │ ──────────── │ Left Pin 19:  5V0/VIN│
 │ Pin 6  (GND)                  │ ──────────── │ Right Pin 1:  GND    │
 │ Pin 18 (LCD_RS / DC)          │ ──────────── │ Right Pin 15: GPIO 2 │
 │ Pin 19 (MOSI / LCD_SI)        │ ──────────── │ Right Pin 2:  GPIO 23│
 │ Pin 21 (MISO / TP_SO)         │ ──────────── │ Right Pin 8:  GPIO 19│
 │ Pin 23 (SCK / LCD_SCK)        │ ──────────── │ Right Pin 9:  GPIO 18│
 │ Pin 24 (LCD_CS / CE0)         │ ──────────── │ Right Pin 16: GPIO 15│
 │ Pin 26 (TP_CS / CE1)          │ ──────────── │ Right Pin 10: GPIO 5 │
 └───────────────────────────────┘              └──────────────────────┘
```

| TIFDP0018 Socket Pin | Signal Name | ESP32 Pin Location | Function |
| :---: | :--- | :--- | :--- |
| **Pin 2** (or 4) | `5V` | **Left Rail Pin 19 (`5V0 / VIN`)** | 5V Power for Backlight & Logic Regulator |
| **Pin 6** | `GND` | **Right Rail Pin 1 (`GND`)** | Common Ground |
| **Pin 18** | `LCD_RS / DC` | **Right Rail Pin 15 (`GPIO 2`)** | Display Data / Command selector |
| **Pin 19** | `MOSI / LCD_SI`| **Right Rail Pin 2 (`GPIO 23`)** | SPI Data Out (Shared) |
| **Pin 21** | `MISO / TP_SO` | **Right Rail Pin 8 (`GPIO 19`)** | Touch Coordinate Feedback (XPT2046) |
| **Pin 23** | `SCK / LCD_SCK`| **Right Rail Pin 9 (`GPIO 18`)** | High-speed SPI Clock (Shared) |
| **Pin 24** | `LCD_CS / CE0` | **Right Rail Pin 16 (`GPIO 15`)** | Display Chip Select (active LOW) |
| **Pin 26** | `TP_CS / CE1`  | **Right Rail Pin 10 (`GPIO 5`)** | Touch Chip Select (active LOW) |

> **Note on Pin 22:** The TIFDP0018 has an onboard power-on auto-reset circuit, so hardware reset via Pin 22 is not required (`TFT_RST = -1`). Leave Pin 22 unconnected.

> **Note:** Pins 1, 3, 4, 5, 7–17, 20, 25 on the blue board are NC (Not Connected) or additional power/GND duplicates. Leave them unconnected.

---

### NFC Module (PN532 V3 I2C) → ESP32

Your red PN532 board has the 4 soldered wires at the top (`SCL`, `SDA`, `VCC`, `GND`):

| PN532 Wire | Connect to ESP32 Pin | Notes |
| :--- | :--- | :--- |
| **`SCL`** | **`GPIO 22`** | I2C Clock Line |
| **`SDA`** | **`GPIO 21`** | I2C Data Line |
| **`VCC`** | **`3.3V`** (or `VIN`) | Standard 3.3V / 5V input |
| **`GND`** | **`GND`** | System common ground |

> **DIP Switch Settings on PN532 Board**: Ensure the toggle switches on the red board are set for **I2C mode** (`0: 1`, `1: 0` as printed in the silkscreen table).

---

### Active Buzzer Module → ESP32

Connect the small blue buzzer module right next to the NFC reader:

| Buzzer Module Pin | Connect to ESP32 Pin |
| :--- | :--- |
| **`I/O`** | **`GPIO 25`** |
| **`VCC`** | **`3.3V`** |
| **`GND`** | **`GND`** |

---

## 3. Arduino IDE Setup

### Step 1: Install Arduino IDE 2.x
Download from [arduino.cc/en/software](https://arduino.cc/en/software) if not already installed.

### Step 2: Add ESP32 Board Package
1. Open Arduino IDE → `File` → `Preferences`
2. In the **Additional boards manager URLs** box, add:
   ```
   https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
   ```
3. Click **OK**
4. Go to `Tools` → `Board` → `Boards Manager`
5. Search for `esp32` by Espressif Systems
6. Install version **2.0.14** or later (avoid 3.x for now — library compatibility)

### Step 3: Select the Right Board
Navigate to: `Tools` → `Board` → `ESP32 Arduino` → **ESP32 Dev Module**

Then set these options in the `Tools` menu:

| Setting | Value |
| :--- | :--- |
| **Board** | `ESP32 Dev Module` |
| **Upload Speed** | `921600` |
| **CPU Frequency** | `240 MHz (WiFi/BT)` |
| **Flash Frequency** | `80 MHz` |
| **Flash Mode** | `QIO` |
| **Flash Size** | `4MB (32Mb)` |
| **Partition Scheme** | `Default 4MB with spiffs` |
| **Core Debug Level** | `None` |
| **Port** | Your COM port (e.g. `COM5`) |

---

## 4. Configure the TFT_eSPI Library

This is the most critical step. The library must be told your exact pin wiring.

### Step 1: Locate the Library File
Find the `TFT_eSPI` folder inside your Arduino libraries directory:
- **Windows:** `C:\Users\<YourName>\Documents\Arduino\libraries\TFT_eSPI\`

### Step 2: Edit `User_Setup_Select.h`
Open `TFT_eSPI/User_Setup_Select.h` in any text editor.

Find the line that says:
```cpp
#include <User_Setup.h>
```
Make sure only this line is uncommented (all other `#include` lines must be commented out with `//`).

### Step 3: Edit `User_Setup.h`
Open `TFT_eSPI/User_Setup.h` and **replace the entire contents** with the following:

```cpp
// ================================================================
// PROJECT VERONICA — TFT_eSPI Configuration
// Target: ESP32-WROOM-32D + 3.5" RPi Display (ILI9486 + XPT2046)
// ================================================================

// --- Display Driver ---
#define RPI_DISPLAY_TYPE     // REQUIRED for the blue RPi display board
#define ILI9486_DRIVER       // ILI9486 is the controller on this 480x320 board

// --- Resolution ---
#define TFT_WIDTH   320      // Physical width before rotation
#define TFT_HEIGHT  480      // Physical height before rotation

// --- SPI Bus Pins ---
#define TFT_MISO    19
#define TFT_MOSI    23
#define TFT_SCLK    18

// --- Display Control Pins ---
#define TFT_CS      15       // LCD Chip Select  → Blue Board Pin 24
#define TFT_DC       2       // Data / Command   → Blue Board Pin 18
#define TFT_RST      4       // Hardware Reset   → Blue Board Pin 22

// --- Touch IC ---
#define TOUCH_CS     5       // XPT2046 CS       → Blue Board Pin 26

// --- Fonts to Load ---
#define LOAD_GLCD
#define LOAD_FONT2
#define LOAD_FONT4
#define LOAD_FONT6
#define LOAD_FONT7
#define LOAD_FONT8
#define LOAD_GFXFF
#define SMOOTH_FONT

// --- SPI Frequencies ---
#define SPI_FREQUENCY       27000000   // 27 MHz for the display
#define SPI_READ_FREQUENCY  20000000
#define SPI_TOUCH_FREQUENCY  2500000   // 2.5 MHz for XPT2046 touch reads
```

> **Why `RPI_DISPLAY_TYPE`?**  
> The blue board uses an extra shift register between the SPI bus and the ILI9486's parallel interface. This define tells `TFT_eSPI` to send data 16-bits-at-a-time through that shift register — without it, you get a scrambled or white screen.

---

## 5. Install Required Libraries

In Arduino IDE: `Tools` → `Manage Libraries`, then search and install:

| Library | Author | Version | Purpose |
| :--- | :--- | :--- | :--- |
| **TFT_eSPI** | Bodmer | ≥ 2.5.43 | Hardware-accelerated display driver |
| **Adafruit PN532** | Adafruit | ≥ 1.3.4 | NFC/RFID Teacher Badge Reader |
| **Adafruit BusIO** | Adafruit | ≥ 1.14.0 | Required by PN532 library |
| **ArduinoJson** | Benoit Blanchon | ≥ 7.x | TCP JSON message parsing |

> The `WiFi`, `Wire`, and `SPI` libraries are already included with the ESP32 board package — do not install them separately.

---

## 6. Configure Your Network Settings

Open `esp32_firmware/esp32_touch_pod.ino` and find lines 38–41:

```cpp
const char* WIFI_SSID     = "Veronica_AP";       // ← Your Pi 5 hotspot name
const char* WIFI_PASSWORD = "veronica_access";   // ← Your Pi 5 hotspot password
const char* PI5_HOST      = "192.168.4.1";       // ← Raspberry Pi 5 IP address
const uint16_t PI5_PORT   = 8765;                // ← Do not change this
```

Change `Veronica_AP` and `veronica_access` to match the hotspot configured on your Raspberry Pi 5. The IP `192.168.4.1` is the standard default for the Pi 5's `hostapd` access point — change only if you configured a different IP.

---

## 7. Touch Calibration

The XPT2046 touch IC needs to be calibrated for your specific screen to map raw ADC values to screen pixel coordinates accurately.

### Step 1: Run the Calibration Sketch
In Arduino IDE: `File` → `Examples` → `TFT_eSPI` → `Generic` → **`Touch_calibrate`**

Flash it to your ESP32. The screen will show cross-hair targets at each corner.

### Step 2: Touch Each Corner
Touch the **exact centre** of each `+` marker as prompted (top-left, top-right, bottom-left, bottom-right, then centre).

### Step 3: Copy the Output
Open `Tools` → `Serial Monitor` (115200 baud). You will see output like:
```cpp
uint16_t calData[5] = { 339, 3446, 341, 3515, 2 };
tft.setTouch(calData);
```

### Step 4: Paste Into the Firmware
Open `esp32_touch_pod.ino` and find the `setup()` function. After the line `tft.begin();`, add or replace the calibration line with your output:
```cpp
tft.begin();
uint16_t calData[5] = { 339, 3446, 341, 3515, 2 };  // ← Paste YOUR values here
tft.setTouch(calData);
```

---

## 8. Flash the Firmware

1. Open `esp32_firmware/esp32_touch_pod.ino` in Arduino IDE
2. Make sure both `esp32_touch_pod.ino` **and** `Display_Config.h` are in the same folder
3. Connect the ESP32 via USB
4. Click the **Upload** button (right-arrow icon, or `Ctrl+U`)

If upload gets stuck at `Connecting......____`:
- Hold down the **BOOT** button on the ESP32 while the upload begins
- Release it after you see `Uploading...` in the status bar

After flashing, the display should immediately light up and show the **Slide 1** dashboard with 4 large touch buttons.

---

## 9. Connect the Raspberry Pi 5 Hub

The ESP32 connects wirelessly over TCP to the Pi 5 running `python3 main.py`.

### On the Raspberry Pi 5
Make sure the Pi 5 is broadcasting a Wi-Fi hotspot with the SSID you configured in Step 6. The main application should already be running:
```bash
cd ~/Project\ Veronica
python3 main.py
```

The ESP32 will automatically connect on boot and register as a pod at port `8765`. You will see in the Pi 5 console:
```
🔌 [POD]: ESP32 Pod connected from 192.168.4.15
```

### What the ESP32 Sends (TCP JSON)
Every touch fires a compact JSON command over Wi-Fi to the Pi 5:
```json
{ "event": "cmd", "action": "photo",    "subject": "PHYSICS" }
{ "event": "cmd", "action": "video",    "subject": "PHYSICS" }
{ "event": "cmd", "action": "subj_chemistry" }
{ "event": "cmd", "action": "stop" }
```

### What the ESP32 Receives
The Pi 5 sends heartbeat and state acknowledgements back:
```json
{ "event": "ack", "subject": "PHYSICS", "session_pages": 7, "recording": true }
```

---

## 10. Troubleshooting

| Symptom | Likely Cause | Fix |
| :--- | :--- | :--- |
| **White screen after boot** | Wrong display driver or missing `RPI_DISPLAY_TYPE` | Confirm `#define RPI_DISPLAY_TYPE` and `#define ILI9486_DRIVER` are both set in `User_Setup.h` |
| **Scrambled / inverted colours** | Using `ILI9488_DRIVER` instead of `ILI9486_DRIVER` | Switch the driver define and re-flash |
| **Touch is off-target or upside-down** | No calibration or wrong rotation | Re-run `Touch_calibrate` and paste new `calData` values |
| **Touch completely unresponsive** | MISO (`GPIO 19`) not connected or bad wire | Check the wire on Blue Board Pin 21 → ESP32 GPIO 19 |
| **Screen is on but black** | Backlight not receiving 5V | Connect Blue Board Pin 2 or Pin 4 to ESP32 VIN (5V rail, not 3.3V) |
| **NFC badge not detected** | PN532 not in I2C mode | Flip the PN532 DIP switch: `SEL0=ON, SEL1=OFF` |
| **No Wi-Fi connection** | Wrong SSID/Password in firmware | Update lines 38–41 in `esp32_touch_pod.ino` and re-flash |
| **Upload fails: won't connect** | ESP32 not in download mode | Hold the `BOOT` button during upload |
| **Buzzer makes no sound** | BC547 transistor missing / wrong polarity | Verify transistor orientation: BASE from GPIO 25 through 10kΩ |

---

## Quick Reference — All ESP32 GPIO Assignments

```
GPIO  2  → Display DC   (Data/Command)
GPIO  4  → Display RST  (Reset)
GPIO  5  → Touch CS     (XPT2046 Chip Select)
GPIO 15  → Display CS   (LCD Chip Select)
GPIO 18  → SPI SCK      (Clock — shared by display & touch)
GPIO 19  → SPI MISO     (Touch read-back from XPT2046)
GPIO 21  → I2C SDA      (PN532 NFC module)
GPIO 22  → I2C SCL      (PN532 NFC module)
GPIO 23  → SPI MOSI     (Data to display)
GPIO 25  → Buzzer       (Via BC547 transistor)
GPIO 27  → Touch IRQ    (Optional interrupt, can be left unconnected)
GPIO 32  → Backlight PWM (Sleep mode dimming)
```

---

*Guide written for Project Veronica v1.2 — November 12, 2026*

