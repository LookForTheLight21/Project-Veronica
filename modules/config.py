"""
Configuration constants & Dynamic Config Engine for Project Veronica FINAL.
Tier 1: ESP32 Teacher Lectern Pod (Keypad, NFC, Buzzer)
Tier 2: Raspberry Pi 5 Overhead Edge Compute Hub (Kreo Owl 4K, Projector Display, Cloud)
"""
import os
import json
import shutil

# ==============================================================================
# 1. STORAGE PATHS (Organized directory hierarchy in project root)
# ==============================================================================
BASE_DIR    = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STORAGE_DIR = os.path.join(BASE_DIR, "storage")
PHOTOS_DIR  = os.path.join(STORAGE_DIR, "photos")
VIDEOS_DIR  = os.path.join(STORAGE_DIR, "videos")
NOTES_DIR   = os.path.join(STORAGE_DIR, "notes")
CONFIG_JSON_PATH = os.path.join(BASE_DIR, "config.json")

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
# 6. HARDWARE & ACOUSTIC PARAMETERS
# ==============================================================================
BUZZER_FREQ = 2000                  # Resonant frequency in Hz for passive piezo buzzer
INACTIVITY_TIMEOUT_SEC = 1200       # 20 minutes idle timeout before auto-compiling lecture PDF

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
    8:  "COMPILE_PDF",
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

# ==============================================================================
# 8. DIAGNOSTIC PORTAL CREDENTIALS
# ==============================================================================
ADMIN_USERNAME = "Chorie"
ADMIN_PASSWORD = "1234"


# ==============================================================================
# 9. DYNAMIC CONFIGURATION ENGINE (Field Technician Persistence)
# ==============================================================================
def get_all_config():
    """Returns all current configurations as a structured dictionary."""
    return {
        "WIFI_SSID": WIFI_SSID,
        "WIFI_PASSWORD": WIFI_PASSWORD,
        "POD_SERVER_HOST": POD_SERVER_HOST,
        "POD_SERVER_PORT": POD_SERVER_PORT,
        "BOT_TOKEN": BOT_TOKEN,
        "CHAT_ID": CHAT_ID,
        "ALLOWED_USERS": ALLOWED_USERS,
        "FOLDER_ID": FOLDER_ID,
        "KERO_VIDEO_DEVICE": KERO_VIDEO_DEVICE,
        "KERO_AUDIO_DEVICE": KERO_AUDIO_DEVICE,
        "KERO_WIDTH": KERO_WIDTH,
        "KERO_HEIGHT": KERO_HEIGHT,
        "KERO_FPS": KERO_FPS,
        "KERO_INPUT_FORMAT": KERO_INPUT_FORMAT,
        "BUZZER_FREQ": BUZZER_FREQ,
        "INACTIVITY_TIMEOUT_SEC": INACTIVITY_TIMEOUT_SEC,
        "NFC_MAP": NFC_MAP,
        "MODE_KEYS": {str(k): v for k, v in MODE_KEYS.items()},
        "SUBJECT_KEYS": {str(k): v for k, v in SUBJECT_KEYS.items()},
        "SECURE_CODE_SEQ": SECURE_CODE_SEQ,
        "ADMIN_USERNAME": ADMIN_USERNAME,
        "ADMIN_PASSWORD": ADMIN_PASSWORD,
    }


def load_dynamic_config():
    """Overrides in-memory constants if config.json exists."""
    global WIFI_SSID, WIFI_PASSWORD, POD_SERVER_PORT, BOT_TOKEN, CHAT_ID, ALLOWED_USERS
    global FOLDER_ID, KERO_VIDEO_DEVICE, KERO_AUDIO_DEVICE, KERO_WIDTH, KERO_HEIGHT
    global KERO_FPS, KERO_INPUT_FORMAT, BUZZER_FREQ, INACTIVITY_TIMEOUT_SEC
    global NFC_MAP, MODE_KEYS, SUBJECT_KEYS, SECURE_CODE_SEQ, ADMIN_USERNAME, ADMIN_PASSWORD

    if not os.path.exists(CONFIG_JSON_PATH):
        return

    try:
        with open(CONFIG_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        if "WIFI_SSID" in data: WIFI_SSID = data["WIFI_SSID"]
        if "WIFI_PASSWORD" in data: WIFI_PASSWORD = data["WIFI_PASSWORD"]
        if "POD_SERVER_PORT" in data: POD_SERVER_PORT = int(data["POD_SERVER_PORT"])
        if "BOT_TOKEN" in data: BOT_TOKEN = data["BOT_TOKEN"]
        if "CHAT_ID" in data: CHAT_ID = str(data["CHAT_ID"])
        if "ALLOWED_USERS" in data: ALLOWED_USERS = [str(x) for x in data["ALLOWED_USERS"]]
        if "FOLDER_ID" in data: FOLDER_ID = data["FOLDER_ID"]
        if "KERO_VIDEO_DEVICE" in data: KERO_VIDEO_DEVICE = data["KERO_VIDEO_DEVICE"]
        if "KERO_AUDIO_DEVICE" in data: KERO_AUDIO_DEVICE = data["KERO_AUDIO_DEVICE"]
        if "KERO_WIDTH" in data: KERO_WIDTH = int(data["KERO_WIDTH"])
        if "KERO_HEIGHT" in data: KERO_HEIGHT = int(data["KERO_HEIGHT"])
        if "KERO_FPS" in data: KERO_FPS = int(data["KERO_FPS"])
        if "KERO_INPUT_FORMAT" in data: KERO_INPUT_FORMAT = data["KERO_INPUT_FORMAT"]
        if "BUZZER_FREQ" in data: BUZZER_FREQ = int(data["BUZZER_FREQ"])
        if "INACTIVITY_TIMEOUT_SEC" in data: INACTIVITY_TIMEOUT_SEC = int(data["INACTIVITY_TIMEOUT_SEC"])
        if "NFC_MAP" in data and isinstance(data["NFC_MAP"], dict):
            NFC_MAP = data["NFC_MAP"]
        if "MODE_KEYS" in data and isinstance(data["MODE_KEYS"], dict):
            MODE_KEYS = {int(k): v for k, v in data["MODE_KEYS"].items()}
        if "SUBJECT_KEYS" in data and isinstance(data["SUBJECT_KEYS"], dict):
            SUBJECT_KEYS = {int(k): v for k, v in data["SUBJECT_KEYS"].items()}
        if "SECURE_CODE_SEQ" in data: SECURE_CODE_SEQ = [int(x) for x in data["SECURE_CODE_SEQ"]]
        if "ADMIN_USERNAME" in data: ADMIN_USERNAME = data["ADMIN_USERNAME"]
        if "ADMIN_PASSWORD" in data: ADMIN_PASSWORD = data["ADMIN_PASSWORD"]

        print("⚙️ Dynamic configuration loaded successfully from config.json")
    except Exception as e:
        print(f"⚠️ Error loading config.json: {e}")


def save_dynamic_config(new_config):
    """Saves updated configurations to config.json and updates runtime constants."""
    current = get_all_config()
    current.update(new_config)

    with open(CONFIG_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2)

    load_dynamic_config()
    return current


# Load dynamic overrides upon import
load_dynamic_config()
