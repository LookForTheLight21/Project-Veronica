"""
Configuration constants for Project Veronica FINAL (Two-Tier Architecture).
Tier 1: ESP32 Teacher Lectern Pod (Keypad, NFC, Buzzer)
Tier 2: Raspberry Pi 5 Overhead Edge Compute Hub (Kreo Owl 4K, Projector Display, Cloud)
"""
import os
import shutil

# ==============================================================================
# 1. STORAGE PATHS (Organized directory hierarchy in project root)
# ==============================================================================
BASE_DIR    = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STORAGE_DIR = os.path.join(BASE_DIR, "storage")
PHOTOS_DIR  = os.path.join(STORAGE_DIR, "photos")
VIDEOS_DIR  = os.path.join(STORAGE_DIR, "videos")
NOTES_DIR   = os.path.join(STORAGE_DIR, "notes")

for d in [STORAGE_DIR, PHOTOS_DIR, VIDEOS_DIR, NOTES_DIR]:
    os.makedirs(d, exist_ok=True)

# ==============================================================================
# 2. NETWORK & TIER-1 POD COMMUNICATION
# ==============================================================================
POD_SERVER_HOST = "0.0.0.0"
POD_SERVER_PORT = 8765

# Wi-Fi Credentials for ESP32 and Pi 5 Hotspot
WIFI_SSID = "Veronica_AP"
WIFI_PASSWORD = "veronica_access"

# ==============================================================================
# 3. TELEGRAM BOT
# ==============================================================================
BOT_TOKEN     = "put yours"
CHAT_ID       = "enter the id detail"
ALLOWED_USERS = ["enter the detail"]

# ==============================================================================
# 4. GOOGLE DRIVE (Dynamic token path at project root)
# ==============================================================================
SCOPES     = ["https://www.googleapis.com/auth/drive.file"]
FOLDER_ID  = "12l5mNFGeAIcPHt-GZSti8KvHNAf-OENf"
TOKEN_PATH = os.path.join(BASE_DIR, "token.json")

# ==============================================================================
# 5. OVERHEAD KREO OWL 4K OPTICAL & AUDIO SENSORS (TIER 2 - PI 5 USB)
# ==============================================================================
FFMPEG_BIN        = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
KERO_VIDEO_DEVICE = "/dev/video0"
KERO_AUDIO_DEVICE = "plughw:CARD=webcam,DEV=0"
KERO_WIDTH        = 3840
KERO_HEIGHT       = 2160
KERO_FPS          = 30
KERO_INPUT_FORMAT = "mjpeg"

# ==============================================================================
# 6. TIER 1 POD HARDWARE PINS (ESP32-WROOM-32D)
# ==============================================================================
ESP32_PINS = {
    "BUZZER": 23,     # Passive PWM Piezo driven via NPN BC547 buffer
    "TTP229_SCL": 18, # Serial Clock
    "TTP229_SDO": 19, # Serial Data Out (active-low)
    "PN532_SDA": 21,  # I2C Data
    "PN532_SCL": 22,  # I2C Clock
}

# ==============================================================================
# 7. LOGICAL MAPPINGS & ACTIONS
# ==============================================================================
SUBJECT_KEYS = {
    5: "Extra",
}

MODE_KEYS = {
    1:  "PHOTO",
    2:  "VIDEO_TOGGLE",
    3:  "AUDIO_TOGGLE",
    4:  "PRIORITY_AUDIO_TOGGLE",
    6:  "STATS",
    7:  "STOP",
    13: "CLEAR_SUBJECT",
    14: "SECURE_SHUTDOWN",
    15: "SECURE_RESTART",
}

NFC_MAP = {
    "D035D95F": "Physics",
    "89D14906": "Chemistry",
    "0D5AFA06": "Computer Science",
    "149680A7": "English",
    "CC9BE931": "Math",
    "A30CF40D": "ACTION:PROJECTOR",     # Opens Fullscreen Classroom Projector View
    "5ACFFB3F": "ACTION:SHUTDOWN",      # Graceful system shutdown
    "4A8D2507": "ACTION:ADMIN_ALERT",   # Telegram alert + snapshot
}

# 4-Digit Security Passcode Sequence
SECURE_CODE_SEQ = [1, 9, 2, 7]

