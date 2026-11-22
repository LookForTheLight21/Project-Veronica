/**
 * ══════════════════════════════════════════════════════════════════════
 *  PROJECT VERONICA — ESP32 3.5" TFT TOUCH POD HARDWARE PINOUTS
 * ══════════════════════════════════════════════════════════════════════
 *  Pre-configured pinout profiles for 3.5" SPI / Parallel Touch Displays
 *  Resolution: 480 x 320 Landscape (Horizontal Orientation)
 */

#ifndef DISPLAY_CONFIG_H
#define DISPLAY_CONFIG_H

// ── Profile 1: Standard ESP32 SPI 3.5" TFT (Dummy remapped) ──
#define TFT_MISO       19
#define TFT_MOSI       23
#define TFT_SCLK       14
#define TFT_CS         12
#define TFT_DC          2
#define TFT_RST         4
#define TFT_BL         32   // Backlight PWM pin

#define TOUCH_CS       15   // Dummy
#define TOUCH_IRQ      13   // Dummy

// ── Peripherals (GPIO 27 Buzzer, GPIO 21 SDA, GPIO 22 SCL) ──
#define BUZZER_PIN     27   // Passive buzzer on GPIO 27
#define BUZZER_FREQ  2000   // 2kHz resonant frequency
#define PN532_SDA      21   // NFC I2C SDA on GPIO 21
#define PN532_SCL      22   // NFC I2C SCL on GPIO 22
#define PN532_IRQ      34   // Dummy input pin for Adafruit constructor (pin 34 is input-only)
#define PN532_RESET    33   // Dummy pin for Adafruit constructor

// ── Display Dimensions ──
#define SCREEN_WIDTH   320
#define SCREEN_HEIGHT  240

// ── Color Definitions (RGB565 16-bit format) ──
// Dark Mode Palette (Night Mode)
#define COLOR_DARK_BG       0x0842  // #07090e Obsidian Black
#define COLOR_DARK_CARD     0x10C4  // #111622 Surface Card
#define COLOR_DARK_BORDER   0x2965  // Border
#define COLOR_DARK_TEXT     0xFFFF  // Pure White
#define COLOR_DARK_MUTED    0x632C  // Muted Gray

// Day Light Mode Palette (Pure White Canvas)
#define COLOR_LIGHT_BG      0xFFFF  // Pure White
#define COLOR_LIGHT_CARD    0xF7BE  // Soft White Card
#define COLOR_LIGHT_BORDER  0xCE59  // Border
#define COLOR_LIGHT_TEXT    0x0842  // Dark Slate
#define COLOR_LIGHT_MUTED   0x738E  // Medium Gray

// Vibrant Accent Colors
#define ACCENT_ORANGE       0xFD20  // #ff6b00 Signature High-Gloss Orange
#define ACCENT_CYAN         0x07FF  // #00f2fe Ice Cyan
#define ACCENT_PURPLE       0xA3BF  // #a277ff Cyber Purple
#define ACCENT_GREEN        0x3689  // #34d399 Emerald Green
#define ACCENT_PINK         0xFA50  // #ff4b82 Hot Pink
#define ACCENT_AMBER        0xFD80  // #f59e0b Amber Gold
#define ACCENT_RED          0xF800  // #ef4444 Danger Red
#define ACCENT_BLUE         0x3DFE  // #38bdf8 Sky Blue

#endif // DISPLAY_CONFIG_H

