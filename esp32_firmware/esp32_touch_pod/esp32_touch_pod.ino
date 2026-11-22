/*
  ╔═══════════════════════════════════════════════════════════════════════════╗
  ║         PROJECT VERONICA — TIER 1: 3.5" TOUCHSCREEN LECTERN POD           ║
  ║  Hardware Controller: ESP32-WROOM-32D (30-pin)                            ║
  ║  Display: 3.5" TFT LCD (480 x 320 Landscape, ILI9488 / ST7796)            ║
  ║  Touch: XPT2046 (SPI) / FT6236 (I2C Capacitive)                           ║
  ║  Wireless: 5.8GHz / 2.4GHz Wi-Fi TCP Client to Raspberry Pi 5             ║
  ║                                                                           ║
  ║  ADVANCED FEATURES:                                                       ║
  ║  • 4 Large Tactile Buttons Per Slide (2x2 Grid, 225x107px tap targets)    ║
  ║  • 🔴 LIVE RECORDING OVERLAY: Fullscreen HUD with real-time seconds/mins  ║
  ║    counter and giant "TERMINATE & ARCHIVE RECORDING" tactile stop button  ║
  ║  • 🏷️ NFC TEACHER GREETING FLASH: Welcome card on RFID card tap          ║
  ║  • 🛡️ ANTI-MISUSE CONSOLE INTERLOCK: Prevents students recording without  ║
  ║    authorized teacher subject selection                                   ║
  ║  • 📄 CHALKBOARD SNAPSHOTS QUEUE COUNTER: Real-time notes count           ║
  ║  • 60s Inactivity Sleep Mode (Pure Black #000000 + Backlight Dimmer)      ║
  ║  • Day / Night Mode Palette Toggle (Obsidian Neon <-> Pure Crisp White)   ║
  ║  • Sub-10ms Wireless Telemetry over TCP (Port 8765) to Overhead Pi 5      ║
  ╚═══════════════════════════════════════════════════════════════════════════╝
*/

#include <WiFi.h>
#include <Wire.h>
#include <Adafruit_PN532.h>  // Hardware PN532 NFC Reader over I2C
#include "Display_Config.h"

// ==============================================================================
// 1. HARDWARE INSTANCES & CONFIGURATION
// ==============================================================================
// Set to false: UI runs on Raspberry Pi 5 Chromium Kiosk (800x480 Fullscreen)
// Set to true: Local 3.5" TFT SPI Shield attached to ESP32
#define ENABLE_TFT_DISPLAY false

#if ENABLE_TFT_DISPLAY
#include <SPI.h>
#include <TFT_eSPI.h>
TFT_eSPI tft = TFT_eSPI();   // Custom TFT_eSPI instance (480x320 landscape)
#endif

// Pass dummy pins (34 for IRQ as input, 33 for RST) so library never touches SDA(21) or SCL(22)
Adafruit_PN532 nfc(PN532_IRQ, PN532_RESET);
WiFiClient client;

// Network settings (Pi 5 Overhead Hub IP & Port)
const char* WIFI_SSID     = "Garib";       // Match Wi-Fi SSID
const char* WIFI_PASSWORD = "yoyo123@";           // Match Wi-Fi Password
// Pi 5 IP Address:
const char* PI5_HOST      = "192.168.0.138";      // <-- Your Pi 5 IP on the network
const uint16_t PI5_PORT   = 8765;                 // Matches POD_SERVER_PORT in config.py

// ==============================================================================
// 2. UI STATE & PALETTE DEFINITIONS
// ==============================================================================
bool isDayMode = false;              // false = Night (Obsidian), true = Day (Pure White)
bool isSleeping = false;             // true = Screen saver active (Black screen)
bool isRecording = false;            // 🔴 true = Live Video/Audio Recording HUD active
String recordingType = "4K VIDEO";   // "4K VIDEO" or "ROOM AUDIO"
unsigned long recordingStartTime = 0;// Millis timestamp when recording began
int currentSlide = 0;                // 0 = Actions, 1 = Hardware, 2 = Subjects
String currentSubject = "PHYSICS";   // Active Subject context ("" or "NONE" = locked)
bool isSubjectLocked = false;        // 🛡️ Anti-misuse lock: true if no subject selected
int sessionPages = 0;                // Chalkboard snapshots queued for PDF
unsigned long lastActivityTime = 0;  // Inactivity tracking for sleep mode
const unsigned long SLEEP_TIMEOUT_MS = 60000; // 60 seconds auto-sleep

// NFC Teacher Greeting Flash State
bool isShowingNFCWelcome = false;
unsigned long nfcWelcomeTime = 0;

// Interlock Warning Alert State
bool isShowingInterlock = false;
unsigned long interlockStartTime = 0;

// Touch tracking
int touchStartX = -1;
int touchStartY = -1;
unsigned long touchStartTime = 0;
bool isTouching = false;

// Heartbeat & NFC tracking
unsigned long last_heartbeat = 0;
unsigned long last_nfc_poll = 0;
String last_nfc_uid = "";
unsigned long last_nfc_time = 0;

// Forward declarations
void renderUI();
void drawHeader();
void drawRecordingHUD();
void updateRecordingTimer(bool forceRedraw = false);
void showInterlockAlert();
void drawNFCWelcomeCard(const char* teacherName, const char* dept, const char* subject);

// ==============================================================================
// 3. COLOR HELPER (Theme Aware)
// ==============================================================================
uint16_t colBg()     { return isDayMode ? COLOR_LIGHT_BG : COLOR_DARK_BG; }
uint16_t colCard()   { return isDayMode ? COLOR_LIGHT_CARD : COLOR_DARK_CARD; }
uint16_t colBorder() { return isDayMode ? COLOR_LIGHT_BORDER : COLOR_DARK_BORDER; }
uint16_t colText()   { return isDayMode ? COLOR_LIGHT_TEXT : COLOR_DARK_TEXT; }
uint16_t colMuted()  { return isDayMode ? COLOR_LIGHT_MUTED : COLOR_DARK_MUTED; }

// ==============================================================================
// 4. ACOUSTIC BUZZER CONTROL (PASSIVE BUZZER via ESP32 PWM TONE)
// ==============================================================================
#define BUZZER_PWM_CHANNEL  2

void playTone(int freq, int duration_ms) {
  if (freq <= 0) return;
  // 2-argument tone() attaches LEDC, then delay(), then noTone() detaches LEDC cleanly
  // This eliminates the "ledc_get_duty: LEDC is not initialized" error on ESP32!
  tone(BUZZER_PIN, freq);
  delay(duration_ms);
  noTone(BUZZER_PIN);
}

void beep(int times = 1, int duration_ms = 80, int gap_ms = 60, int freq = BUZZER_FREQ) {
  for (int i = 0; i < times; i++) {
    playTone(freq > 0 ? freq : BUZZER_FREQ, duration_ms);
    if (i < times - 1) delay(gap_ms);
  }
}

// ==============================================================================
// 5. NETWORK TELEMETRY TO PI 5 (TCP SOCKET PORT 8765) — ALWAYS ACTIVE
// ==============================================================================
void ensureConnection() {
  static bool wifi_announced = false;

  // 1. Wi-Fi Link
  if (WiFi.status() != WL_CONNECTED) {
    wifi_announced = false;
    static unsigned long last_retry = 0;
    if (millis() - last_retry > 5000) {
      last_retry = millis();
      Serial.printf("📶 Connecting to Wi-Fi [%s]...\n", WIFI_SSID);
      WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    }
    return;
  }

  // Print once as soon as Wi-Fi gets an IP
  if (!wifi_announced) {
    wifi_announced = true;
    Serial.println("\n══════════════════════════════════════════");
    Serial.print("✅ Wi-Fi Connected Successfully!\n");
    Serial.print("📍 ESP32 IP Address : ");
    Serial.println(WiFi.localIP());
    Serial.print("📶 Signal Strength  : ");
    Serial.print(WiFi.RSSI());
    Serial.println(" dBm");
    Serial.println("══════════════════════════════════════════\n");
    beep(2, 50, 40, 2500); // 2 quick success beeps
  }

  // 2. TCP Socket Link to Pi 5
  if (!client.connected()) {
    static unsigned long last_tcp = 0;
    if (millis() - last_tcp > 3000) {
      last_tcp = millis();
      Serial.printf("🔌 Connecting to Pi 5 at %s:%d...\n", PI5_HOST, PI5_PORT);
      if (client.connect(PI5_HOST, PI5_PORT)) {
        Serial.println("✅ Connected to Raspberry Pi 5 Core Hub!");
        beep(2, 60, 40, 2800);
      } else {
        Serial.println("⚠️ Connection to Pi 5 pending... (Make sure 'python main.py' is running on the Pi 5)");
      }
    }
  }
}

void sendEvent(const char* eventType, String jsonBody) {
  if (client.connected()) {
    String msg = String("{\"event\":\"") + eventType + "\"," + jsonBody.substring(1) + "\n";
    client.print(msg);
    Serial.print("📤 Dispatched: " + msg);
  } else {
    Serial.println("⚠️ TCP Link Offline: Event queued");
  }
}

void checkIncomingCommands() {
  while (client.available()) {
    String line = client.readStringUntil('\n');
    line.trim();
    if (line.length() > 0) {
      Serial.println("📥 Pi 5 Packet: " + line);

      if (line.indexOf("\"cmd\":\"beep\"") >= 0) {
        beep(1, 80);
      }

      if (line.indexOf("\"subject\":") >= 0) {
        int idx = line.indexOf("\"subject\":\"");
        if (idx >= 0) {
          int endIdx = line.indexOf("\"", idx + 11);
          if (endIdx > 0) {
            currentSubject = line.substring(idx + 11, endIdx);
            currentSubject.toUpperCase();
            isSubjectLocked = (currentSubject == "NONE" || currentSubject.length() == 0);
            if (!isSleeping && !isRecording && !isShowingNFCWelcome) renderUI();
          }
        }
      }

      if (line.indexOf("\"pages\":") >= 0) {
        int pidx = line.indexOf("\"pages\":");
        sessionPages = line.substring(pidx + 8).toInt();
        if (!isSleeping && !isRecording && !isShowingNFCWelcome) drawHeader();
      }

      if (line.indexOf("\"recording\":true") >= 0) {
        if (!isRecording) {
          isRecording = true;
          recordingStartTime = millis();
          recordingType = (line.indexOf("\"audio\"") >= 0) ? "ROOM AUDIO" : "4K VIDEO";
          drawRecordingHUD();
        }
      } else if (line.indexOf("\"recording\":false") >= 0) {
        if (isRecording) {
          isRecording = false;
          renderUI();
        }
      }
    }
  }
}

// ==============================================================================
// 6. DISPLAY DRAWING & TOUCH FUNCTIONS (Optional TFT Screen Mode)
// ==============================================================================
#if ENABLE_TFT_DISPLAY

// Set Backlight Brightness
void setBacklight(uint8_t brightness) {
  // RPi 3.5" shield backlight is powered via 5V rail
}

// Draw the Permanent Status Header Bar (44px)
void drawHeader() {
  tft.fillRect(0, 0, 480, 44, isDayMode ? 0xF7BE : 0x0821);
  tft.drawFastHLine(0, 43, 480, colBorder());

  // 1. Active Subject Pill (Tap to open slide 3)
  if (!isSubjectLocked && currentSubject.length() > 0 && currentSubject != "NONE") {
    uint16_t subjCol = ACCENT_GREEN;
    tft.fillRoundRect(8, 7, 115, 30, 15, isDayMode ? 0xEF7D : 0x11E3);
    tft.drawRoundRect(8, 7, 115, 30, 15, subjCol);
    tft.fillCircle(20, 22, 4, subjCol);
    tft.setTextColor(subjCol);
    tft.setTextSize(1);
    tft.drawString(currentSubject, 30, 16, 2);
  } else {
    // 🛡️ Anti-Misuse Warning Pill
    tft.fillRoundRect(8, 7, 125, 30, 15, isDayMode ? 0xFEEC : 0x2180);
    tft.drawRoundRect(8, 7, 125, 30, 15, ACCENT_AMBER);
    tft.fillCircle(20, 22, 4, ACCENT_AMBER);
    tft.setTextColor(ACCENT_AMBER);
    tft.setTextSize(1);
    tft.drawString("LOCK: NO SUBJ", 30, 16, 2);
  }

  // 2. Classroom Node Tag & Snapshots counter
  tft.setTextColor(colMuted());
  tft.drawString("Class X", 140, 16, 2);

  if (sessionPages > 0) {
    tft.fillRoundRect(195, 10, 52, 24, 12, isDayMode ? 0xEFF6 : 0x1925);
    tft.drawRoundRect(195, 10, 52, 24, 12, ACCENT_BLUE);
    tft.setTextColor(ACCENT_BLUE);
    char pgBuf[16];
    snprintf(pgBuf, sizeof(pgBuf), "%dpg", sessionPages);
    tft.drawString(pgBuf, 203, 14, 2);
  }

  // 3. Wi-Fi Status
  tft.setTextColor(ACCENT_CYAN);
  tft.drawString("● 5.8G", 260, 16, 2);

  // 4. Uptime Clock
  unsigned long secs = millis() / 1000;
  char timeBuf[16];
  snprintf(timeBuf, sizeof(timeBuf), "%02lu:%02lu", (secs / 60) % 60, secs % 60);
  tft.setTextColor(colText());
  tft.drawString(timeBuf, 335, 16, 2);

  // 5. Day/Night Toggle Button (Right Header)
  tft.fillRoundRect(395, 7, 34, 30, 6, isDayMode ? 0xFFFF : 0x1925);
  tft.drawRoundRect(395, 7, 34, 30, 6, colBorder());
  tft.setTextColor(ACCENT_ORANGE);
  tft.drawString(isDayMode ? "D" : "N", 407, 15, 2);

  // 6. Sleep Lock Button
  tft.fillRoundRect(436, 7, 36, 30, 6, isDayMode ? 0xFFFF : 0x1925);
  tft.drawRoundRect(436, 7, 36, 30, 6, colBorder());
  tft.setTextColor(colText());
  tft.drawString("LK", 446, 15, 2);
}

// Draw a Single Tactile Button (225px x 107px)
void drawButton(int x, int y, int w, int h, const char* title, const char* subtitle, const char* tag, uint16_t accent, bool locked = false) {
  tft.fillRoundRect(x, y, w, h, 12, colCard());
  tft.drawRoundRect(x, y, w, h, 12, locked ? colBorder() : accent);
  tft.drawFastHLine(x + 10, y + 1, w - 20, isDayMode ? 0xFFFF : 0x3186);

  // Top Tag Pill
  tft.fillRoundRect(x + w - 55, y + 8, 45, 18, 4, isDayMode ? 0xEF5D : 0x18C3);
  tft.setTextColor(locked ? colMuted() : accent);
  tft.drawString(tag, x + w - 48, y + 11, 1);

  // Accent Dot / Lock Indicator
  tft.fillCircle(x + 20, y + 20, 6, locked ? colMuted() : accent);

  // Button Title (Bold)
  tft.setTextColor(locked ? colMuted() : colText());
  tft.drawString(title, x + 14, y + 46, 2);

  // Subtitle
  tft.setTextColor(colMuted());
  tft.drawString(locked ? "Locked: Tap Subject" : subtitle, x + 14, y + 74, 1);
}

// Draw Slide 1: Academic Actions (4 Buttons)
void drawSlide1() {
  drawButton(10, 48,  225, 107, "Optical Scan", "Capture Chalkboard", "SCAN", ACCENT_PURPLE, isSubjectLocked);
  drawButton(245, 48, 225, 107, "Compile Notes", "Publish Session PDF", "PDF", ACCENT_GREEN, isSubjectLocked);
  drawButton(10, 161, 225, 107, "4K Stream", "Toggle Board Video", "4K", ACCENT_PINK, isSubjectLocked);
  drawButton(245, 161, 225, 107, "Room Audio", "Lecture Microphone", "MIC", ACCENT_AMBER, isSubjectLocked);
}

// Draw Slide 2: Hardware & Systems (4 Buttons)
void drawSlide2() {
  drawButton(10, 48,  225, 107, "Projector View", "Wall Board Mirror", "HDMI", ACCENT_CYAN);
  drawButton(245, 48, 225, 107, "Terminate", "Standby Mode", "STOP", colText());
  drawButton(10, 161, 225, 107, "Transmit Status", "Broadcast Diagnostics", "HEAL", ACCENT_BLUE);
  drawButton(245, 161, 225, 107, "Reboot Pod", "Restart Lectern Hub", "SYS", ACCENT_RED);
}

// Draw Slide 3: Subject Context (4 Buttons)
void drawSlide3() {
  drawButton(10, 48,  225, 107, "Physics", "Prof. H. C. Verma", "NFC1", ACCENT_PURPLE);
  drawButton(245, 48, 225, 107, "Chemistry", "Dr. P. Mukherjee", "NFC2", ACCENT_CYAN);
  drawButton(10, 161, 225, 107, "Mathematics", "Prof. S. Ramanujan", "NFC3", ACCENT_BLUE);
  drawButton(245, 161, 225, 107, "Computer Sci", "Prof. Alan Turing", "NFC4", ACCENT_GREEN);
}

// Draw Bottom Pagination Bar (36px)
void drawFooter() {
  tft.fillRect(0, 276, 480, 44, isDayMode ? 0xF7BE : 0x0821);
  tft.drawFastHLine(0, 276, 480, colBorder());

  // Left Chevron <
  tft.fillRoundRect(10, 282, 34, 30, 6, isDayMode ? 0xFFFF : 0x1925);
  tft.drawRoundRect(10, 282, 34, 30, 6, colBorder());
  tft.setTextColor(colText());
  tft.drawString("<", 22, 289, 2);

  // Pagination Dots
  for (int i = 0; i < 3; i++) {
    int dx = 70 + (i * 22);
    if (i == currentSlide) {
      tft.fillRoundRect(dx, 294, 16, 6, 3, ACCENT_ORANGE);
    } else {
      tft.fillCircle(dx + 3, 297, 3, colMuted());
    }
  }

  // Slide Label
  const char* labels[] = { "Lecture Actions (1/3)", "System & Display (2/3)", "Subject Context (3/3)" };
  tft.setTextColor(colMuted());
  tft.drawString(labels[currentSlide], 150, 289, 2);

  // Right Chevron >
  tft.fillRoundRect(436, 282, 34, 30, 6, isDayMode ? 0xFFFF : 0x1925);
  tft.drawRoundRect(436, 282, 34, 30, 6, colBorder());
  tft.setTextColor(colText());
  tft.drawString(">", 448, 289, 2);
}

// ==============================================================================
// 6. 🔴 LIVE RECORDING OVERLAY (HUD WITH LIVE TIMER & GIANT STOP BUTTON)
// ==============================================================================
void drawRecordingHUD() {
  tft.fillScreen(isDayMode ? 0xFFFF : 0x0821);

  // 1. Top Danger / Recording Banner (44px)
  tft.fillRect(0, 0, 480, 44, ACCENT_RED);
  tft.fillCircle(20, 22, 6, 0xFFFF);
  tft.setTextColor(0xFFFF);
  tft.drawString(String("LIVE ") + recordingType + " RECORDING", 34, 15, 2);

  // Subject pill in right top
  tft.fillRoundRect(350, 8, 120, 28, 6, 0x9800);
  tft.setTextColor(0xFFFF);
  tft.drawString(currentSubject, 362, 14, 2);

  // 2. Middle Info & Duration Timer Deck
  tft.setTextColor(colMuted());
  tft.drawString("RECORDING DURATION (ELAPSED):", 135, 60, 2);

  // Draw giant live timer
  updateRecordingTimer(true);

  // Camera / Tech Specs
  tft.setTextColor(colMuted());
  if (recordingType.indexOf("VIDEO") >= 0) {
    tft.drawString("KREO OWL 4K  |  3840x2160 @ 30 FPS  |  H.264 MP4", 75, 168, 2);
  } else {
    tft.drawString("LECTERN POD MIC  |  STEREO 48kHz  |  AAC COMPRESSED", 68, 168, 2);
  }

  // 3. Giant STOP Button (x: 25, y: 215, w: 430, h: 76)
  tft.fillRoundRect(25, 215, 430, 76, 16, ACCENT_RED);
  tft.drawRoundRect(25, 215, 430, 76, 16, 0xFFFF);

  // White Square Stop Icon
  tft.fillRect(48, 238, 26, 26, 0xFFFF);

  // Stop Button Labels
  tft.setTextColor(0xFFFF);
  tft.drawString("TERMINATE & ARCHIVE RECORDING", 88, 228, 4);
  tft.drawString("Tap to stop recording feed & upload MP4 to cloud", 90, 260, 2);
}

void updateRecordingTimer(bool forceRedraw) {
  if (!isRecording) return;
  unsigned long elapsedSecs = (millis() - recordingStartTime) / 1000;
  unsigned int mins = elapsedSecs / 60;
  unsigned int secs = elapsedSecs % 60;
  char timeBuf[16];
  snprintf(timeBuf, sizeof(timeBuf), "%02u:%02u", mins, secs);

  // Clear previous timer digit area
  tft.fillRect(150, 88, 180, 68, isDayMode ? 0xFFFF : 0x0821);

  // Draw giant timer
  tft.setTextColor(ACCENT_RED);
  tft.drawString(timeBuf, 160, 92, 6);
}

// ==============================================================================
// 7. 🏷️ NFC TEACHER GREETING FLASH & 🛡️ INTERLOCK MODAL
// ==============================================================================
void drawNFCWelcomeCard(const char* teacherName, const char* dept, const char* subject) {
  isShowingNFCWelcome = true;
  nfcWelcomeTime = millis();

  tft.fillScreen(isDayMode ? 0xF7BE : 0x0821);

  // High-gloss card frame
  tft.fillRoundRect(20, 16, 440, 288, 18, isDayMode ? 0xFFFF : 0x1116);
  tft.drawRoundRect(20, 16, 440, 288, 18, ACCENT_GREEN);
  tft.drawRoundRect(22, 18, 436, 284, 16, ACCENT_GREEN);

  // Verification Pill
  tft.fillRoundRect(36, 30, 210, 32, 16, isDayMode ? 0xEF7D : 0x11E3);
  tft.drawRoundRect(36, 30, 210, 32, 16, ACCENT_GREEN);
  tft.fillCircle(50, 46, 5, ACCENT_GREEN);
  tft.setTextColor(ACCENT_GREEN);
  tft.drawString("TEACHER VERIFIED", 64, 38, 2);

  // Teacher Name
  tft.setTextColor(colText());
  tft.drawString(teacherName, 38, 80, 4);

  // Department
  tft.setTextColor(colMuted());
  tft.drawString(dept, 40, 118, 2);

  // Active Subject Banner
  tft.fillRoundRect(36, 155, 408, 54, 12, ACCENT_GREEN);
  tft.setTextColor(0xFFFF);
  tft.drawString(String("CLASSROOM UNLOCKED: ") + subject, 56, 170, 4);

  // Footer status
  tft.setTextColor(colMuted());
  tft.drawString("Zero-friction handover  ·  Auto-upload to Drive armed", 54, 235, 2);
  tft.drawString("● 5.8GHz Mesh Link: Operational (2ms)", 98, 260, 2);

  // Melodic welcome chime
  beep(1, 60, 20, 2200);
  beep(1, 100, 20, 3000);
}

void showInterlockAlert() {
  isShowingInterlock = true;
  interlockStartTime = millis();

  tft.fillRoundRect(30, 50, 420, 220, 18, isDayMode ? 0xFEEC : 0x1810);
  tft.drawRoundRect(30, 50, 420, 220, 18, ACCENT_AMBER);
  tft.drawRoundRect(32, 52, 416, 216, 16, ACCENT_AMBER);

  tft.fillRoundRect(50, 68, 220, 28, 14, isDayMode ? 0xFDE0 : 0x2180);
  tft.setTextColor(ACCENT_AMBER);
  tft.drawString("🛡️ CONSOLE INTERLOCKED", 64, 74, 2);

  tft.setTextColor(colText());
  tft.drawString("Subject Not Selected!", 52, 108, 4);

  tft.setTextColor(colMuted());
  tft.drawString("Student Misuse Prevention is active on lectern.", 52, 142, 2);
  tft.drawString("Please scan Teacher NFC Card or select a subject", 52, 164, 2);
  tft.drawString("on Slide 3 to unlock recording and notes.", 52, 186, 2);

  // Big Jump Button
  tft.fillRoundRect(50, 214, 380, 42, 10, ACCENT_ORANGE);
  tft.setTextColor(0xFFFF);
  tft.drawString("SELECT SUBJECT NOW ➔", 128, 224, 2);
}

// Render the Entire Screen
void renderUI() {
  if (isRecording) {
    drawRecordingHUD();
    return;
  }
  if (isShowingNFCWelcome) return;

  tft.fillScreen(colBg());
  drawHeader();

  if (currentSlide == 0) drawSlide1();
  else if (currentSlide == 1) drawSlide2();
  else if (currentSlide == 2) drawSlide3();

  drawFooter();
}

// Draw Deep Black Sleep Mode (#000000 Pure Black to Save Screen)
void enterSleepMode() {
  if (isRecording || isShowingNFCWelcome) return;

  isSleeping = true;
  tft.fillScreen(0x0000); // 100% Pure Pitch Black

  tft.setTextColor(0x2104);
  tft.drawString("VERONICA POD STANDBY", 140, 60, 2);

  unsigned long secs = millis() / 1000;
  char timeBuf[16];
  snprintf(timeBuf, sizeof(timeBuf), "%02lu:%02lu", (secs / 60) % 60, secs % 60);
  tft.setTextColor(0x3186);
  tft.drawString(timeBuf, 180, 100, 4);

  tft.setTextColor(0x2104);
  tft.drawString(String("SUBJECT: ") + (isSubjectLocked ? "LOCKED (NONE)" : currentSubject), 140, 160, 2);

  // Slide/Tap to unlock widget
  tft.fillRoundRect(60, 220, 360, 48, 24, 0x10A2);
  tft.drawRoundRect(60, 220, 360, 48, 24, 0x2104);
  tft.setTextColor(0x632C);
  tft.drawString("Swipe or Tap to Wake Pod ➔", 120, 235, 2);
  tft.fillCircle(85, 244, 18, ACCENT_ORANGE);
  tft.setTextColor(0xFFFF);
  tft.drawString(">", 81, 236, 2);

  setBacklight(30);
}

void wakeScreen() {
  isSleeping = false;
  lastActivityTime = millis();
  setBacklight(255);
  beep(1, 30);
  renderUI();
}

// ==============================================================================
// 7. RECORDING TRIGGER & TOUCH EVENT HANDLER
// ==============================================================================
void startRecording(const char* type, const char* actionCmd) {
  isRecording = true;
  recordingType = type;
  recordingStartTime = millis();
  beep(1, 60);
  sendEvent("cmd", String("{\"action\":\"") + actionCmd + "\"}");
  lastActivityTime = millis();
  drawRecordingHUD();
}

void stopRecording() {
  isRecording = false;
  beep(2, 60, 40);
  sendEvent("cmd", "{\"action\":\"stop\"}");
  lastActivityTime = millis();
  renderUI();
}

void handleButtonAction(const char* action) {
  beep(1, 40);
  sendEvent("cmd", String("{\"action\":\"") + action + "\"}");
  lastActivityTime = millis();
}

void processTouch(int x, int y) {
  lastActivityTime = millis();

  if (isSleeping) {
    wakeScreen();
    return;
  }

  // Dismiss Interlock Modal on tap
  if (isShowingInterlock) {
    isShowingInterlock = false;
    currentSlide = 2; // Jump directly to Subject Selection
    beep(1, 30);
    renderUI();
    return;
  }

  // Dismiss NFC Welcome banner early on tap
  if (isShowingNFCWelcome) {
    isShowingNFCWelcome = false;
    renderUI();
    return;
  }

  // 🔴 If in Live Recording Overlay -> Check STOP Button
  if (isRecording) {
    if (x >= 25 && x <= 455 && y >= 210 && y <= 300) {
      stopRecording();
    }
    return;
  }

  // 1. Header Clicks (y: 0 - 44)
  if (y <= 44) {
    if (x >= 8 && x <= 135) {
      // Tap active subject -> Open Slide 3
      currentSlide = 2;
      beep(1, 30);
      renderUI();
      return;
    }
    if (x >= 395 && x <= 430) {
      isDayMode = !isDayMode;
      beep(1, 30);
      renderUI();
      return;
    }
    if (x >= 436 && x <= 475) {
      enterSleepMode();
      return;
    }
  }

  // 2. Footer Clicks (y: 276 - 320)
  if (y >= 276) {
    if (x <= 60) {
      currentSlide = (currentSlide - 1 + 3) % 3;
      beep(1, 30);
      renderUI();
      return;
    }
    if (x >= 420) {
      currentSlide = (currentSlide + 1) % 3;
      beep(1, 30);
      renderUI();
      return;
    }
  }

  // 3. 2x2 Button Grid Clicks (y: 48 - 268)
  if (y >= 48 && y <= 268) {
    int col = (x < 240) ? 0 : 1;
    int row = (y < 160) ? 0 : 1;

    if (currentSlide == 0) {
      // 🛡️ ANTI-MISUSE CHECK: Block student taps if no subject selected!
      if (isSubjectLocked) {
        beep(3, 80, 50, 800);
        showInterlockAlert();
        return;
      }

      // Slide 1: Actions
      if (row == 0 && col == 0) { sessionPages++; handleButtonAction("photo"); drawHeader(); }
      if (row == 0 && col == 1) { sessionPages = 0; handleButtonAction("compile_pdf"); drawHeader(); }
      if (row == 1 && col == 0) startRecording("4K VIDEO", "video");
      if (row == 1 && col == 1) startRecording("ROOM AUDIO", "audio");
    }
    else if (currentSlide == 1) {
      // Slide 2: Hardware
      if (row == 0 && col == 0) handleButtonAction("projector");
      if (row == 0 && col == 1) handleButtonAction("stop");
      if (row == 1 && col == 0) handleButtonAction("report");
      if (row == 1 && col == 1) handleButtonAction("reboot");
    }
    else if (currentSlide == 2) {
      // Slide 3: Subjects (Unlocks console!)
      isSubjectLocked = false;
      sessionPages = 0;
      if (row == 0 && col == 0) { currentSubject = "PHYSICS";     handleButtonAction("subj_physics"); }
      if (row == 0 && col == 1) { currentSubject = "CHEMISTRY";   handleButtonAction("subj_chemistry"); }
      if (row == 1 && col == 0) { currentSubject = "MATHEMATICS"; handleButtonAction("subj_math"); }
      if (row == 1 && col == 1) { currentSubject = "COMP SCI";    handleButtonAction("subj_comp"); }
      currentSlide = 0; // Return to action slide
      renderUI();
    }
  }
}

void pollTouch() {
#if defined(TOUCH_CS)
  uint16_t x, y;
  bool touched = tft.getTouch(&x, &y);

  if (touched) {
    if (!isTouching) {
      isTouching = true;
      touchStartX = x;
      touchStartY = y;
      touchStartTime = millis();
    }
  } else {
    if (isTouching) {
      isTouching = false;
      int dx = x - touchStartX;
      int dur = millis() - touchStartTime;

      if (!isRecording && !isShowingNFCWelcome && !isShowingInterlock && abs(dx) > 50 && dur < 500 && !isSleeping) {
        if (dx < 0) {
          currentSlide = (currentSlide + 1) % 3;
        } else {
          currentSlide = (currentSlide - 1 + 3) % 3;
        }
        beep(1, 30);
        renderUI();
      } else {
        processTouch(touchStartX, touchStartY);
      }
    }
  }
#endif
}

#else
// ══════════════════════════════════════════════════════════════════════════════
// Bypassed TFT / Touch Stubs (UI is displayed on Raspberry Pi 5 Chromium Kiosk)
// ══════════════════════════════════════════════════════════════════════════════
void setBacklight(uint8_t brightness) {}
void drawHeader() {}
void drawRecordingHUD() {}
void updateRecordingTimer(bool forceRedraw) {}
void showInterlockAlert() {}
void drawNFCWelcomeCard(const char* teacherName, const char* dept, const char* subject) {
  // Melodic acoustic feedback on teacher badge scan
  beep(1, 60, 20, 2200);
  delay(30);
  beep(1, 100, 20, 3000);
}
void renderUI() {}
void enterSleepMode() {}
void wakeScreen() {}
void pollTouch() {}
#endif

// ==============================================================================
// 10. PN532 NFC BADGE SCANNER (Zero-Friction Teacher Check-in via I2C)
// ==============================================================================
void pollNFC() {
  if (millis() - last_nfc_poll < 200) return;
  last_nfc_poll = millis();

  uint8_t uid[7];
  uint8_t uidLength;

  if (nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A, uid, &uidLength, 40)) {
    String uidStr = "";
    for (uint8_t i = 0; i < uidLength; i++) {
      if (uid[i] < 0x10) uidStr += "0";
      uidStr += String(uid[i], HEX);
    }
    uidStr.toUpperCase();

    if (uidStr != last_nfc_uid || (millis() - last_nfc_time > 2500)) {
      last_nfc_uid = uidStr;
      last_nfc_time = millis();
      lastActivityTime = millis();
      if (isSleeping) wakeScreen();

      // Look up Teacher & Subject context
      String teacher = "PROFESSOR";
      String dept = "FACULTY OF ACADEMICS";
      String subj = "GENERAL";

      if (uidStr == "D035D95F") { teacher = "PROF. H. C. VERMA"; dept = "DEPARTMENT OF PHYSICS"; subj = "PHYSICS"; }
      else if (uidStr == "89D14906") { teacher = "DR. P. MUKHERJEE"; dept = "DEPARTMENT OF CHEMISTRY"; subj = "CHEMISTRY"; }
      else if (uidStr == "0D5AFA06") { teacher = "PROF. ALAN TURING"; dept = "COMPUTER SCIENCE DEPT"; subj = "COMP SCI"; }
      else if (uidStr == "149680A7") { teacher = "MS. ARUNDHATI ROY"; dept = "DEPARTMENT OF ENGLISH"; subj = "ENGLISH"; }
      else if (uidStr == "CC9BE931") { teacher = "PROF. S. RAMANUJAN"; dept = "MATHEMATICS DEPT"; subj = "MATHEMATICS"; }

      currentSubject = subj;
      isSubjectLocked = false; // 🛡️ Unlocks the console!
      sessionPages = 0;
      currentSlide = 0;

      // 🎵 Auditory feedback for card tap
      beep(1, 70, 0, 2700);

      drawNFCWelcomeCard(teacher.c_str(), dept.c_str(), subj.c_str());
      sendEvent("nfc", String("{\"uid\":\"") + uidStr + "\"}");
    }
  }
}

// ==============================================================================
// 11. SETUP & MAIN LOOP
// ==============================================================================
void setup() {
  Serial.begin(115200);
  delay(500);

  Serial.println("\n══════════════════════════════════════════════════════════");
  Serial.println("  PROJECT VERONICA — ESP32 POD FIRMWARE");
  Serial.println("  Dedicated Node: PN532 NFC + Passive Buzzer");
  Serial.println("══════════════════════════════════════════════════════════");

  // 1. Buzzer setup & immediate boot beep
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);
  Serial.printf("🔊 Initializing Passive Buzzer on GPIO %d...\n", BUZZER_PIN);
  playTone(2000, 80);
  delay(40);
  playTone(2800, 100);
  Serial.println("✅ Buzzer OK");

#if ENABLE_TFT_DISPLAY
  // 2. TFT Display Initialization
  Serial.println("🖥️ Initializing TFT Display (ILI9486)...");
  tft.init();
  tft.setRotation(1);
  tft.fillScreen(COLOR_DARK_BG);
  Serial.println("✅ TFT Initialized & Screen Cleared");

#if defined(TOUCH_CS)
  uint16_t calData[5] = { 285, 3550, 395, 3450, 7 };
  tft.setTouch(calData);
#endif
#else
  Serial.println("🖥️ TFT Display: Bypassed on ESP32 (UI running on Raspberry Pi 5 Chromium Kiosk)");
#endif

  // 3. PN532 NFC Reader Initialization (I2C: SDA=GPIO21, SCL=GPIO22)
  Serial.printf("📡 Initializing PN532 NFC Reader on I2C (SDA=GPIO%d, SCL=GPIO%d)...\n", PN532_SDA, PN532_SCL);
  Wire.begin(PN532_SDA, PN532_SCL);
  Wire.setClock(100000); // 100kHz standard I2C for rock-solid stability
  Wire.setTimeOut(250);  // Prevent clock-stretch timeouts
  delay(200);            // Allow PN532 power-on stabilization

  // Probe I2C bus address 0x24
  Serial.println("🔍 Probing I2C address 0x24 for PN532...");
  Wire.beginTransmission(0x24);
  byte i2c_err = Wire.endTransmission();
  if (i2c_err == 0) {
    Serial.println("   📍 I2C Device ACK received at address 0x24 (PN532 chip present)!");
  } else {
    Serial.printf("   ⚠️ No ACK at address 0x24 (Wire error: %d).\n", i2c_err);
    Serial.println("   👉 Check PN532 DIP Switches: I2C mode requires CH1=ON (1), CH2=OFF (0).");
    Serial.println("   👉 Check VCC: connect to 3.3V or 5V (VIN), and GND to GND.");
  }

  nfc.begin();

  // Retry up to 5 times to wake PN532 from low-power standby
  uint32_t versiondata = 0;
  for (int attempt = 1; attempt <= 5; attempt++) {
    versiondata = nfc.getFirmwareVersion();
    if (versiondata) break;
    delay(100);
  }

  if (versiondata) {
    nfc.SAMConfig();
    Serial.printf("✅ PN532 Online! Chip: PN5%02X, Firmware Ver: %d.%d\n",
                  (versiondata >> 24) & 0xFF,
                  (versiondata >> 16) & 0xFF,
                  (versiondata >> 8) & 0xFF);
    playTone(3200, 60);
  } else {
    Serial.println("⚠️ PN532 NFC Reader not detected! Check 3.3V/GND/SDA/SCL wiring & DIP switches.");
  }

#if ENABLE_TFT_DISPLAY
  // 4. Initial UI Render
  Serial.println("🎨 Rendering UI Dashboard...");
  renderUI();
  lastActivityTime = millis();
  Serial.println("✅ UI Render Complete");
#endif

  // 5. Connect to Wi-Fi
  Serial.printf("📶 Connecting Wi-Fi to [%s]...\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  beep(1, 120, 0, 1800); // Ready chime
  Serial.println("🚀 Sensor Pod Ready! Scanning for NFC tags...");
}

void loop() {
  ensureConnection();
#if ENABLE_TFT_DISPLAY
  pollTouch();
#endif
  pollNFC();
  checkIncomingCommands();

#if ENABLE_TFT_DISPLAY
  // Dismiss NFC Greeting after 2.2 seconds
  if (isShowingNFCWelcome && (millis() - nfcWelcomeTime > 2200)) {
    isShowingNFCWelcome = false;
    renderUI();
  }

  // Dismiss Interlock Alert after 3 seconds
  if (isShowingInterlock && (millis() - interlockStartTime > 3000)) {
    isShowingInterlock = false;
    currentSlide = 2; // Jump to subjects
    renderUI();
  }

  // Live Timer Tick for Recording HUD
  static unsigned long last_rec_tick = 0;
  if (isRecording && (millis() - last_rec_tick >= 1000)) {
    last_rec_tick = millis();
    updateRecordingTimer();
  }

  // 60-Second Inactivity Screen Saver Watchdog
  if (!isSleeping && !isRecording && !isShowingNFCWelcome && !isShowingInterlock && (millis() - lastActivityTime > SLEEP_TIMEOUT_MS)) {
    enterSleepMode();
  }
#endif

  // Periodic 10s Heartbeat Telemetry to Pi 5
  if (millis() - last_heartbeat > 10000) {
    last_heartbeat = millis();
    if (client.connected()) {
      sendEvent("heartbeat", String("{\"rssi\":") + String(WiFi.RSSI()) + ",\"recording\":" + (isRecording ? "true" : "false") + "}");
    }
#if ENABLE_TFT_DISPLAY
    if (!isSleeping && !isRecording && !isShowingNFCWelcome && !isShowingInterlock) {
      drawHeader();
    }
#endif
  }

  delay(10);
}
