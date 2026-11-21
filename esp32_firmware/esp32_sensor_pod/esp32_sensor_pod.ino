/*
  ╔═══════════════════════════════════════════════════════════════════════════╗
  ║         PROJECT VERONICA — TIER 1: DEDICATED SENSOR & NFC POD             ║
  ║  Hardware Controller: ESP32-WROOM-32D (30-pin)                            ║
  ║  Peripherals:                                                             ║
  ║    • PN532 NFC Module over I2C: SDA -> GPIO 21, SCL -> GPIO 22            ║
  ║    • Passive Piezo Buzzer: Signal -> GPIO 15                              ║
  ║  Function:                                                                ║
  ║    • Zero-friction teacher badge tap & dispatch via Wi-Fi TCP to Pi 5     ║
  ║    • Acoustic feedback chimes on badge scan and system alerts             ║
  ║    • Sub-10ms packet dispatch directly to Raspberry Pi 5 Core (Port 8765) ║
  ╚═══════════════════════════════════════════════════════════════════════════╝
*/

#include <WiFi.h>
#include <Wire.h>
#include <Adafruit_PN532.h>

// ══════════════════════════════════════════════════════════════════════
// 1. PIN CONFIGURATION (Soldered Pins)
// ══════════════════════════════════════════════════════════════════════
#define BUZZER_PIN     15     // Passive buzzer pin (tone() PWM driven)
#define BUZZER_FREQ  2000     // 2kHz resonant chime frequency
#define PN532_SDA      21     // I2C Data
#define PN532_SCL      22     // I2C Clock

// ══════════════════════════════════════════════════════════════════════
// 2. NETWORK CREDENTIALS & PI 5 HUB IP
// ══════════════════════════════════════════════════════════════════════
// Adjust to match your Raspberry Pi 5 Hotspot or shared Wi-Fi network:
const char* WIFI_SSID     = "Veronica_AP";       // Match config.py or your router
const char* WIFI_PASSWORD = "veronica_access";   // Match config.py or your router

// If Pi 5 is running Hotspot mode: default is usually 192.168.4.1
// If both Pi 5 and ESP32 are on your home Wi-Fi: set to Pi 5's Wi-Fi IP (e.g. 192.168.1.xxx)
const char* PI5_HOST      = "192.168.4.1";       
const uint16_t PI5_PORT   = 8765;                // Matches POD_SERVER_PORT in config.py

// ══════════════════════════════════════════════════════════════════════
// 3. HARDWARE INSTANCES
// ══════════════════════════════════════════════════════════════════════
Adafruit_PN532 nfc(PN532_SDA, PN532_SCL);
WiFiClient client;

unsigned long last_nfc_poll   = 0;
unsigned long last_nfc_time   = 0;
String        last_nfc_uid    = "";
unsigned long last_heartbeat  = 0;
unsigned long last_wifi_retry = 0;
unsigned long last_tcp_retry  = 0;

// ══════════════════════════════════════════════════════════════════════
// 4. ACOUSTIC CHIME HELPERS (Passive Buzzer via tone())
// ══════════════════════════════════════════════════════════════════════
void playTone(int freq, int duration_ms) {
  if (freq <= 0) return;
  tone(BUZZER_PIN, freq, duration_ms);
  delay(duration_ms);
  noTone(BUZZER_PIN);
}

void beep(int times = 1, int duration_ms = 80, int gap_ms = 60, int freq = BUZZER_FREQ) {
  for (int i = 0; i < times; i++) {
    playTone(freq > 0 ? freq : BUZZER_FREQ, duration_ms);
    if (i < times - 1) delay(gap_ms);
  }
}

// ══════════════════════════════════════════════════════════════════════
// 5. TCP NETWORK CLIENT & EVENT SENDER
// ══════════════════════════════════════════════════════════════════════
void ensureConnection() {
  // 1. Maintain Wi-Fi link
  if (WiFi.status() != WL_CONNECTED) {
    if (millis() - last_wifi_retry > 5000) {
      last_wifi_retry = millis();
      Serial.printf("📶 Connecting to Wi-Fi [%s]...\n", WIFI_SSID);
      WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    }
    return;
  }

  // 2. Maintain TCP link to Pi 5 (Port 8765)
  if (!client.connected()) {
    if (millis() - last_tcp_retry > 3000) {
      last_tcp_retry = millis();
      Serial.printf("🔌 Connecting to Pi 5 Core at %s:%d...\n", PI5_HOST, PI5_PORT);
      if (client.connect(PI5_HOST, PI5_PORT)) {
        Serial.println("✅ Connected to Raspberry Pi 5 Core Hub!");
        beep(2, 60, 40, 2400); // 2 confirmation beeps
      } else {
        Serial.println("⚠️ Pi 5 connection pending...");
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
    Serial.println("⚠️ TCP Offline: Event cannot be sent yet.");
  }
}

// Listen for incoming commands from Pi 5 (e.g. buzzer trigger)
void checkIncomingCommands() {
  while (client.available()) {
    String line = client.readStringUntil('\n');
    line.trim();
    if (line.length() > 0) {
      Serial.println("📥 Pi 5 Command: " + line);

      // Trigger Buzzer from Pi 5
      if (line.indexOf("\"cmd\":\"beep\"") >= 0) {
        int times = 1;
        int dur = 80;
        int freq = BUZZER_FREQ;

        int tIdx = line.indexOf("\"times\":");
        if (tIdx >= 0) times = line.substring(tIdx + 8).toInt();

        int dIdx = line.indexOf("\"duration\":");
        if (dIdx >= 0) dur = line.substring(dIdx + 11).toInt();

        int fIdx = line.indexOf("\"freq\":");
        if (fIdx >= 0) freq = line.substring(fIdx + 7).toInt();

        beep(times, dur, 50, freq);
      }
    }
  }
}

// ══════════════════════════════════════════════════════════════════════
// 6. NFC READER POLLING (PN532 over I2C)
// ══════════════════════════════════════════════════════════════════════
void pollNFC() {
  if (millis() - last_nfc_poll < 150) return;
  last_nfc_poll = millis();

  uint8_t uid[7];
  uint8_t uidLength;

  // Poll ISO14443A cards with 35ms quick timeout
  if (nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A, uid, &uidLength, 35)) {
    String uidStr = "";
    for (uint8_t i = 0; i < uidLength; i++) {
      if (uid[i] < 0x10) uidStr += "0";
      uidStr += String(uid[i], HEX);
    }
    uidStr.toUpperCase();

    // Prevent repeated re-triggers within 2.5 seconds
    if (uidStr != last_nfc_uid || (millis() - last_nfc_time > 2500)) {
      last_nfc_uid = uidStr;
      last_nfc_time = millis();

      Serial.printf("🏷️ NFC Card Scanned! UID: [%s]\n", uidStr.c_str());

      // 🎵 Chime feedback: teacher recognized
      beep(1, 60, 20, 2200);
      delay(20);
      beep(1, 100, 20, 2800);

      // Send to Pi 5 via TCP
      sendEvent("nfc", String("{\"uid\":\"") + uidStr + "\"}");
    }
  }
}

// ══════════════════════════════════════════════════════════════════════
// 7. SETUP & MAIN LOOP
// ══════════════════════════════════════════════════════════════════════
void setup() {
  Serial.begin(115200);
  delay(300);

  Serial.println("\n══════════════════════════════════════════════════════════");
  Serial.println("  PROJECT VERONICA — ESP32 SENSOR POD FIRMWARE");
  Serial.println("  Dedicated Node: PN532 NFC + Passive Buzzer");
  Serial.println("══════════════════════════════════════════════════════════");

  // 1. Buzzer Setup & Quick Boot Beep
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);
  Serial.printf("🔊 Initializing Buzzer on GPIO %d...\n", BUZZER_PIN);
  playTone(2000, 80);
  delay(40);
  playTone(2800, 100);
  Serial.println("✅ Buzzer OK");

  // 2. PN532 NFC Reader Initialization (I2C: SDA=GPIO21, SCL=GPIO22)
  Serial.println("📡 Initializing PN532 NFC Reader on I2C (GPIO 21/22)...");
  Wire.begin(PN532_SDA, PN532_SCL);
  Wire.setClock(100000); // 100kHz standard I2C for rock-solid stability
  nfc.begin();
  uint32_t versiondata = nfc.getFirmwareVersion();
  if (versiondata) {
    nfc.SAMConfig();
    Serial.printf("✅ PN532 Online! Chip: PN5%02X, Firmware Ver: %d.%d\n",
                  (versiondata >> 24) & 0xFF,
                  (versiondata >> 16) & 0xFF,
                  (versiondata >> 8) & 0xFF);
  } else {
    Serial.println("⚠️ PN532 NFC Reader not detected! Check 3.3V/GND/SDA/SCL wiring.");
  }

  // 3. Connect to Wi-Fi
  Serial.printf("📶 Connecting Wi-Fi to [%s]...\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  // Ready signal
  beep(1, 120, 0, 1800);
  Serial.println("🚀 Sensor Pod Ready! Scanning for NFC tags...");
}

void loop() {
  ensureConnection();
  pollNFC();
  checkIncomingCommands();

  // Periodic 8s Heartbeat Telemetry to Pi 5
  if (millis() - last_heartbeat > 8000) {
    last_heartbeat = millis();
    if (client.connected()) {
      sendEvent("heartbeat", String("{\"rssi\":") + String(WiFi.RSSI()) + ",\"node\":\"sensor_pod\"}");
    }
  }

  delay(10);
}

