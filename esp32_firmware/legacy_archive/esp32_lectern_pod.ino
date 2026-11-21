/*
  ╔══════════════════════════════════════════════════════════════════╗
  ║       PROJECT VERONICA — TIER 1: TEACHER LECTERN POD             ║
  ║  Hardware Controller: ESP32-WROOM-32D (30-pin)                  ║
  ║                                                                  ║
  ║  WIRING SPECIFICATION:                                           ║
  ║  • Buzzer       : GPIO 23 (Passive 2000Hz PWM via BC547 buffer)  ║
  ║  • TTP229 SCL   : GPIO 18 (Clock output from ESP32)              ║
  ║  • TTP229 SDO   : GPIO 19 (Data input to ESP32, Active-LOW)      ║
  ║    * Note: Bridge pads 3 & 7 on TTP229 P1 pad for 16-key mode    ║
  ║  • PN532 SDA    : GPIO 21 (I2C Data)                             ║
  ║  • PN532 SCL    : GPIO 22 (I2C Clock)                            ║
  ║  • VCC / GND    : 3.3V / 5V & Common GND                         ║
  ║                                                                  ║
  ║  PROTOCOL:                                                       ║
  ║  Streams JSON telemetry over TCP socket (Port 8765) to Pi 5.     ║
  ║  Non-blocking network reads (20ms timeout). Sub-10ms response.   ║
  ╚══════════════════════════════════════════════════════════════════╝
*/

#include <WiFi.h>
#include <Wire.h>
#include <Adafruit_PN532.h>

// ==============================================================================
// 1. PIN DEFINITIONS
// ==============================================================================
#define BUZZER_PIN    23
#define BUZZER_FREQ   2000   // 2 kHz resonant frequency for passive buzzer
#define TTP229_SCL    18
#define TTP229_SDO    19
#define PN532_SDA     21
#define PN532_SCL     22

// ==============================================================================
// 2. NETWORK CONFIGURATION (Pi 5 Overhead Hub IP & Port)
// ==============================================================================
const char* WIFI_SSID     = "Veronica_AP";       // Match config.py
const char* WIFI_PASSWORD = "veronica_access";   // Match config.py
const char* PI5_HOST      = "192.168.4.1";       // Pi 5 IP
const uint16_t PI5_PORT   = 8765;

// ==============================================================================
// 3. HARDWARE INSTANCES & STATE
// ==============================================================================
Adafruit_PN532 nfc(PN532_SDA, PN532_SCL);
WiFiClient client;

uint16_t prev_key_state = 0;
unsigned long last_nfc_poll = 0;
unsigned long last_heartbeat = 0;
unsigned long last_wifi_retry = 0;
String last_nfc_uid = "";
unsigned long last_nfc_time = 0;

// ==============================================================================
// 4. ACOUSTIC BUZZER CONTROL (PASSIVE PWM TONE GENERATION)
// ==============================================================================
void beep(int times = 1, int duration_ms = 100, int gap_ms = 80, int freq = BUZZER_FREQ) {
  for (int i = 0; i < times; i++) {
    // Generate square wave for passive buzzer at target frequency
    tone(BUZZER_PIN, freq > 0 ? freq : BUZZER_FREQ, duration_ms);
    delay(duration_ms);
    noTone(BUZZER_PIN);
    if (i < times - 1) {
      delay(gap_ms);
    }
  }
}

// ==============================================================================
// 5. TTP229 16-KEY CAPACITIVE KEYPAD SCANNER (Bit-Bang)
// ==============================================================================
uint16_t readTTP229() {
  uint16_t keys = 0;
  for (int i = 0; i < 16; i++) {
    digitalWrite(TTP229_SCL, LOW);
    delayMicroseconds(50);
    // TTP229 is active-low: 0 indicates touched
    if (digitalRead(TTP229_SDO) == LOW) {
      keys |= (1 << i);
    }
    digitalWrite(TTP229_SCL, HIGH);
    delayMicroseconds(50);
  }
  return keys;
}

void pollKeypad() {
  uint16_t current = readTTP229();
  for (int bit = 0; bit < 16; bit++) {
    bool wasPressed = (prev_key_state & (1 << bit)) != 0;
    bool isPressed  = (current & (1 << bit)) != 0;

    // Detect newly pressed keys
    if (isPressed && !wasPressed) {
      int keyNum = bit + 1;
      Serial.printf("🎹 Key Pressed: %d\n", keyNum);
      
      // Instant local acoustic feedback (<10ms)
      beep(1, 40);

      // Transmit to Pi 5
      sendEvent("key", String("{\"key\":") + String(keyNum) + "}");
    }
  }
  prev_key_state = current;
}

// ==============================================================================
// 6. PN532 NFC READER (I2C)
// ==============================================================================
void pollNFC() {
  if (millis() - last_nfc_poll < 200) return;
  last_nfc_poll = millis();

  uint8_t uid[7];
  uint8_t uidLength;

  if (nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A, uid, &uidLength, 50)) {
    String uidStr = "";
    for (uint8_t i = 0; i < uidLength; i++) {
      if (uid[i] < 0x10) uidStr += "0";
      uidStr += String(uid[i], HEX);
    }
    uidStr.toUpperCase();

    // Debounce duplicate reads within 2 seconds
    if (uidStr != last_nfc_uid || (millis() - last_nfc_time > 2000)) {
      last_nfc_uid = uidStr;
      last_nfc_time = millis();
      Serial.printf("🏷️ NFC Card Scanned: %s\n", uidStr.c_str());

      beep(2, 60, 50);
      sendEvent("nfc", String("{\"uid\":\"") + uidStr + "\"}");
    }
  }
}

// ==============================================================================
// 7. NETWORK TRANSMISSION & COMMAND DISPATCH
// ==============================================================================
void ensureConnection() {
  // 1. Wi-Fi Connection
  if (WiFi.status() != WL_CONNECTED) {
    if (millis() - last_wifi_retry > 5000) {
      last_wifi_retry = millis();
      Serial.println("🔄 Connecting to Wi-Fi...");
      WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    }
    return;
  }

  // 2. TCP Link to Pi 5
  if (!client.connected()) {
    static unsigned long last_tcp_retry = 0;
    if (millis() - last_tcp_retry > 3000) {
      last_tcp_retry = millis();
      Serial.printf("🔌 Connecting to Pi 5 (%s:%d)...\n", PI5_HOST, PI5_PORT);
      if (client.connect(PI5_HOST, PI5_PORT)) {
        Serial.println("✅ Connected to Pi 5 Edge Hub!");
        beep(2, 80, 50);
      }
    }
  }
}

void sendEvent(const char* eventType, String jsonBody) {
  if (client.connected()) {
    String msg = String("{\"event\":\"") + eventType + "\"," + jsonBody.substring(1) + "\n";
    client.print(msg);
    Serial.print("📤 Sent: " + msg);
  } else {
    Serial.println("⚠️ Cannot send: Pi 5 link disconnected");
  }
}

void checkIncomingCommands() {
  while (client.available()) {
    String line = client.readStringUntil('\n');
    line.trim();
    if (line.length() > 0) {
      Serial.println("📥 Command from Pi 5: " + line);
      // Parse beep commands: {"cmd":"beep","times":2,"duration":100,"gap":80}
      if (line.indexOf("\"cmd\":\"beep\"") >= 0) {
        int times = 1;
        int duration = 100;
        int gap = 80;
        int freq = BUZZER_FREQ;
        
        int idx = line.indexOf("\"times\":");
        if (idx > 0) times = line.substring(idx + 8).toInt();
        idx = line.indexOf("\"duration\":");
        if (idx > 0) duration = line.substring(idx + 11).toInt();
        idx = line.indexOf("\"gap\":");
        if (idx > 0) gap = line.substring(idx + 6).toInt();
        idx = line.indexOf("\"freq\":");
        if (idx > 0) freq = line.substring(idx + 7).toInt();

        beep(times, duration, gap, freq);
      }
    }
  }
}

// ==============================================================================
// 8. SETUP & MAIN LOOP
// ==============================================================================
void setup() {
  Serial.begin(115200);
  delay(500);

  Serial.println("\n══════════════════════════════════════════");
  Serial.println(" Project Veronica — Lectern Pod (Tier 1)");
  Serial.println("══════════════════════════════════════════");

  // Non-blocking network read timeout (Fixes 1000ms freeze bug)
  client.setTimeout(20);

  // Passive Buzzer Pin
  pinMode(BUZZER_PIN, OUTPUT);
  noTone(BUZZER_PIN);

  // TTP229 Bit-Bang Pins
  pinMode(TTP229_SCL, OUTPUT);
  pinMode(TTP229_SDO, INPUT_PULLUP);
  digitalWrite(TTP229_SCL, HIGH);

  // Initialize PN532 I2C
  Wire.begin(PN532_SDA, PN532_SCL);
  nfc.begin();
  uint32_t versiondata = nfc.getFirmwareVersion();
  if (!versiondata) {
    Serial.println("⚠️ PN532 NFC not detected! Check I2C wiring.");
  } else {
    Serial.printf("✅ PN532 NFC Online (Chip PN5%02X, Firmware ver %d.%d)\n",
                  (versiondata >> 24) & 0xFF,
                  (versiondata >> 16) & 0xFF,
                  (versiondata >> 8) & 0xFF);
    nfc.SAMConfig();
  }

  // Initial Wi-Fi begin
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  // Power-on acoustic confirmation
  beep(1, 150);
}

void loop() {
  ensureConnection();
  pollKeypad();
  pollNFC();
  checkIncomingCommands();

  // Send periodic 10s heartbeat
  if (millis() - last_heartbeat > 10000) {
    last_heartbeat = millis();
    if (client.connected()) {
      sendEvent("heartbeat", String("{\"rssi\":") + String(WiFi.RSSI()) + "}");
    }
  }

  delay(10);
}
