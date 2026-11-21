"""
╔══════════════════════════════════════════════════════════════╗
║              PROJECT VERONICA  —  FINAL                     ║
║  Hardware : Raspberry Pi 5                                  ║
║  Keypad   : TTP229 (Bit-Bang  GPIO4=SDO  GPIO17=SCL)        ║
║  NFC      : PN532 (I2C)                                     ║
║  Buzzer   : Passive PWM  GPIO 23                            ║
║  Camera   : Kero 4K Owl  /dev/video0  (MJPEG)              ║
║  Mic      : plughw:CARD=webcam,DEV=0  (48kHz stereo)       ║
║  Storage  : Google Drive                                    ║
║  Notify   : Telegram Bot                                    ║
║     ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import print_function

import os, time, datetime, requests, subprocess, functools, builtins
import signal, shutil, psutil, threading, socket, json
from threading import Lock
from flask import Flask, request as flask_request
# Google Drive
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# GPIO (buzzer only via gpiozero PWM — confirmed working)
from gpiozero import PWMOutputDevice

# NFC
import board, busio
from adafruit_pn532.i2c import PN532_I2C

# Pi 5 pin factory
try:
    from gpiozero.pins.lgpio import LGPIOFactory
    factory = LGPIOFactory()
except ImportError:
    print("⚠️  LGPIO not found — using default pin factory.")
    factory = None

print = functools.partial(builtins.print, flush=True)


# ═══════════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════════

ALLOWED_USERS = ["1356709538"]
SCOPES        = ["https://www.googleapis.com/auth/drive.file"]
FOLDER_ID     = "12l5mNFGeAIcPHt-GZSti8KvHNAf-OENf"
BOT_TOKEN     = "8365210789:AAFbiu9hyMDwTkvLNq7vOnGLDI7g9WT-BEg"
CHAT_ID       = "1356709538"
TOKEN_PATH    = "/home/light/token.json"

# System ffmpeg — DO NOT change to /usr/local/bin/ffmpeg (static build has no ALSA)
FFMPEG_BIN    = "/usr/bin/ffmpeg"

# ── Kero 4K Owl ───────────────────────────────────────────────
# Confirmed: MJPEG required for 4K@30fps. YUYV only does 5fps.
# Audio confirmed working: plughw:CARD=webcam,DEV=0 @ 48kHz stereo S16_LE
KERO_VIDEO_DEVICE = "/dev/video0"
KERO_AUDIO_DEVICE = "plughw:CARD=webcam,DEV=0"
KERO_WIDTH        = 3840
KERO_HEIGHT       = 2160
KERO_FPS          = 30
KERO_INPUT_FORMAT = "mjpeg"

# ── Buzzer (PASSIVE — PWM confirmed working) ───────────────────
BUZZER_PIN  = 23
BUZZER_FREQ = 2000   # Hz — pitch of the beep

# ── TTP229 Bit-Bang pins (confirmed working via gpiod test) ───
TTP229_SDO = 4    # GPIO 4  — Physical Pin 7  — Data
TTP229_SCL = 17   # GPIO 17 — Physical Pin 11 — Clock

# ── NFC ────────────────────────────────────────────────────────
NFC_ENABLED = True

# ── Key mappings  (TTP229 keys 1–16) ──────────────────────────
# Edit these to match your physical keypad layout
SUBJECT_KEYS = {
    5: "Extra",
}

MODE_KEYS = {
    1:  "PHOTO",
    2:  "VIDEO_TOGGLE",
    3:  "AUDIO_TOGGLE",
    4:  "PRIORITY_AUDIO_TOGGLE",   # Audio recorded + pinned on Telegram
    6:  "STATS",
    7:  "STOP",
    13: "CLEAR_SUBJECT",
    14: "SECURE_SHUTDOWN",         # Needs passcode: keys 1,9,2,7
    15: "SECURE_RESTART",          # Needs passcode: keys 1,9,2,7
}

# ── NFC card → subject/action map ─────────────────────────────
# Add all 8 UIDs here. Actions start with "ACTION:"
NFC_MAP = {
    "D035D95F": "Physics",
    "89D14906": "Chemistry",
    "0D5AFA06": "Computer Science",
    "149680A7": "English",
    "CC9BE931": "Math",
    "A30CF40D": "ACTION:BROWSER",       # Opens browser
    "5ACFFB3F": "ACTION:SHUTDOWN",      # Shuts down Pi
    "4A8D2507": "ACTION:ADMIN_ALERT",   # Sends alert + photo
}

# ── Security passcode sequence (key numbers) ───────────────────
SECURE_CODE_SEQ = [1, 9, 2, 7]


# ═══════════════════════════════════════════════════════════════
#  GLOBAL STATE
# ═══════════════════════════════════════════════════════════════

recording         = False
ffmpeg_proc       = None
raw_filename      = None

audio_recording   = False
audio_proc        = None
audio_filename    = None
audio_is_priority = False

current_subject   = None
state_lock        = Lock()

# Security state machine
secure_target_action = None
secure_current_step  = 0
secure_timer         = 0

app = Flask(__name__)


# ═══════════════════════════════════════════════════════════════
#  ACTIVITY LOG  —  Principal's Record System
# ═══════════════════════════════════════════════════════════════
# Tracks per-subject usage for inspection/authority reports.
# Saved to activity_log.json — persists across reboots.

ACTIVITY_LOG_PATH = "activity_log.json"

def _load_log():
    try:
        with open(ACTIVITY_LOG_PATH) as f:
            return json.load(f)
    except Exception:
        return {}

def _save_log(data):
    try:
        with open(ACTIVITY_LOG_PATH, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"⚠️  Activity log save error: {e}")

def log_activity(action_type):
    """
    Call this every time a subject-tagged action happens.
    action_type: "photo" | "video" | "audio" | "subject_change"
    """
    subj = current_subject or "Unassigned"
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    now   = datetime.datetime.now().strftime("%H:%M")

    data = _load_log()

    # Ensure structure exists
    if subj not in data:
        data[subj] = {"total_photos": 0, "total_videos": 0,
                       "total_audios": 0, "subject_changes": 0,
                       "daily": {}}
    if today not in data[subj]["daily"]:
        data[subj]["daily"][today] = {"photos": 0, "videos": 0,
                                       "audios": 0, "sessions": [],
                                       "subject_changes": 0}

    s = data[subj]
    d = s["daily"][today]

    if action_type == "photo":
        s["total_photos"] += 1
        d["photos"]        += 1
        d["sessions"].append({"type": "photo", "time": now})
    elif action_type == "video_start":
        s["total_videos"] += 1
        d["videos"]        += 1
        d["sessions"].append({"type": "video_start", "time": now})
    elif action_type == "audio_start":
        s["total_audios"] += 1
        d["audios"]        += 1
        d["sessions"].append({"type": "audio_start", "time": now})
    elif action_type == "subject_change":
        s["subject_changes"] += 1
        d["subject_changes"]  += 1
        d["sessions"].append({"type": "subject_set", "time": now})

    _save_log(data)


# ═══════════════════════════════════════════════════════════════
#  HARDWARE — Buzzer  (Passive PWM — confirmed working)
# ═══════════════════════════════════════════════════════════════

class BuzzerWrapper:
    """
    Passive buzzer driven by PWM.
    Confirmed working with:
        buzzer = PWMOutputDevice(23, pin_factory=factory)
        buzzer.frequency = 2000
        buzzer.value = 0.5   → ON
        buzzer.value = 0     → OFF
    """
    def __init__(self, pin, freq=BUZZER_FREQ):
        self.bz   = PWMOutputDevice(pin, pin_factory=factory)
        self.freq = freq
        self.bz.frequency = freq
        self.bz.value     = 0

    def beep(self, times=1, duration=0.15, gap=0.08):
        threading.Thread(target=self._beep_thread,
                         args=(times, duration, gap), daemon=True).start()

    def _beep_thread(self, times, duration, gap):
        for _ in range(times):
            self.bz.frequency = self.freq
            self.bz.value     = 0.5
            time.sleep(duration)
            self.bz.value     = 0
            time.sleep(gap)


# ═══════════════════════════════════════════════════════════════
#  HARDWARE — TTP229  (Bit-Bang via lgpio — confirmed working)
# ═══════════════════════════════════════════════════════════════

class TTP229Touch:
    """
    16-key capacitive keypad in bit-bang serial mode.

    Wiring (bridge points 3 & 7 on P1 pad for 16-key mode):
      SDO  → GPIO 4  (Pin 7)   — Data out (active LOW when touched)
      SCL  → GPIO 17 (Pin 11)  — Clock (we drive this)
      VCC  → 3.3V
      GND  → GND

    Confirmed working via gpiod test script.
    Uses lgpio directly (gpiochip4 = Pi 5 main header).
    """
    def __init__(self):
        self._sdo  = TTP229_SDO
        self._scl  = TTP229_SCL
        self._prev = 0
        self._h    = None
        try:
            import lgpio
            self._lgpio = lgpio
            self._h     = lgpio.gpiochip_open(4)   # gpiochip4 on Pi 5
            lgpio.gpio_claim_output(self._h, self._scl)
            lgpio.gpio_claim_input(self._h,  self._sdo)
            print(f"✅ TTP229 ready  (SDO=GPIO{self._sdo}  SCL=GPIO{self._scl})")
        except ImportError:
            print("❌ lgpio not found — install: sudo apt install python3-lgpio")
        except Exception as e:
            print(f"⚠️  TTP229 init error: {e}")

    def _read_raw(self):
        """16 clock pulses → 16-bit state. Bit N set = key N+1 touched."""
        if not self._h:
            return 0
        result = 0
        try:
            for i in range(16):
                self._lgpio.gpio_write(self._h, self._scl, 0)
                time.sleep(0.00005)                           # 50 µs
                if self._lgpio.gpio_read(self._h, self._sdo) == 0:  # Active LOW
                    result |= (1 << i)
                self._lgpio.gpio_write(self._h, self._scl, 1)
                time.sleep(0.00005)
        except Exception as e:
            print(f"⚠️  TTP229 read error: {e}")
        return result

    def get_newly_pressed(self):
        """Returns list of key numbers (1-16) that just transitioned to pressed."""
        current = self._read_raw()
        newly   = []
        for bit in range(16):
            was = bool(self._prev  & (1 << bit))
            now = bool(current & (1 << bit))
            if now and not was:
                newly.append(bit + 1)
        self._prev = current
        return newly


# ═══════════════════════════════════════════════════════════════
#  HARDWARE — NFC PN532  (I2C)
# ═══════════════════════════════════════════════════════════════

class NFCReaderPN532:
    def __init__(self):
        try:
            i2c        = busio.I2C(board.SCL, board.SDA)
            self.pn532 = PN532_I2C(i2c, debug=False)
            self.pn532.SAM_configuration()
            print("✅ NFC PN532 ready")
        except Exception as e:
            print(f"⚠️  NFC init failed: {e}")
            self.pn532 = None

    def poll(self):
        """Returns the NFC_MAP value for the scanned card, or None."""
        if not self.pn532:
            return None
        try:
            uid = self.pn532.read_passive_target(timeout=0.2)
            if uid:
                uid_str = "".join(f"{x:02X}" for x in uid)
                return NFC_MAP.get(uid_str)
        except Exception:
            pass
        return None


# ═══════════════════════════════════════════════════════════════
#  TELEGRAM
# ═══════════════════════════════════════════════════════════════

def send_telegram(msg, retries=3, delay=2, pin=False):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(url,
                              data={"chat_id": CHAT_ID, "text": msg},
                              timeout=10)
            if r.status_code == 200:
                print(f"✅ Telegram: {msg[:60]}")
                if pin:
                    try:
                        mid = r.json().get("result", {}).get("message_id")
                        if mid:
                            requests.post(
                                f"https://api.telegram.org/bot{BOT_TOKEN}/pinChatMessage",
                                data={"chat_id": CHAT_ID, "message_id": mid},
                                timeout=5)
                            print("📌 Message pinned")
                    except Exception as pe:
                        print(f"⚠️  Pin failed: {pe}")
                return True
            print(f"⚠️  Telegram HTTP {r.status_code}")
        except Exception as e:
            print(f"⚠️  Telegram attempt {attempt}: {e}")
        time.sleep(delay)
    return False


HELP_TEXT = (
    "📋 Project Veronica — Commands\n\n"
    "📸 /photo   — Snapshot + upload\n"
    "🎥 /video   — Start video+audio\n"
    "🎙 /audio   — Start audio only\n"
    "⏹ /stop    — Stop recording\n"
    "📊 /stats   — System stats\n"
    "📡 /status  — Recording status\n"
    "🔁 /reboot  — Reboot Pi\n"
    "❓ /help    — This message"
)


def load_last_update_id():
    try:
        with open("last_update_id.txt") as f:
            return int(f.read().strip())
    except Exception:
        return None

def save_last_update_id(uid):
    try:
        with open("last_update_id.txt", "w") as f:
            f.write(str(uid))
    except Exception as e:
        print(f"⚠️  Save update ID: {e}")


def telegram_listener():
    print("📡 Telegram listener started")
    url            = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    last_update_id = load_last_update_id()
    while True:
        try:
            params = {"timeout": 30, "allowed_updates": ["message"]}
            if last_update_id is not None:
                params["offset"] = last_update_id + 1
            resp = requests.get(url, params=params, timeout=40)
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                time.sleep(5); continue
            for update in data.get("result", []):
                uid = update["update_id"]
                last_update_id = uid
                save_last_update_id(uid)
                msg_obj   = update.get("message", {})
                text      = (msg_obj.get("text") or "").strip()
                sender_id = str(msg_obj.get("from", {}).get("id", ""))
                if not text: continue
                print(f"📩 [{sender_id}] {text}")
                if sender_id not in ALLOWED_USERS:
                    send_telegram("🚫 Unauthorized.")
                    continue
                _handle_telegram_command(text)
        except requests.exceptions.Timeout:
            pass
        except Exception as e:
            print(f"⚠️  Telegram listener: {e}")
            time.sleep(5)


def _handle_telegram_command(cmd):
    cmd = cmd.lower().split()[0]
    if cmd == "/photo":
        send_telegram(take_photo_and_upload())
    elif cmd == "/video":
        if recording or audio_recording:
            send_telegram("⚠️  Already recording. /stop first.")
        else:
            send_telegram(start_video_audio())
    elif cmd == "/audio":
        if recording or audio_recording:
            send_telegram("⚠️  Already recording. /stop first.")
        else:
            send_telegram(start_audio_only())
    elif cmd == "/stop":
        if recording:       send_telegram(stop_video_audio())
        elif audio_recording: send_telegram(stop_audio_only())
        else:               send_telegram("ℹ️  Nothing recording.")
    elif cmd == "/stats":   send_telegram(send_stats_report())
    elif cmd == "/status":  report_status()
    elif cmd == "/reboot":  reboot_system()
    elif cmd == "/help":    send_telegram(HELP_TEXT)
    else: send_telegram(f"❓ Unknown: {cmd}\nSend /help")


# ═══════════════════════════════════════════════════════════════
#  GOOGLE DRIVE
# ═══════════════════════════════════════════════════════════════

def get_drive_service():
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow  = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, "w") as tok:
            tok.write(creds.to_json())
    return build("drive", "v3", credentials=creds)

def get_month_folder(service, parent_id):
    month_name = datetime.datetime.now().strftime("%Y-%m")
    q = (f"'{parent_id}' in parents and "
         f"mimeType='application/vnd.google-apps.folder' and "
         f"name='{month_name}' and trashed=false")
    items = service.files().list(q=q, fields="files(id)").execute().get("files", [])
    if items:
        return items[0]["id"]
    folder = service.files().create(
        body={"name": month_name,
              "mimeType": "application/vnd.google-apps.folder",
              "parents": [parent_id]},
        fields="id").execute()
    return folder["id"]

def upload_to_drive(filename, parent_folder_id, pin_message=False):
    try:
        service   = get_drive_service()
        folder_id = get_month_folder(service, parent_folder_id)
        meta      = {"name": os.path.basename(filename), "parents": [folder_id]}
        media     = MediaFileUpload(filename, resumable=True)
        f         = service.files().create(body=meta, media_body=media,
                                            fields="id,webViewLink").execute()
        link = f.get("webViewLink", "no-link")
        msg  = f"✅ Uploaded: {os.path.basename(filename)}\n🔗 {link}"
        if pin_message:
            msg = "📌 [PRIORITY] " + msg
        send_telegram(msg, pin=pin_message)
        print(f"📤 {filename} → {link}")
    except Exception as e:
        send_telegram(f"❌ Upload failed: {e}")
        print(f"❌ Upload error: {e}")


# ═══════════════════════════════════════════════════════════════
#  MEDIA — Photo
# Confirmed: -input_format mjpeg + -update 1 required on ffmpeg 7.x
# ═══════════════════════════════════════════════════════════════

def take_photo_and_upload():
    ts     = datetime.datetime.now().strftime("%m%d_%H%M%S")
    prefix = f"{current_subject}_" if current_subject else ""
    fname  = f"{prefix}photo_{ts}.jpg"
    
    # Restored: CPU-blended computational photography via fswebcam
    cmd = [
        "fswebcam",
        "-d", KERO_VIDEO_DEVICE,
        "-r", f"{KERO_WIDTH}x{KERO_HEIGHT}",
        "-D", "1",             # Delay to let USB settle
        "-S", "30",            # Skip frames to allow auto-exposure
        "-F", "5",             # Average 5 frames to crush noise
        "--no-banner",         
        "--jpeg", "100",       # Max quality (5MB+ files)
        fname
    ]
    try:
        # Run command and capture error output
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if not os.path.exists(fname):
            raise RuntimeError(f"fswebcam failed:\n{result.stderr}")
            
        msg = f" Photo saved: {fname}"
        print(msg)
        log_activity("photo")
        # Upload in the background so the Pi doesn't freeze
        threading.Thread(target=upload_to_drive, args=(fname, FOLDER_ID), daemon=True).start()
        return msg
        
    except Exception as e:
        msg = f"❌ Photo failed: {e}"
        print(msg)
        send_telegram(msg)
        return msg


# ═══════════════════════════════════════════════════════════════
#  MEDIA — Video + Audio
# Confirmed: -thread_queue_size 1024 prevents A/V sync issues
# Video: 1080p x264 ultrafast (Pi 5 can encode this in real time)
# Audio: AAC 128k from Kero built-in mic
# ═══════════════════════════════════════════════════════════════

def _build_video_cmd(filename):
    return [
        FFMPEG_BIN, "-y",
        # Video source — MJPEG required for smooth capture
        "-thread_queue_size", "1024",
        "-f", "v4l2",
        "-input_format", KERO_INPUT_FORMAT,
        "-video_size", "1920x1080",    # Record at 1080p — Pi encodes this in real time
        "-framerate", str(KERO_FPS),
        "-i", KERO_VIDEO_DEVICE,
        # Audio source — confirmed working device
        "-thread_queue_size", "1024",
        "-f", "alsa",
        "-ar", "48000",
        "-ac", "2",
        "-i", KERO_AUDIO_DEVICE,
        # Encoding
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
        "-c:a", "aac", "-b:a", "128k",
        filename
    ]

def start_video_audio():
    global ffmpeg_proc, recording, raw_filename
    ts           = datetime.datetime.now().strftime("%m%d_%H%M")
    prefix       = f"{current_subject}_" if current_subject else ""
    raw_filename = f"{prefix}video_{ts}.mp4"
    cmd          = _build_video_cmd(raw_filename)
    print(f"▶️  Video cmd: {' '.join(cmd)}")
    try:
        ffmpeg_proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL)
        recording   = True
        log_activity("video_start")
        sub_msg     = f" [{current_subject}]" if current_subject else ""
        msg         = f"🎥 Recording started{sub_msg} → {raw_filename}"
        send_telegram(msg)
        return msg
    except Exception as e:
        msg = f"❌ Video start failed: {e}"
        print(msg); send_telegram(msg)
        recording = False; ffmpeg_proc = None
        return msg

def stop_video_audio():
    global ffmpeg_proc, recording, raw_filename
    if not (ffmpeg_proc and recording):
        return "⚠️  No active video recording."
    try:
        ffmpeg_proc.stdin.write(b"q\n")
        ffmpeg_proc.stdin.flush()
        ffmpeg_proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        ffmpeg_proc.kill()
    except Exception as e:
        print(f"⚠️  Stop video: {e}")
    finally:
        recording = False; ffmpeg_proc = None
    fname        = raw_filename
    raw_filename = None
    if fname and os.path.exists(fname):
        threading.Thread(target=upload_to_drive,
                         args=(fname, FOLDER_ID), daemon=True).start()
        msg = f"🛑 Video stopped → uploading {fname}"
    else:
        msg = "🛑 Video stopped (no file)"
    send_telegram(msg)
    return msg


# ═══════════════════════════════════════════════════════════════
#  MEDIA — Audio Only
# ═══════════════════════════════════════════════════════════════

def _build_audio_cmd(filename):
    return [
        FFMPEG_BIN, "-y",
        "-f", "alsa",
        "-ar", "48000",
        "-ac", "2",
        "-i", KERO_AUDIO_DEVICE,
        "-c:a", "aac", "-b:a", "256k",
        filename
    ]

def start_audio_only(priority=False):
    global audio_proc, audio_recording, audio_filename, audio_is_priority
    audio_is_priority = priority
    ts             = datetime.datetime.now().strftime("%m%d_%H%M")
    prefix         = f"{current_subject}_" if current_subject else ""
    audio_filename = f"{prefix}{'PRIORITY_' if priority else ''}audio_{ts}.m4a"
    cmd            = _build_audio_cmd(audio_filename)
    print(f"▶️  Audio cmd: {' '.join(cmd)}")
    try:
        audio_proc      = subprocess.Popen(cmd, stderr=subprocess.DEVNULL)
        audio_recording = True
        log_activity("audio_start")
        icon            = "🚨" if priority else "🎙️"
        sub_msg         = f" [{current_subject}]" if current_subject else ""
        msg             = f"{icon} Audio started{sub_msg} → {audio_filename}"
        send_telegram(msg)
        return msg
    except Exception as e:
        msg = f"❌ Audio start failed: {e}"
        print(msg); send_telegram(msg)
        audio_recording = False; audio_proc = None; audio_is_priority = False
        return msg

def stop_audio_only():
    global audio_proc, audio_recording, audio_filename, audio_is_priority
    if not audio_recording:
        return "⚠️  No active audio recording."
    try:
        if audio_proc and audio_proc.poll() is None:
            audio_proc.send_signal(signal.SIGINT)
            try:    audio_proc.wait(timeout=10)
            except subprocess.TimeoutExpired: audio_proc.kill()
    except Exception as e:
        print(f"⚠️  Stop audio: {e}")
    finally:
        audio_recording = False; audio_proc = None
    fname          = audio_filename
    audio_filename = None
    was_priority   = audio_is_priority
    audio_is_priority = False
    if fname and os.path.exists(fname):
        threading.Thread(target=upload_to_drive,
                         args=(fname, FOLDER_ID, was_priority), daemon=True).start()
        msg = f"🛑 Audio stopped → uploading {fname}"
    else:
        msg = "🛑 Audio stopped (no file)"
    send_telegram(msg)
    return msg


# ═══════════════════════════════════════════════════════════════
#  STATS / STATUS / SYSTEM
# ═══════════════════════════════════════════════════════════════

def get_storage_usage():
    u = shutil.disk_usage("/")
    return (round(u.used/u.total*100, 1),
            round(u.free/(1024**3), 2),
            round(u.total/(1024**3), 2))

def get_uptime():
    secs   = int(time.time() - psutil.boot_time())
    h, rem = divmod(secs, 3600)
    m      = rem // 60
    return f"{h}h {m}m"

def send_stats_report():
    cpu                     = psutil.cpu_percent(interval=1)
    ram                     = psutil.virtual_memory().percent
    used_pct, free_gb, _    = get_storage_usage()
    photo_count             = len([f for f in os.listdir() if "photo_" in f])
    video_count             = len([f for f in os.listdir() if "video_" in f])
    audio_count             = len([f for f in os.listdir() if "audio_" in f])
    cam_ok                  = os.path.exists(KERO_VIDEO_DEVICE)
    return (
        f"📊 Veronica Stats\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"📝 Subject : {current_subject or 'None'}\n"
        f"⏱️  Uptime  : {get_uptime()}\n"
        f"🖥️  CPU     : {cpu}%\n"
        f"🧠 RAM     : {ram}%\n"
        f"💾 Storage : {used_pct}% · {free_gb} GB free\n"
        f"📸 Photos  : {photo_count}\n"
        f"🎥 Videos  : {video_count}\n"
        f"🎙️  Audios  : {audio_count}\n"
        f"📷 Camera  : {'✅' if cam_ok else '❌'}\n"
        f"🎬 Mode    : {'Video' if recording else 'Audio' if audio_recording else 'Idle'}"
    )

def report_status():
    if recording:
        send_telegram(f"🎬 Recording video → {raw_filename}")
    elif audio_recording:
        send_telegram(f"🎙️  Recording audio → {audio_filename}")
    else:
        send_telegram("🟢 Idle.")

def reboot_system():
    send_telegram("🔁 Rebooting…")
    time.sleep(1)
    subprocess.Popen(["sudo", "reboot"])

def shutdown_system():
    send_telegram("🛑 Shutting down…")
    time.sleep(1)
    subprocess.Popen(["sudo", "poweroff"])


# ═══════════════════════════════════════════════════════════════
#  WATCHDOG
# ═══════════════════════════════════════════════════════════════

def watchdog_loop():
    while True:
        if recording and (ffmpeg_proc is None or ffmpeg_proc.poll() is not None):
            send_telegram("🛡️  Watchdog: video crashed — restarting…")
            start_video_audio()
        elif audio_recording and (audio_proc is None or audio_proc.poll() is not None):
            send_telegram("🛡️  Watchdog: audio crashed — restarting…")
            start_audio_only()
        time.sleep(10)


# ═══════════════════════════════════════════════════════════════
#  KEY HANDLER
# ═══════════════════════════════════════════════════════════════

def handle_key(key_num, buzzer):
    global current_subject, secure_target_action, secure_current_step, secure_timer

    # ── Security passcode interceptor ──────────────────────────
    if secure_target_action:
        if time.time() - secure_timer > 10:
            secure_target_action = None
            secure_current_step  = 0
            buzzer.beep(3)
            print("⏳ Passcode timed out.")
            return
        if key_num == SECURE_CODE_SEQ[secure_current_step]:
            secure_current_step += 1
            buzzer.beep(1, 0.05)
            if secure_current_step == len(SECURE_CODE_SEQ):
                buzzer.beep(2)
                print(f"✅ Passcode accepted → {secure_target_action}")
                if secure_target_action == "SHUTDOWN": shutdown_system()
                elif secure_target_action == "RESTART": reboot_system()
                secure_target_action = None
                secure_current_step  = 0
        else:
            secure_target_action = None
            secure_current_step  = 0
            buzzer.beep(3)
            print("❌ Wrong passcode.")
        return   # always eat keypress during passcode entry

    # ── Subject key ────────────────────────────────────────────
    if key_num in SUBJECT_KEYS:
        current_subject = SUBJECT_KEYS[key_num]
        print(f"👆 Key {key_num} → Subject: {current_subject}")
        log_activity("subject_change")
        buzzer.beep(2)
        send_telegram(f"📘 Subject: {current_subject}")
        return

    # ── Mode key ───────────────────────────────────────────────
    if key_num not in MODE_KEYS:
        print(f"ℹ️  Key {key_num} not mapped")
        return

    action = MODE_KEYS[key_num]
    print(f"👆 Key {key_num} → {action}")

    if action == "PHOTO":
        buzzer.beep(1)
        threading.Thread(target=take_photo_and_upload, daemon=True).start()

    elif action == "VIDEO_TOGGLE":
        if not recording:   start_video_audio();  buzzer.beep(1)
        else:               stop_video_audio();   buzzer.beep(2)

    elif action == "AUDIO_TOGGLE":
        if not audio_recording: start_audio_only();  buzzer.beep(1)
        else:                   stop_audio_only();   buzzer.beep(2)

    elif action == "PRIORITY_AUDIO_TOGGLE":
        if not audio_recording: start_audio_only(priority=True); buzzer.beep(1)
        else:                   stop_audio_only();               buzzer.beep(2)

    elif action == "STOP":
        if recording:           stop_video_audio(); buzzer.beep(2)
        elif audio_recording:   stop_audio_only();  buzzer.beep(2)
        else:                   print("ℹ️  Nothing to stop")

    elif action == "STATS":
        send_telegram(send_stats_report()); buzzer.beep(1)

    elif action == "CLEAR_SUBJECT":
        current_subject = None
        buzzer.beep(1)
        send_telegram("⚪ Subject cleared.")

    elif action == "SECURE_SHUTDOWN":
        secure_target_action = "SHUTDOWN"
        secure_current_step  = 0
        secure_timer         = time.time()
        buzzer.beep(1)
        print("🔒 Enter passcode for SHUTDOWN…")

    elif action == "SECURE_RESTART":
        secure_target_action = "RESTART"
        secure_current_step  = 0
        secure_timer         = time.time()
        buzzer.beep(1)
        print("🔒 Enter passcode for RESTART…")


# ═══════════════════════════════════════════════════════════════
#  FLASK WEB DASHBOARD
# ═══════════════════════════════════════════════════════════════

@app.route("/")
def dashboard():
    with state_lock:
        status_text = "System Idle"
        status_color = "#3fb950" 
        pulse_css = ""
        
        if recording: 
            status_text = "LIVE: Video Feed Active"
            status_color = "#ff4b82" 
            pulse_css = "animation: pulse-red 2s infinite;"
        elif audio_recording: 
            status_text = "LIVE: Audio Feed Active"
            status_color = "#f1fa8c" 
            pulse_css = "animation: pulse-yellow 2s infinite;"
            
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        used_pct, free_gb2, total_gb = get_storage_usage()
        
        # FIX: Look for the word anywhere in the file name so subject prefixes don't hide them
        photo_files = sorted([f for f in os.listdir() if "photo_" in f], reverse=True)
        video_files = sorted([f for f in os.listdir() if "video_" in f], reverse=True)
        audio_files = sorted([f for f in os.listdir() if "audio_" in f], reverse=True)

        last_photo = photo_files[0] if photo_files else "No assets detected"
        last_video = video_files[0] if video_files else "No assets detected"
        last_audio = audio_files[0] if audio_files else "No assets detected"
        
        uptime_str = get_uptime()
        hostname = socket.gethostname()
        active_subj = current_subject if current_subject else "Unassigned"

        # Pass recording states to Javascript
        is_rec_js = "true" if (recording or audio_recording) else "false"
        is_vid_js = "true" if recording else "false"

        return f"""
        <!doctype html>
        <html lang="en">
        <head>
            <meta charset="utf-8"/>
            <meta name="viewport" content="width=device-width, initial-scale=1"/>
            <title>Veronica Command Center</title>
            <style>
                @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
                
                :root {{ 
                    --bg-dark: #05070a;
                    --glass-bg: linear-gradient(145deg, rgba(20, 24, 32, 0.5) 0%, rgba(13, 16, 22, 0.7) 100%);
                    --glass-border: rgba(255, 255, 255, 0.08);
                    --glass-edge-top: rgba(255, 255, 255, 0.15);
                    --glass-edge-left: rgba(255, 255, 255, 0.05);
                    --neon-cyan: #7cd0ff;
                    --text-main: #f0f6fc;
                    --text-muted: #8b949e;
                }}
                
                * {{ box-sizing: border-box; margin: 0; padding: 0; }}
                
                body {{ 
                    font-family: 'Inter', sans-serif; 
                    color: var(--text-main); 
                    background-color: var(--bg-dark);
                    background-image: linear-gradient(rgba(255, 255, 255, 0.015) 1px, transparent 1px), linear-gradient(90deg, rgba(255, 255, 255, 0.015) 1px, transparent 1px);
                    background-size: 50px 50px;
                    min-height: 100vh; display: flex; flex-direction: column; overflow-x: hidden;
                    letter-spacing: -0.2px;
                }}
                
                /* AMBIENT ORBS */
                .ambient-orb {{ position: fixed; border-radius: 50%; filter: blur(140px); z-index: -1; pointer-events: none; opacity: 0.45; animation: breathe 15s infinite alternate ease-in-out; }}
                @keyframes breathe {{ 0% {{ transform: scale(1); opacity: 0.3; }} 100% {{ transform: scale(1.1) translate(30px, -30px); opacity: 0.5; }} }}
                .orb-1 {{ top: -10%; left: -5%; width: 50vw; height: 50vw; background: rgba(88, 166, 255, 0.2); }}
                .orb-2 {{ bottom: -20%; right: -10%; width: 60vw; height: 60vw; background: rgba(162, 119, 255, 0.15); animation-delay: -7s; }}
                .orb-3 {{ top: 40%; left: 40%; width: 30vw; height: 30vw; background: rgba(0, 242, 254, 0.1); }}

                @keyframes pulse-red {{ 0% {{ box-shadow: 0 0 10px #ff4b82; }} 50% {{ box-shadow: 0 0 25px #ff4b82; }} 100% {{ box-shadow: 0 0 10px #ff4b82; }} }}
                @keyframes pulse-yellow {{ 0% {{ box-shadow: 0 0 10px #f1fa8c; }} 50% {{ box-shadow: 0 0 25px #f1fa8c; }} 100% {{ box-shadow: 0 0 10px #f1fa8c; }} }}

                /* 🔴 GIANT RECORDING OVERLAY */
                .recording-overlay {{
                    position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
                    background: rgba(5, 7, 10, 0.6); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
                    z-index: 9999; display: flex; flex-direction: column; justify-content: center; align-items: center;
                    opacity: 0; pointer-events: none; transition: opacity 0.4s ease;
                }}
                .recording-overlay.active {{ opacity: 1; pointer-events: all; }}
                
                .overlay-label {{ font-size: 28px; font-weight: 700; letter-spacing: 6px; margin-bottom: 10px; text-transform: uppercase; animation: pulse-opacity 2s infinite; }}
                @keyframes pulse-opacity {{ 0% {{ opacity: 0.6; }} 50% {{ opacity: 1; }} 100% {{ opacity: 0.6; }} }}
                
                .timer-text {{
                    font-size: 160px; font-weight: 700; font-variant-numeric: tabular-nums;
                    letter-spacing: -4px; margin-bottom: 50px; line-height: 1;
                }}
                
                .terminate-btn {{
                    background: transparent; border: 3px solid; border-radius: 20px;
                    font-size: 24px; font-weight: 700; padding: 25px 60px; cursor: pointer;
                    text-transform: uppercase; letter-spacing: 2px; transition: all 0.3s cubic-bezier(0.2, 0.8, 0.2, 1);
                }}
                .terminate-btn:hover {{ transform: scale(1.05); color: #fff !important; }}
                
                /* TOP NAVIGATION */
                .topbar-wrapper {{ padding: 24px 32px 0 32px; position: sticky; top: 0; z-index: 100; }}
                .topbar {{ max-width: 1400px; margin: 0 auto; display: flex; align-items: center; justify-content: space-between; gap: 16px; }}
                .glass-pill {{
                    display: flex; align-items: center; gap: 10px; font-size: 13px; font-weight: 600;
                    background: rgba(10, 12, 16, 0.6); backdrop-filter: blur(40px) saturate(200%); -webkit-backdrop-filter: blur(40px) saturate(200%);
                    padding: 10px 20px; border-radius: 30px; border: 1px solid var(--glass-border); border-top: 1px solid var(--glass-edge-top);
                    box-shadow: 0 15px 35px rgba(0,0,0,0.5);
                }}
                .status-dot {{ width: 10px; height: 10px; background-color: {status_color}; border-radius: 50%; box-shadow: 0 0 12px {status_color}; {pulse_css} }}

                /* 3-COLUMN LAYOUT */
                .container {{ max-width: 1400px; margin: 0 auto; padding: 32px; width: 100%; flex-grow: 1; display: grid; grid-template-columns: 300px 1fr 320px; gap: 28px; align-items: start; }}
                @media (max-width: 1100px) {{ .container {{ grid-template-columns: 1fr 1fr; }} }}
                @media (max-width: 800px) {{ .container {{ grid-template-columns: 1fr; padding: 20px; }} }}
                .column-stack {{ display: flex; flex-direction: column; gap: 28px; }}

                /* CARDS */
                .card {{
                    background: var(--glass-bg); backdrop-filter: blur(40px) saturate(200%); -webkit-backdrop-filter: blur(40px) saturate(200%);
                    border: 1px solid var(--glass-border); border-top: 1px solid var(--glass-edge-top); border-left: 1px solid var(--glass-edge-left);
                    border-radius: 20px; box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.6); overflow: hidden;
                }}
                .card-header {{ display: flex; justify-content: space-between; align-items: center; padding: 18px 24px; border-bottom: 1px solid rgba(255,255,255,0.03); background: rgba(0,0,0,0.2); }}
                .card-title {{ display: flex; align-items: center; gap: 10px; font-weight: 600; font-size: 13px; text-transform: uppercase; letter-spacing: 1px; color: var(--neon-cyan); }}
                .card-body {{ padding: 24px; }}

                /* CALENDAR & CLOCK */
                .clock-display {{ font-size: 36px; font-weight: 700; letter-spacing: -1px; margin-bottom: 4px; color: #fff; text-shadow: 0 0 20px rgba(255,255,255,0.3); }}
                .date-display {{ font-size: 13px; color: var(--neon-cyan); font-weight: 600; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 24px; }}
                
                .cal-grid {{ display: grid; grid-template-columns: repeat(7, 1fr); gap: 6px; text-align: center; font-size: 12px; font-weight: 500; }}
                .cal-header {{ color: var(--text-muted); font-size: 10px; font-weight: 700; padding-bottom: 8px; border-bottom: 1px solid rgba(255,255,255,0.05); margin-bottom: 4px; }}
                .cal-day {{ padding: 6px 0; border-radius: 6px; color: var(--text-muted); transition: all 0.2s; }}
                .cal-day:hover {{ background: rgba(255,255,255,0.1); color: #fff; }}
                .cal-today {{ background: var(--neon-cyan); color: #000; font-weight: 700; box-shadow: 0 0 10px var(--neon-cyan); }}
                .cal-today:hover {{ background: #fff; color: #000; }}

                /* UPLINK GRID (QUICK LINKS) */
                .uplink-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
                .uplink-btn {{
                    background: rgba(0,0,0,0.2); border: 1px solid var(--glass-border); border-radius: 14px;
                    padding: 16px 12px; display: flex; flex-direction: column; align-items: center; gap: 8px;
                    cursor: pointer; transition: all 0.3s cubic-bezier(0.2, 0.8, 0.2, 1);
                    text-decoration: none; color: var(--text-main); font-size: 12px; font-weight: 600;
                }}
                .uplink-icon {{ width: 24px; height: 24px; stroke: var(--text-muted); fill: none; stroke-width: 2; transition: all 0.3s; }}
                
                .uplink-yt:hover {{ border-color: #ff0000; box-shadow: 0 10px 20px rgba(255,0,0,0.2); background: rgba(50,10,10,0.6); transform: translateY(-3px); }}
                .uplink-yt:hover .uplink-icon {{ stroke: #ff0000; }}
                
                .uplink-google:hover {{ border-color: #4285f4; box-shadow: 0 10px 20px rgba(66,133,244,0.2); background: rgba(10,25,50,0.6); transform: translateY(-3px); }}
                .uplink-google:hover .uplink-icon {{ stroke: #4285f4; }}
                
                .uplink-gemini:hover {{ border-color: #a277ff; box-shadow: 0 10px 20px rgba(162,119,255,0.2); background: rgba(30,15,50,0.6); transform: translateY(-3px); }}
                .uplink-gemini:hover .uplink-icon {{ stroke: #a277ff; }}
                
                .uplink-chrome:hover {{ border-color: #3fb950; box-shadow: 0 10px 20px rgba(63,185,80,0.2); background: rgba(10,40,15,0.6); transform: translateY(-3px); }}
                .uplink-chrome:hover .uplink-icon {{ stroke: #3fb950; }}

                /* SUBJECT SELECTOR */
                .subject-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }}
                .subj-btn {{
                    background: rgba(0,0,0,0.2); border: 1px solid rgba(255,255,255,0.06); border-radius: 12px;
                    padding: 14px 8px; color: var(--text-muted); font-size: 12px; font-weight: 600; cursor: pointer; 
                    transition: all 0.3s cubic-bezier(0.2, 0.8, 0.2, 1);
                }}
                
                .subj-physics:hover {{ border-color: #a277ff; color: #a277ff; box-shadow: 0 8px 15px rgba(162,119,255,0.2); transform: translateY(-3px); background: rgba(162,119,255,0.1); }}
                .subj-chemistry:hover {{ border-color: #7cd0ff; color: #7cd0ff; box-shadow: 0 8px 15px rgba(124,208,255,0.2); transform: translateY(-3px); background: rgba(124,208,255,0.1); }}
                .subj-math:hover {{ border-color: #58a6ff; color: #58a6ff; box-shadow: 0 8px 15px rgba(88,166,255,0.2); transform: translateY(-3px); background: rgba(88,166,255,0.1); }}
                .subj-english:hover {{ border-color: #ff9e64; color: #ff9e64; box-shadow: 0 8px 15px rgba(255,158,100,0.2); transform: translateY(-3px); background: rgba(255,158,100,0.1); }}
                .subj-comp:hover {{ border-color: #9ece6a; color: #9ece6a; box-shadow: 0 8px 15px rgba(158,206,106,0.2); transform: translateY(-3px); background: rgba(158,206,106,0.1); }}
                .subj-clear:hover {{ border-color: #ff5555; color: #ff5555; box-shadow: 0 8px 15px rgba(255,85,85,0.2); transform: translateY(-3px); background: rgba(255,85,85,0.1); }}
                
                .subj-active {{ background: rgba(255,255,255,0.1); color: #fff; border-color: #fff; box-shadow: 0 0 15px rgba(255,255,255,0.1); }}

                /* TACTICAL ACTION BUTTONS */
                .actions-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }}
                .action-btn {{
                    background: linear-gradient(180deg, rgba(40, 46, 56, 0.5) 0%, rgba(25, 30, 38, 0.5) 100%);
                    border: 1px solid var(--glass-border); border-top: 1px solid var(--glass-edge-top); border-radius: 16px; 
                    padding: 20px 16px; color: var(--text-main); cursor: pointer;
                    display: flex; flex-direction: column; align-items: flex-start; gap: 16px;
                    transition: all 0.3s cubic-bezier(0.2, 0.8, 0.2, 1); box-shadow: 0 8px 20px rgba(0,0,0,0.2);
                }}
                
                .btn-icon-svg {{ width: 24px; height: 24px; stroke: var(--text-muted); transition: all 0.3s; fill: none; }}
                .btn-text {{ font-size: 13px; font-weight: 600; text-align: left; line-height: 1.4; transition: color 0.3s; }}
                
                .btn-photo:hover {{ border-color: #a277ff; box-shadow: 0 12px 25px rgba(162, 119, 255, 0.25); transform: translateY(-4px); background: rgba(50, 40, 70, 0.7); }}
                .btn-photo:hover .btn-icon-svg {{ stroke: #a277ff; filter: drop-shadow(0 0 8px #a277ff); }}
                .btn-photo:hover .btn-text {{ color: #a277ff; }}
                
                .btn-video:hover {{ border-color: #ff4b82; box-shadow: 0 12px 25px rgba(255, 75, 130, 0.25); transform: translateY(-4px); background: rgba(70, 30, 50, 0.7); }}
                .btn-video:hover .btn-icon-svg {{ stroke: #ff4b82; filter: drop-shadow(0 0 8px #ff4b82); }}
                .btn-video:hover .btn-text {{ color: #ff4b82; }}
                
                .btn-audio:hover {{ border-color: #f1fa8c; box-shadow: 0 12px 25px rgba(241, 250, 140, 0.2); transform: translateY(-4px); background: rgba(60, 60, 30, 0.7); }}
                .btn-audio:hover .btn-icon-svg {{ stroke: #f1fa8c; filter: drop-shadow(0 0 8px #f1fa8c); }}
                .btn-audio:hover .btn-text {{ color: #f1fa8c; }}
                
                .btn-stop:hover {{ border-color: #ffffff; box-shadow: 0 12px 25px rgba(255, 255, 255, 0.2); transform: translateY(-4px); background: rgba(70, 75, 85, 0.7); }}
                .btn-stop:hover .btn-icon-svg {{ stroke: #ffffff; filter: drop-shadow(0 0 8px #ffffff); }}
                .btn-stop:hover .btn-text {{ color: #ffffff; }}
                
                .btn-stats:hover {{ border-color: #8be9fd; box-shadow: 0 12px 25px rgba(139, 233, 253, 0.25); transform: translateY(-4px); background: rgba(30, 60, 70, 0.7); }}
                .btn-stats:hover .btn-icon-svg {{ stroke: #8be9fd; filter: drop-shadow(0 0 8px #8be9fd); }}
                .btn-stats:hover .btn-text {{ color: #8be9fd; }}
                
                .btn-reboot {{ border-color: rgba(255, 85, 85, 0.3); }}
                .btn-reboot .btn-icon-svg {{ stroke: #ff5555; }}
                .btn-reboot:hover {{ border-color: #ff5555; box-shadow: 0 12px 25px rgba(255, 85, 85, 0.35); transform: translateY(-4px); background: rgba(90, 25, 25, 0.7); }}
                .btn-reboot:hover .btn-icon-svg {{ filter: drop-shadow(0 0 8px #ff5555); }}
                .btn-reboot:hover .btn-text {{ color: #ff5555; }}
                
                .action-btn:active {{ transform: translateY(0) scale(0.98); }}

                /* SYSTEM OVERSEER */
                .sys-row {{ display: flex; justify-content: space-between; align-items: center; padding: 12px 0; border-bottom: 1px dashed rgba(255,255,255,0.06); font-size: 13px; }}
                .sys-row:last-child {{ border-bottom: none; }}
                .sys-label {{ color: var(--text-muted); display: flex; align-items: center; gap: 8px; font-weight: 500; }}
                .sys-tag {{ display: flex; align-items: center; gap: 6px; font-family: monospace; font-size: 11px; background: rgba(63, 185, 80, 0.1); color: #3fb950; padding: 4px 8px; border-radius: 6px; border: 1px solid rgba(63, 185, 80, 0.3); letter-spacing: 0.5px; }}
                .sys-tag-warn {{ background: rgba(241, 250, 140, 0.1); color: #f1fa8c; border: 1px solid rgba(241, 250, 140, 0.3); }}
                .sys-icon {{ width: 14px; height: 14px; stroke: currentColor; fill: none; stroke-width: 2; }}

                /* KEY-VALUE ROWS & BARS */
                .kv-row {{ display: flex; justify-content: space-between; align-items: center; padding: 12px 0; font-size: 13px; }}
                .kv-row.dashed {{ border-bottom: 1px dashed rgba(255,255,255,0.06); }}
                .kv-row:last-child {{ border-bottom: none; }}
                .kv-label {{ color: var(--text-muted); font-weight: 500; }}
                .kv-value {{ font-weight: 600; font-family: monospace; font-size: 12px; }}

                .progress-track {{ width: 100%; height: 6px; background: rgba(0, 0, 0, 0.6); border-radius: 10px; overflow: hidden; margin: 16px 0 10px 0; box-shadow: inset 0 1px 3px rgba(0,0,0,0.5); }}
                .progress-fill {{ height: 100%; width: {used_pct}%; background: linear-gradient(90deg, #00f2fe, var(--neon-cyan)); border-radius: 10px; box-shadow: 0 0 15px rgba(124, 208, 255, 0.6); }}
                
                /* SVG ICONS FOR TITLES */
                .title-icon {{ width: 18px; height: 18px; stroke: currentColor; fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }}
            </style>
        </head>
        <body>
            <div class="recording-overlay" id="rec-overlay">
                <div class="overlay-label" id="rec-label">🔴 LIVE RECORDING</div>
                <div class="timer-text" id="rec-timer">00:00</div>
                <button class="terminate-btn" id="rec-btn" onclick="post('stop')">TERMINATE SESSION</button>
            </div>

            <div class="ambient-orb orb-1"></div>
            <div class="ambient-orb orb-2"></div>
            <div class="ambient-orb orb-3"></div>
            
            <div class="topbar-wrapper">
                <div class="topbar">
                    <div class="glass-pill"><div style="color:var(--neon-cyan)">✦</div> Veronica Core <span style="color:var(--text-muted);font-weight:400;margin-left:6px;">{hostname}.local</span></div>
                    <div class="glass-pill"><div class="status-dot"></div> {status_text}</div>
                </div>
            </div>

            <div class="container">
                
                <div class="column-stack">
                    <div class="card">
                        <div class="card-body">
                            <div class="clock-display" id="clock">00:00:00</div>
                            <div class="date-display" id="date">Loading Temporal Data...</div>
                            <div class="cal-grid" id="calendar">
                                </div>
                        </div>
                    </div>

                    <div class="card">
                        <div class="card-header"><div class="card-title"><svg class="title-icon"><path d="M22 12h-4l-3 9L9 3l-3 9H2"></path></svg> Uplink Grid</div></div>
                        <div class="card-body">
                            <div class="uplink-grid">
                                <a href="https://www.google.com" target="_blank" class="uplink-btn uplink-google">
                                    <svg class="uplink-icon" viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
                                    Google
                                </a>
                                <a href="https://www.youtube.com" target="_blank" class="uplink-btn uplink-yt">
                                    <svg class="uplink-icon" viewBox="0 0 24 24"><path d="M22.54 6.42a2.78 2.78 0 0 0-1.94-2C18.88 4 12 4 12 4s-6.88 0-8.6.46a2.78 2.78 0 0 0-1.94 2A29 29 0 0 0 1 11.75a29 29 0 0 0 .46 5.33 2.78 2.78 0 0 0 1.94 2c1.72.46 8.6.46 8.6.46s6.88 0 8.6-.46a2.78 2.78 0 0 0 1.94-2 29 29 0 0 0 .46-5.33 29 29 0 0 0-.46-5.33z"></path><polygon points="9.75 15.02 15.5 11.75 9.75 8.48 9.75 15.02"></polygon></svg>
                                    YouTube
                                </a>
                                <a href="https://gemini.google.com" target="_blank" class="uplink-btn uplink-gemini">
                                    <svg class="uplink-icon" viewBox="0 0 24 24"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"></path></svg>
                                    Gemini AI
                                </a>
                                <div onclick="post('open_chrome')" class="uplink-btn uplink-chrome">
                                    <svg class="uplink-icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><circle cx="12" cy="12" r="4"></circle><line x1="21.17" y1="8" x2="12" y2="8"></line><line x1="3.95" y1="6.06" x2="8.54" y2="14"></line><line x1="10.88" y1="21.94" x2="15.46" y2="14"></line></svg>
                                    Display UI
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="column-stack">
                    <div class="card">
                        <div class="card-header"><div class="card-title"><svg class="title-icon"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg> Subject Context</div></div>
                        <div class="card-body">
                            <div class="subject-grid">
                                <button class="subj-btn subj-physics {'subj-active' if active_subj=='Physics' else ''}" onclick="post('subj_physics')">Physics</button>
                                <button class="subj-btn subj-chemistry {'subj-active' if active_subj=='Chemistry' else ''}" onclick="post('subj_chemistry')">Chemistry</button>
                                <button class="subj-btn subj-math {'subj-active' if active_subj=='Math' else ''}" onclick="post('subj_math')">Math</button>
                                <button class="subj-btn subj-english {'subj-active' if active_subj=='English' else ''}" onclick="post('subj_english')">English</button>
                                <button class="subj-btn subj-comp {'subj-active' if active_subj=='Computer Science' else ''}" onclick="post('subj_computer science')">Comp Sci</button>
                                <button class="subj-btn subj-clear" onclick="post('subj_clear')">Clear Context</button>
                            </div>
                            <div style="margin-top: 16px; font-size: 12px; color: var(--text-muted); text-align: center;">
                                Current Focus: <span style="color:#fff; font-weight:600;">{active_subj}</span>
                            </div>
                        </div>
                    </div>

                    <div class="card">
                        <div class="card-header"><div class="card-title"><svg class="title-icon"><circle cx="12" cy="12" r="10"></circle><circle cx="12" cy="12" r="6"></circle><circle cx="12" cy="12" r="2"></circle></svg> Tactical Controls</div></div>
                        <div class="card-body">
                            <div class="actions-grid">
                                <button class="action-btn btn-photo" onclick="post('photo')">
                                    <svg class="btn-icon-svg" viewBox="0 0 24 24"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path><circle cx="12" cy="13" r="4"></circle></svg>
                                    <span class="btn-text">Engage<br>Optical Sensor</span>
                                </button>
                                <button class="action-btn btn-video" onclick="post('video')">
                                    <svg class="btn-icon-svg" viewBox="0 0 24 24"><polygon points="23 7 16 12 23 17 23 7"></polygon><rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect></svg>
                                    <span class="btn-text">Initialize<br>Video Feed</span>
                                </button>
                                <button class="action-btn btn-audio" onclick="post('audio')">
                                    <svg class="btn-icon-svg" viewBox="0 0 24 24"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path><path d="M19 10v2a7 7 0 0 1-14 0v-2"></path><line x1="12" y1="19" x2="12" y2="23"></line><line x1="8" y1="23" x2="16" y2="23"></line></svg>
                                    <span class="btn-text">Initialize<br>Audio Feed</span>
                                </button>
                                <button class="action-btn btn-stop" onclick="post('stop')">
                                    <svg class="btn-icon-svg" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect></svg>
                                    <span class="btn-text">Terminate<br>Active Feed</span>
                                </button>
                                <button class="action-btn btn-stats" onclick="post('stats')">
                                    <svg class="btn-icon-svg" viewBox="0 0 24 24"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>
                                    <span class="btn-text">Transmit<br>Sys Report</span>
                                </button>
                                <button class="action-btn btn-reboot" onclick="post('reboot')">
                                    <svg class="btn-icon-svg" viewBox="0 0 24 24"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>
                                    <span class="btn-text">Execute<br>System Reboot</span>
                                </button>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="column-stack">
                    <div class="card">
                        <div class="card-header"><div class="card-title"><svg class="title-icon"><line x1="18" y1="20" x2="18" y2="10"></line><line x1="12" y1="20" x2="12" y2="4"></line><line x1="6" y1="20" x2="6" y2="14"></line></svg> System Overseer</div></div>
                        <div class="card-body">
                            <div class="sys-row">
                                <span class="sys-label"><svg class="title-icon"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect><line x1="8" y1="21" x2="16" y2="21"></line><line x1="12" y1="17" x2="12" y2="21"></line></svg> Core Compute</span>
                                <span class="sys-tag"><svg class="sys-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"></polyline></svg> STABLE [{cpu}%]</span>
                            </div>
                            <div class="sys-row">
                                <span class="sys-label"><svg class="title-icon"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path><path d="M13.73 21a2 2 0 0 1-3.46 0"></path></svg> Memory Matrix</span>
                                <span class="sys-tag {'sys-tag-warn' if ram > 80 else ''}"><svg class="sys-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"></polyline></svg> NOMINAL [{ram}%]</span>
                            </div>
                            <div class="sys-row">
                                <span class="sys-label"><svg class="title-icon"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg> Hardware Subsystems</span>
                                <span class="sys-tag"><svg class="sys-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"></polyline></svg> ONLINE</span>
                            </div>
                        </div>
                    </div>

                    <div class="card">
                        <div class="card-header"><div class="card-title"><svg class="title-icon"><ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path></svg> Storage Drive</div></div>
                        <div class="card-body">
                            <div style="display: flex; justify-content: space-between; font-size: 13px; font-weight: 500;">
                                <span style="color:var(--text-muted)">Volume Used</span>
                                <span style="font-family:monospace;">{used_pct}%</span>
                            </div>
                            <div class="progress-track"><div class="progress-fill"></div></div>
                            <div style="color:var(--text-muted); font-size:12px; margin-top:10px; display:flex; justify-content: space-between;">
                                <span>Free: {free_gb2} GB</span>
                                <span>Total: {total_gb} GB</span>
                            </div>
                        </div>
                    </div>

                    <div class="card">
                        <div class="card-header"><div class="card-title"><svg class="title-icon"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg> Asset Ledger</div></div>
                        <div class="card-body">
                            <div class="kv-row dashed"><span class="kv-label">Latest Visual</span><span class="kv-value">{last_photo}</span></div>
                            <div class="kv-row dashed"><span class="kv-label">Latest Feed</span><span class="kv-value">{last_video}</span></div>
                            <div class="kv-row"><span class="kv-label">Latest Audio</span><span class="kv-value">{last_audio}</span></div>
                        </div>
                    </div>
                </div>

            </div>

            <script>
            // JS CALENDAR & CLOCK INJECTION
            function updateTime() {{
                const now = new Date();
                document.getElementById('clock').innerText = now.toLocaleTimeString('en-US', {{hour12: false}});
                document.getElementById('date').innerText = now.toLocaleDateString('en-US', {{ weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' }});
            }}
            setInterval(updateTime, 1000);
            updateTime();

            const cal = document.getElementById('calendar');
            let d = new Date(); d.setDate(1);
            let startDay = d.getDay();
            let daysInMonth = new Date(d.getFullYear(), d.getMonth()+1, 0).getDate();
            let html = '';
            const days = ['Su','Mo','Tu','We','Th','Fr','Sa'];
            days.forEach(day => html += `<div class="cal-header">${{day}}</div>`);
            for(let i=0; i<startDay; i++) html += `<div></div>`;
            for(let i=1; i<=daysInMonth; i++) {{
                let today = (i === new Date().getDate()) ? 'cal-today' : '';
                html += `<div class="cal-day ${{today}}">${{i}}</div>`;
            }}
            cal.innerHTML = html;

            function post(cmd) {{
                if (!cmd.startsWith("subj_") && cmd !== "open_chrome") {{
                    if (!confirm("Execute command: " + cmd.toUpperCase() + "?")) return;
                }}
                fetch("/trigger", {{ method: "POST", headers: {{ "Content-Type": "application/x-www-form-urlencoded" }}, body: "cmd=" + cmd }})
                .then(res => res.text()).then(msg => {{ 
                    if (!cmd.startsWith("subj_") && cmd !== "open_chrome") alert("✅ " + msg); 
                    location.reload(); 
                }})
                .catch(err => {{ alert("❌ " + err); }});
            }}
            
            // 🔴 GIANT OVERLAY TIMER LOGIC
            const isRecording = {is_rec_js};
            const isVideo = {is_vid_js};
            const overlay = document.getElementById('rec-overlay');
            const timerEl = document.getElementById('rec-timer');
            const labelEl = document.getElementById('rec-label');
            const btnEl = document.getElementById('rec-btn');

            if (isRecording) {{
                overlay.classList.add('active');
                
                // Color Code based on Audio vs Video
                if (isVideo) {{
                    timerEl.style.color = '#ff4b82';
                    timerEl.style.textShadow = '0 0 40px rgba(255, 75, 130, 0.5)';
                    labelEl.innerHTML = '<span style="color:#ff4b82;">●</span> LIVE VIDEO RECORDING';
                    btnEl.style.borderColor = '#ff4b82';
                    btnEl.style.color = '#ff4b82';
                    btnEl.style.background = 'rgba(255, 75, 130, 0.1)';
                }} else {{
                    timerEl.style.color = '#f1fa8c';
                    timerEl.style.textShadow = '0 0 40px rgba(241, 250, 140, 0.5)';
                    labelEl.innerHTML = '<span style="color:#f1fa8c;">●</span> LIVE AUDIO RECORDING';
                    btnEl.style.borderColor = '#f1fa8c';
                    btnEl.style.color = '#f1fa8c';
                    btnEl.style.background = 'rgba(241, 250, 140, 0.1)';
                }}

                // Save start time to local browser memory so it survives 10s refreshes
                if (!localStorage.getItem('rec_start')) {{
                    localStorage.setItem('rec_start', Date.now());
                }}
                
                const startTime = parseInt(localStorage.getItem('rec_start'));

                function updateRecTimer() {{
                    const diff = Math.floor((Date.now() - startTime) / 1000);
                    const m = String(Math.floor(diff / 60)).padStart(2, '0');
                    const s = String(diff % 60).padStart(2, '0');
                    timerEl.innerText = `${{m}}:${{s}}`;
                }}
                updateRecTimer();
                setInterval(updateRecTimer, 1000);
            }} else {{
                // Not recording, wipe the memory
                localStorage.removeItem('rec_start');
                overlay.classList.remove('active');
            }}

            setInterval(() => location.reload(), 10000);
            </script>
        </body>
        </html>
        """
        
@app.route("/trigger", methods=["POST"])
def trigger():
    global current_subject
    cmd = (flask_request.form.get("cmd") or "").strip().lower()
    
    if cmd.startswith("subj_"):
        sub = cmd.replace("subj_", "")
        current_subject = None if sub == "clear" else sub.title()
        if current_subject:
            log_activity("subject_change")
        return f"Subject updated to {current_subject}"
        
    if cmd == "open_chrome":
        subprocess.Popen("DISPLAY=:0 chromium-browser", shell=True)
        return "Chromium Browser launched on hardware display."
        
    if cmd == "photo": return take_photo_and_upload()
    elif cmd == "video": return start_video_audio()
    elif cmd == "audio": return start_audio_only()
    elif cmd == "stop":
        if recording:         return stop_video_audio()
        if audio_recording:   return stop_audio_only()
        return "Nothing to stop"
    elif cmd == "stats":
        return send_stats_report()
    elif cmd == "reboot":
        subprocess.Popen(["sudo", "reboot"])
        return "Reboot triggered"
    return f"Unknown: {cmd}"


@app.route("/report")
def report():
    """Principal's Activity Report — strictly per-subject tracking."""
    data     = _load_log()
    hostname = socket.gethostname()
    now_str  = datetime.datetime.now().strftime("%A, %d %B %Y  %H:%M")

    subject_cards_html = ""
    all_subjects = sorted(data.keys())

    if not all_subjects:
        subject_cards_html = """
        <div style="grid-column:1/-1;text-align:center;padding:60px;color:var(--text-muted);">
            No activity recorded yet. Start teaching!
        </div>"""
    else:
        for subj in all_subjects:
            s         = data[subj]
            t_photos  = s.get("total_photos", 0)
            t_videos  = s.get("total_videos", 0)
            t_audios  = s.get("total_audios", 0)
            
            # This is how many times the teacher selected the subject
            t_changes = s.get("subject_changes", 0) 

            # Calculate active days
            daily       = s.get("daily", {})
            days_active = len(daily)

            subject_cards_html += f"""
            <div class="card">
                <div class="card-header">
                    <div class="card-title">
                        <svg class="title-icon"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                        <polyline points="14 2 14 8 20 8"></polyline></svg>
                        {subj}
                    </div>
                    <span style="font-size:11px;color:var(--neon-cyan);font-family:monospace;">
                        {days_active} day(s) active
                    </span>
                </div>
                <div class="card-body">
                    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;text-align:center;">
                        <div style="background:rgba(162,119,255,0.1);border:1px solid rgba(162,119,255,0.3);border-radius:10px;padding:12px;">
                            <div style="font-size:22px;font-weight:700;color:#a277ff;">{t_photos}</div>
                            <div style="font-size:10px;color:var(--text-muted);margin-top:4px;">PHOTOS</div>
                        </div>
                        <div style="background:rgba(255,75,130,0.1);border:1px solid rgba(255,75,130,0.3);border-radius:10px;padding:12px;">
                            <div style="font-size:22px;font-weight:700;color:#ff4b82;">{t_videos}</div>
                            <div style="font-size:10px;color:var(--text-muted);margin-top:4px;">VIDEOS</div>
                        </div>
                        <div style="background:rgba(241,250,140,0.1);border:1px solid rgba(241,250,140,0.3);border-radius:10px;padding:12px;">
                            <div style="font-size:22px;font-weight:700;color:#f1fa8c;">{t_audios}</div>
                            <div style="font-size:10px;color:var(--text-muted);margin-top:4px;">AUDIOS</div>
                        </div>
                        <div style="background:rgba(124,208,255,0.1);border:1px solid rgba(124,208,255,0.3);border-radius:10px;padding:12px;">
                            <div style="font-size:22px;font-weight:700;color:#7cd0ff;">{t_changes}</div>
                            <div style="font-size:10px;color:var(--text-muted);margin-top:4px;">SESSIONS</div>
                        </div>
                    </div>
                </div>
            </div>"""

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Veronica — Principal's Report</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
:root {{
    --bg-dark:#05070a; --glass-bg:linear-gradient(145deg,rgba(20,24,32,0.5) 0%,rgba(13,16,22,0.7) 100%);
    --glass-border:rgba(255,255,255,0.08); --glass-edge-top:rgba(255,255,255,0.15);
    --glass-edge-left:rgba(255,255,255,0.05); --neon-cyan:#7cd0ff;
    --text-main:#f0f6fc; --text-muted:#8b949e;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Inter',sans-serif;color:var(--text-main);background-color:var(--bg-dark);
      background-image:linear-gradient(rgba(255,255,255,0.015) 1px,transparent 1px),
      linear-gradient(90deg,rgba(255,255,255,0.015) 1px,transparent 1px);
      background-size:50px 50px;min-height:100vh;overflow-x:hidden;letter-spacing:-0.2px}}
.ambient-orb{{position:fixed;border-radius:50%;filter:blur(140px);z-index:-1;pointer-events:none;opacity:0.45}}
.orb-1{{top:-10%;left:-5%;width:50vw;height:50vw;background:rgba(88,166,255,0.2)}}
.orb-2{{bottom:-20%;right:-10%;width:60vw;height:60vw;background:rgba(162,119,255,0.15)}}
.topbar-wrapper{{padding:24px 32px 0 32px}}
.topbar{{max-width:1400px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;gap:16px}}
.glass-pill{{display:flex;align-items:center;gap:10px;font-size:13px;font-weight:600;
             background:rgba(10,12,16,0.6);backdrop-filter:blur(40px);padding:10px 20px;
             border-radius:30px;border:1px solid var(--glass-border);border-top:1px solid var(--glass-edge-top);
             box-shadow:0 15px 35px rgba(0,0,0,0.5)}}
.container{{max-width:1400px;margin:0 auto;padding:32px}}
.subjects-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:24px}}
.card{{background:var(--glass-bg);backdrop-filter:blur(40px) saturate(200%);
       border:1px solid var(--glass-border);border-top:1px solid var(--glass-edge-top);
       border-radius:20px;box-shadow:0 25px 50px -12px rgba(0,0,0,0.6);overflow:hidden}}
.card-header{{display:flex;justify-content:space-between;align-items:center;
              padding:18px 24px;border-bottom:1px solid rgba(255,255,255,0.03);background:rgba(0,0,0,0.2)}}
.card-title{{display:flex;align-items:center;gap:10px;font-weight:600;font-size:13px;
             text-transform:uppercase;letter-spacing:1px;color:var(--neon-cyan)}}
.card-body{{padding:24px}}
.title-icon{{width:18px;height:18px;stroke:currentColor;fill:none;stroke-width:2;
             stroke-linecap:round;stroke-linejoin:round}}
.dl-btn{{display:inline-block;margin-top:24px;padding:12px 28px;
         background:rgba(124,208,255,0.1);border:1px solid rgba(124,208,255,0.4);
         border-radius:12px;color:#7cd0ff;font-weight:600;font-size:13px;
         text-decoration:none;transition:all 0.3s}}
.dl-btn:hover{{background:rgba(124,208,255,0.2);box-shadow:0 8px 20px rgba(124,208,255,0.2)}}
.back-btn{{display:inline-block;margin-right:16px;padding:12px 28px;
           background:rgba(255,255,255,0.05);border:1px solid var(--glass-border);
           border-radius:12px;color:var(--text-muted);font-weight:600;font-size:13px;
           text-decoration:none;transition:all 0.3s}}
.back-btn:hover{{background:rgba(255,255,255,0.1);color:var(--text-main)}}
</style></head>
<body>
<div class="ambient-orb orb-1"></div>
<div class="ambient-orb orb-2"></div>
<div class="topbar-wrapper">
  <div class="topbar">
    <div class="glass-pill"><span style="color:var(--neon-cyan)">✦</span> Principal's Report &nbsp;—&nbsp; {hostname}.local</div>
    <div class="glass-pill" style="font-size:12px;color:var(--text-muted);">{now_str}</div>
  </div>
</div>
<div class="container">
  <div class="subjects-grid">
    {subject_cards_html}
  </div>
  <div style="margin-top:32px;">
    <a href="/" class="back-btn">← Back to Dashboard</a>
    <a href="/report/download" class="dl-btn">⬇ Download JSON Report</a>
  </div>
</div>
</body></html>"""

 
@app.route("/report/download")
def report_download():
    """Download the raw activity log as a JSON file."""
    from flask import Response
    data = _load_log()
    now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    return Response(
        json.dumps(data, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment;filename=veronica_report_{now_str}.json"}
    )



# ═══════════════════════════════════════════════════════════════
#  HARDWARE POLLING LOOP  (background thread)
# ═══════════════════════════════════════════════════════════════

def hardware_loop(buzzer, keypad, nfc):
    global current_subject
    while True:
        # TTP229 keypad
        for key_num in keypad.get_newly_pressed():
            handle_key(key_num, buzzer)

        # NFC reader
        if NFC_ENABLED:
            result = nfc.poll()
            if result:
                if result.startswith("ACTION:"):
                    action = result.split(":")[1]
                    if action == "BROWSER":
                        buzzer.beep(1)
                        subprocess.Popen(
                            "DISPLAY=:0 chromium-browser https://www.google.com",
                            shell=True)
                    elif action == "SHUTDOWN":
                        buzzer.beep(3); shutdown_system()
                    elif action == "ADMIN_ALERT":
                        buzzer.beep(5)
                        send_telegram("🚨 ADMIN ALERT: Assistance needed at Veronica!")
                        threading.Thread(target=take_photo_and_upload, daemon=True).start()
                elif result != current_subject:
                    current_subject = result
                    print(f"🏷️  NFC → {current_subject}")
                    log_activity("subject_change")
                    buzzer.beep(2)
                    send_telegram(f"🏷️  Subject: {current_subject}")

        time.sleep(0.05)


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    if not os.path.exists(FFMPEG_BIN):
        print(f"❌  ffmpeg not found at {FFMPEG_BIN}")
        print("    sudo apt install ffmpeg")
        return
    print(f"✅ ffmpeg: {FFMPEG_BIN}")

    # Background services
    threading.Thread(target=telegram_listener, daemon=True).start()
    threading.Thread(target=watchdog_loop,     daemon=True).start()
    threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=5000, use_reloader=False),
        daemon=True).start()

    # Hardware
    buzzer = BuzzerWrapper(BUZZER_PIN)
    keypad = TTP229Touch()
    nfc    = NFCReaderPN532()

    print(" Project Veronica FINAL started")
    print(f"   Camera  : {KERO_VIDEO_DEVICE}  ({KERO_WIDTH}x{KERO_HEIGHT} MJPEG)")
    print(f"   Mic     : {KERO_AUDIO_DEVICE}")
    print(f"   Keypad  : TTP229 bit-bang  SDO=GPIO{TTP229_SDO}  SCL=GPIO{TTP229_SCL}")
    print(f"   Buzzer  : Passive PWM  GPIO{BUZZER_PIN}  {BUZZER_FREQ}Hz")
    print(f"   NFC     : PN532 I2C  {len(NFC_MAP)} cards mapped")
    print(f"   Web UI  : http://0.0.0.0:5000")
    print(f"   Report  : http://0.0.0.0:5000/report")
    buzzer.beep(3)

    # Hardware polling in background thread
    threading.Thread(target=hardware_loop,
                     args=(buzzer, keypad, nfc),
                     daemon=True).start()

    # Main thread just keeps the process alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 Shutting down…")
    finally:
        if recording:       stop_video_audio()
        if audio_recording: stop_audio_only()


if __name__ == "__main__":
    main()
