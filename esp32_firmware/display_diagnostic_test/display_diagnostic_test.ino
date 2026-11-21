#include <Arduino.h>

// Pins as wired:
#define LCD_RD   2
#define LCD_WR   4
#define LCD_RS  15
#define LCD_CS  33
#define LCD_RST 32

const uint8_t dataPins[8] = { 12, 13, 26, 25, 17, 16, 27, 14 };

void setBusWrite() {
  for (int i = 0; i < 8; i++) {
    pinMode(dataPins[i], OUTPUT);
  }
}

void setBusRead() {
  for (int i = 0; i < 8; i++) {
    pinMode(dataPins[i], INPUT_PULLUP);
  }
}

void write8(uint8_t val) {
  for (int i = 0; i < 8; i++) {
    digitalWrite(dataPins[i], (val >> i) & 1);
  }
  digitalWrite(LCD_WR, LOW);
  delayMicroseconds(1);
  digitalWrite(LCD_WR, HIGH);
}

uint8_t read8() {
  digitalWrite(LCD_RD, LOW);
  delayMicroseconds(2);
  uint8_t val = 0;
  for (int i = 0; i < 8; i++) {
    if (digitalRead(dataPins[i])) {
      val |= (1 << i);
    }
  }
  digitalWrite(LCD_RD, HIGH);
  return val;
}

void writeCommand(uint8_t cmd) {
  digitalWrite(LCD_RS, LOW);
  digitalWrite(LCD_CS, LOW);
  setBusWrite();
  write8(cmd);
  digitalWrite(LCD_CS, HIGH);
}

uint32_t readReg(uint8_t cmd, uint8_t numBytes) {
  writeCommand(cmd);
  digitalWrite(LCD_RS, HIGH);
  digitalWrite(LCD_CS, LOW);
  setBusRead();
  
  uint32_t val = 0;
  for (uint8_t i = 0; i < numBytes; i++) {
    uint8_t b = read8();
    Serial.printf(" [byte %d = 0x%02X]", i, b);
    val = (val << 8) | b;
  }
  digitalWrite(LCD_CS, HIGH);
  return val;
}

void setup() {
  Serial.begin(115200);
  delay(1500);

  Serial.println("\n══════════════════════════════════════════");
  Serial.println("  IDENTIFYING RED PARALLEL DISPLAY CHIP   ");
  Serial.println("══════════════════════════════════════════");

  pinMode(LCD_RD, OUTPUT);
  pinMode(LCD_WR, OUTPUT);
  pinMode(LCD_RS, OUTPUT);
  pinMode(LCD_CS, OUTPUT);
  pinMode(LCD_RST, OUTPUT);

  digitalWrite(LCD_RD, HIGH);
  digitalWrite(LCD_WR, HIGH);
  digitalWrite(LCD_RS, HIGH);
  digitalWrite(LCD_CS, HIGH);

  // Hardware Reset
  Serial.println("Hardware Resetting LCD...");
  digitalWrite(LCD_RST, HIGH);
  delay(50);
  digitalWrite(LCD_RST, LOW);
  delay(100);
  digitalWrite(LCD_RST, HIGH);
  delay(200);

  // Test reading Register 0x04 (Manufacturer ID)
  Serial.print("\nReading Reg 0x04:");
  readReg(0x04, 4);

  // Test reading Register 0xD3 (ILI9341 / ILI9486 / ILI9488 ID)
  Serial.print("\n\nReading Reg 0xD3:");
  readReg(0xD3, 4);

  // Test reading Register 0x00 (ILI9325 / SPFD5408)
  Serial.print("\n\nReading Reg 0x00:");
  readReg(0x00, 2);

  // Test reading Register 0x0A (Power mode)
  Serial.print("\n\nReading Reg 0x0A:");
  readReg(0x0A, 2);

  Serial.println("\n\n--- Done reading registers! ---");
}

void loop() {
  delay(2000);
}
