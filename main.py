from __future__ import print_function
from flask import Flask, request
from threading import Lock, Thread
import os, time, datetime, requests, subprocess, functools, builtins, signal, shutil, psutil, socket, json

# Google Drive Imports
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# --- HARDWARE IMPORTS (New) ---
from gpiozero import DigitalInputDevice, DigitalOutputDevice
import board
import busio
from adafruit_pn532.i2c import PN532_I2C

# Load Pi 5 Factory
try:
    from gpiozero.pins.lgpio import LGPIOFactory
    factory = LGPIOFactory()
except ImportError:
    print("⚠️ LGPIO not found. Using default pin factory.")
    factory = None

print = functools.partial(builtins.print, flush=True)

# =========================
# Configuration
# =========================
ALLOWED_USERS = ["1356709538"]
SCOPES = ['https://www.googleapis.com/auth/drive.file']
FOLDER_ID = "12l5mNFGeAIcPHt-GZSti8KvHNAf-OENf"
BOT_TOKEN = "8365210789:AAFbiu9hyMDwTkvLNq7vOnGLDI7g9WT-BEg"
CHAT_ID = "1356709538"
TOKEN_PATH = "/home/light/token.json"
RTSP_URL = "rtsp://10.31.229.242:8080/h264_aac.sdp"
PHOTO_URL = "http://10.31.229.242:8080/shot.jpg"
FFMPEG_BIN = shutil.which("ffmpeg") or "ffmpeg"

# Hardware Config (Membrane Keypad Reversed + Buzzer + NFC)
HW_CONFIG = {
    "rows": [6, 5, 11, 26],
    "cols": [10, 22, 27, 17],
    "buzzer": {"PIN": 23, "beep_ms": 100},
    "nfc": {"enabled": True, "poll_interval_sec": 0.2}
}

# --- LOGIC MAPPING ---
SUBJECT_KEYS = {

    'A': "Math", 
    'B': "Bio", 
    'C': "English", 
    'D': "General"
}

MODE_KEYS = {
    '1': "PHOTO", 
    '2': "VIDEO", 
    '3': "AUDIO", 
    '4': "STATS", 
    '#': "REBOOT", 
    '*': "CLEAR"
}

app = Flask(__name__) 

# =========================
# State
# =========================
recording_video = False
recording_audio = False
ffmpeg_proc = None
audio_proc = None
current_subject = None
current_filename = None
state_lock = Lock()

# =========================
# Hardware Classes
# =========================

class BuzzerWrapper:
    def __init__(self, pin, beep_ms=100):
        self.bz = DigitalOutputDevice(pin, pin_factory=factory)
        self.beep_ms = beep_ms / 1000.0
    
    def beep(self, times=1, gap_ms=100):
        Thread(target=self._beep_thread, args=(times, gap_ms)).start()

    def _beep_thread(self, times, gap_ms):
        for _ in range(times):
            self.bz.on()
            time.sleep(self.beep_ms)
            self.bz.off()
            time.sleep(gap_ms/1000.0)

class MembraneKeypad:
    def __init__(self, row_pins, col_pins):
        self.rows = [DigitalOutputDevice(pin, initial_value=False, pin_factory=factory) for pin in row_pins]
        self.cols = [DigitalInputDevice(pin, pull_up=False, pin_factory=factory) for pin in col_pins]
        self.keys = [['1', '2', '3', 'A'], ['4', '5', '6', 'B'], ['7', '8', '9', 'C'], ['*', '0', '#', 'D']]

    def get_pressed_key(self):
        pressed_key = None
        for r, row_pin in enumerate(self.rows):
            row_pin.on()
            for c, col_pin in enumerate(self.cols):
                if col_pin.value == 1:
                    pressed_key = self.keys[r][c]
                    while col_pin.value == 1: time.sleep(0.05) # Debounce
                    break
            row_pin.off()
            if pressed_key: break
        return pressed_key

class NFCReaderPN532:
    def __init__(self):
        self.subject_map = {"D035D95F": "Physics", "89D14906": "Chemistry"}
        try:
            i2c = busio.I2C(board.SCL, board.SDA)
            self.pn532 = PN532_I2C(i2c, debug=False)
            self.pn532.SAM_configuration()
            print("✅ NFC PN532 Initialized")
        except:
            print("⚠️ NFC Init Failed")
            self.pn532 = None

    def poll_subject(self):
        if not self.pn532: return None
        try:
            uid = self.pn532.read_passive_target(timeout=0.1)
            if uid:
                uid_str = "".join([f"{x:02X}" for x in uid])
                return self.subject_map.get(uid_str)
        except: pass
        return None

# =========================
# Core Functions
# =========================

def send_telegram(msg, retries=3, delay=2):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
            if r.status_code == 200:
                print(f"✅ Telegram sent: {msg}")
                return True
            else:
                print(f"⚠️ Telegram send failed: {r.text}")
        except Exception as e:
            print(f"⚠️ Telegram send exception: {e}")
        time.sleep(delay)
    return False

def get_drive_service():
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, 'w') as token:
            token.write(creds.to_json())
    return build('drive', 'v3', credentials=creds)

def get_subject_folder(service, subject_name):
    # 1. Get Month Folder
    month_name = datetime.datetime.now().strftime("%Y-%m")
    query = f"mimeType='application/vnd.google-apps.folder' and name='{month_name}' and '{FOLDER_ID}' in parents and trashed=false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    items = results.get('files', [])
    
    if not items:
        month_meta = {'name': month_name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [FOLDER_ID]}
        month_folder = service.files().create(body=month_meta, fields='id').execute()
        month_id = month_folder.get('id')
    else:
        month_id = items[0]['id']

    # 2. Get Subject Folder Inside Month Folder
    if not subject_name: subject_name = "General"
    query_subj = f"mimeType='application/vnd.google-apps.folder' and name='{subject_name}' and '{month_id}' in parents and trashed=false"
    results_subj = service.files().list(q=query_subj, fields="files(id, name)").execute()
    items_subj = results_subj.get('files', [])

    if not items_subj:
        subj_meta = {'name': subject_name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [month_id]}
        subj_folder = service.files().create(body=subj_meta, fields='id').execute()
        return subj_folder.get('id')
    else:
        return items_subj[0]['id']

def upload_to_drive(filename, subject="General"):
    try:
        service = get_drive_service()
        parent_id = get_subject_folder(service, subject)
        file_metadata = {'name': os.path.basename(filename), 'parents': [parent_id]}
        media = MediaFileUpload(filename, resumable=True)
        file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        link = file.get('webViewLink')
        send_telegram(f"✅ Uploaded {os.path.basename(filename)} to {subject}\n🔗 {link}")
        os.remove(filename)
    except Exception as e:
        send_telegram(f"❌ Upload Failed: {e}")

def generate_filename(type_prefix):
    # Naming: Subject_Type_Date_Time.ext
    ts = datetime.datetime.now().strftime("%m%d_%H%M")
    subj = current_subject if current_subject else "General"
    ext = "jpg" if type_prefix == "Photo" else "mp4" if type_prefix == "Video" else "m4a"
    return f"{subj}_{type_prefix}_{ts}.{ext}"

def take_photo():
    if not current_subject:
        send_telegram("⚠️ Please Select Subject First! (Tap card or press A-D)")
        return
    
    fname = generate_filename("Photo")
    try:
        r = requests.get(PHOTO_URL, timeout=5)
        with open(fname, "wb") as f: f.write(r.content)
        send_telegram(f"📸 Photo Taken: {fname}")
        Thread(target=upload_to_drive, args=(fname, current_subject)).start()
    except Exception as e:
        send_telegram(f"❌ Photo Error: {e}")

def toggle_video():
    global recording_video, ffmpeg_proc, current_filename
    
    if recording_audio:
        send_telegram("⚠️ Audio is running. Stop it first."); return
    if not current_subject:
        send_telegram("⚠️ Please Select Subject First!"); return

    if not recording_video:
        # Save as MKV for more robust timestamp handling
        current_filename = generate_filename("Video").replace(".mp4", ".mkv")
        cmd = [
            FFMPEG_BIN, "-y",
            "-rtsp_transport", "tcp",
            "-i", RTSP_URL,
            "-c", "copy",                        # copy streams directly
            "-fflags", "+genpts",                # generate presentation timestamps
            "-use_wallclock_as_timestamps", "1", # smooth DTS/PTS
            "-loglevel", "warning",              # suppress console spam
            current_filename
        ]
        ffmpeg_proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        recording_video = True
        send_telegram(f"🎥 Recording Started: {current_subject}")
    else:
        stop_recording()


def toggle_audio():
    global recording_audio, audio_proc, current_filename
    
    if recording_video:
        send_telegram("⚠️ Video is running. Stop it first."); return
    if not current_subject:
        send_telegram("⚠️ Please Select Subject First!"); return

    if not recording_audio:
        current_filename = generate_filename("Audio")
        cmd = [FFMPEG_BIN, "-y", "-rtsp_transport", "tcp", "-i", RTSP_URL, "-vn", "-acodec", "aac", "-b:a", "256k", current_filename]
        audio_proc = subprocess.Popen(cmd)
        recording_audio = True
        send_telegram(f"🎙️ Audio Recording: {current_subject}")
    else:
        stop_recording()

def stop_recording():
    global recording_video, recording_audio, ffmpeg_proc, audio_proc
    
    if recording_video and ffmpeg_proc:
        try:
            ffmpeg_proc.stdin.write(b"q\n"); ffmpeg_proc.stdin.flush(); ffmpeg_proc.wait(timeout=5)
        except: ffmpeg_proc.kill()
        recording_video = False
        send_telegram("🛑 Video Stopped. Uploading...")
        Thread(target=upload_to_drive, args=(current_filename, current_subject)).start()

    if recording_audio and audio_proc:
        audio_proc.send_signal(signal.SIGINT)
        try: audio_proc.wait(timeout=5)
        except: audio_proc.kill()
        recording_audio = False
        send_telegram("🛑 Audio Stopped. Uploading...")
        Thread(target=upload_to_drive, args=(current_filename, current_subject)).start()

def reminder_loop(buzzer):
    while True:
        if recording_video or recording_audio:
            buzzer.beep(1) # One beep every minute
        time.sleep(60)

def get_storage_usage():
    info = shutil.disk_usage("/")
    used_pct = (info.used / info.total) * 100
    free_gb = info.free / (1024**3)
    total_gb = info.total / (1024**3)
    return round(used_pct, 1), round(free_gb, 2), round(total_gb, 2)

def get_uptime():
    boot_ts = psutil.boot_time()
    delta = datetime.timedelta(seconds=int(time.time() - boot_ts))
    return str(delta)

def generate_status_summary(cpu, ram, free_gb):
    summary = "🧠 AI Status Summary:\n"
    summary += f"CPU usage is {'high' if cpu > 80 else 'normal'} at {cpu}%.\n"
    summary += f"RAM usage is {'critical' if ram > 90 else 'moderate'} at {ram}%.\n"
    summary += f"Free disk space is {free_gb:.2f} GB.\n"
    summary += f"Current Subject: {current_subject if current_subject else 'None'}.\n"
    if cpu > 90 or ram > 95: summary += "⚠️ System is under heavy load. Consider stopping recordings or rebooting."
    else: summary += "✅ System is stable and ready for operations."
    return summary

def send_stats_report():
    uptime_min = int((time.time() - psutil.boot_time()) // 60)
    free_gb = shutil.disk_usage("/").free / (1024**3)
    photo_count = len([f for f in os.listdir() if f.startswith("photo_")])
    video_count = len([f for f in os.listdir() if f.startswith("video_")])
    audio_count = len([f for f in os.listdir() if f.startswith("audio_")])
    
    try:
        r = requests.get(RTSP_URL, timeout=3)
        stream_status = "✅ Reachable" if r.status_code == 200 else "⚠️ Unreachable"
    except:
        stream_status = "⚠️ Unreachable"
    msg = (
        f"📊 System Stats:\n"
        f"📝 Subject: {current_subject}\n"
        f"⏱️ Uptime: {uptime_min} min\n"
        f"📸 Photos: {photo_count}\n"
        f"🎥 Videos: {video_count}\n"
        f"🎙️ Audios: {audio_count}\n"
        f"💾 Free Space: {free_gb:.2f} GB\n"
        f"📡 RTSP Stream: {stream_status}"
    )
    send_telegram(msg)

def cleanup_old_files(days=2):
    cutoff = time.time() - (days * 86400)
    deleted = []
    for fname in os.listdir():
        if fname.startswith(("photo_", "video_", "audio_", "Physics_", "Chemistry_", "Math_", "English_")) and os.path.isfile(fname):
            if os.path.getmtime(fname) < cutoff:
                try:
                    os.remove(fname)
                    deleted.append(fname)
                except Exception as e:
                    print(f"⚠️ Failed to delete {fname}: {e}")
    if deleted:
        msg = f"🧹 Cleanup complete\n🗑️ Deleted {len(deleted)} files:\n" + "\n".join(deleted)
    else:
        msg = "🧹 Cleanup complete\n✅ No old files found."
    send_telegram(msg)
    return msg

def reboot_system():
    send_telegram("🔁 Rebooting...")
    subprocess.Popen(["sudo", "reboot"])

# -------------------------
# Flask Routes
# -------------------------
@app.route("/")
def dashboard():
    with state_lock:
        status_msg = "🟢 Idle"
        if recording_video: status_msg = f"🎥 Recording ({current_subject})"
        elif recording_audio: status_msg = f"🎙️ Recording ({current_subject})"
        
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        free_gb = shutil.disk_usage("/").free / (1024**3)
        used_pct, free_gb2, total_gb = get_storage_usage()
        
        summary = generate_status_summary(cpu, ram, free_gb)
        html_summary = summary.replace('\n', '<br>')
        
        photo_files = sorted([f for f in os.listdir() if f.startswith("photo_")], reverse=True)
        video_files = sorted([f for f in os.listdir() if f.startswith("video_")], reverse=True)
        audio_files = sorted([f for f in os.listdir() if f.startswith("audio_")], reverse=True)

        last_photo = photo_files[0] if photo_files else "None"
        last_video = video_files[0] if video_files else "None"
        last_audio = audio_files[0] if audio_files else "None"
        
        uptime_str = get_uptime()
        hostname = socket.gethostname()

        return f"""
        <!doctype html>
        <html lang="en">
        <head>
            <meta charset="utf-8"/>
            <meta name="viewport" content="width=device-width, initial-scale=1"/>
            <title>Veronica Center</title>
            <style>
                :root {{ --bg: #0f1115; --bg-2: #12151b; --glass: rgba(255,255,255,0.06); --glass-strong: rgba(255,255,255,0.12); --border: rgba(255,255,255,0.12); --text: #e6e8eb; --muted: #a9b0ba; --accent: #7aa2ff; --accent-2: #7df3ff; --shadow: 0 12px 40px rgba(0,0,0,0.45); }}
                body {{ margin: 0; padding: 0; font-family: Inter, sans-serif; color: var(--text); background: radial-gradient(1200px 800px at 10% 10%, rgba(122,162,255,0.12), transparent 60%), linear-gradient(180deg, var(--bg), var(--bg-2)); }}
                .nav {{ position: sticky; top: 0; backdrop-filter: blur(16px); background: var(--glass); border-bottom: 1px solid var(--border); box-shadow: var(--shadow); z-index: 10; }}
                .nav-inner {{ max-width: 1080px; margin: 0 auto; padding: 14px 20px; display: flex; align-items: center; gap: 16px; }}
                .brand {{ display: flex; align-items: center; gap: 12px; font-weight: 700; }}
                .container {{ max-width: 1080px; margin: 0 auto; padding: 26px 20px 60px; }}
                .grid {{ display: grid; grid-template-columns: 1.2fr 1fr; gap: 24px; }}
                @media (max-width: 940px) {{ .grid {{ grid-template-columns: 1fr; }} }}
                .card {{ background: var(--glass); border: 1px solid var(--border); border-radius: 16px; box-shadow: var(--shadow); overflow: hidden; }}
                .card-header {{ display: flex; align-items: center; justify-content: space-between; padding: 16px 18px; border-bottom: 1px solid var(--border); }}
                .card-body {{ padding: 18px; }}
                .kv {{ display: grid; grid-template-columns: 1fr auto; gap: 12px; padding: 8px 0; border-bottom: 1px dashed var(--border); }}
                .bar {{ width: 100%; height: 14px; border-radius: 10px; background: rgba(255,255,255,0.08); border: 1px solid var(--border); overflow: hidden; }}
                .bar > span {{ display: block; height: 100%; width: {used_pct}%; background: linear-gradient(90deg, #4facfe 0%, #00f2fe 100%); }}
                .actions {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }}
                .btn {{ display: inline-flex; align-items: center; justify-content: center; padding: 12px 14px; border-radius: 12px; color: var(--text); border: 1px solid var(--border); background: var(--glass-strong); cursor: pointer; }}
                .status-active {{ color: #a6e3a1; font-weight: bold; }}
            </style>
        </head>
        <body>
            <div class="nav">
                <div class="nav-inner">
                    <div class="brand">Control Center <small>{hostname}</small></div>
                    <span>Mode: <span class="status-active">{status_msg}</span></span>
                    <span style="margin-left:auto">{current_subject if current_subject else "No Subject"}</span>
                </div>
            </div>
            <div class="container">
                <div class="grid">
                    <div class="stack">
                        <div class="card">
                            <div class="card-header"><span>🖥️ System Health</span></div>
                            <div class="card-body">
                                <div class="kv"><b>CPU</b><span>{cpu}%</span></div>
                                <div class="kv"><b>RAM</b><span>{ram}%</span></div>
                                <div class="kv"><b>Uptime</b><span>{uptime_str}</span></div>
                            </div>
                        </div>
                        <div class="card">
                            <div class="card-header"><span>Storage</span></div>
                            <div class="card-body">
                                <div class="kv"><b>Used</b><span>{used_pct}%</span></div>
                                <div class="bar"><span style="width:{used_pct}%"></span></div>
                                <div style="text-align:right; font-size:12px; color:#aaa; margin-top:5px;">{free_gb2} GB Free / {total_gb} GB Total</div>
                            </div>
                        </div>
                        <div class="card">
                            <div class="card-header"><span>📊 Summary</span></div>
                            <div class="card-body"><div>{html_summary}</div></div>
                        </div>
                    </div>
                    <div class="stack">
                        <div class="card">
                            <div class="card-header"><span> Actions</span></div>
                            <div class="card-body">
                                <div class="actions">
                                    <button class="btn" onclick="post('photo')">📷 Photo</button>
                                    <button class="btn" onclick="post('video')">🎬 Video</button>
                                    <button class="btn" onclick="post('audio')">🎙️ Audio</button>
                                    <button class="btn" onclick="post('stop')">⏹ Stop</button>
                                    <button class="btn" onclick="post('stats')">📈 Stats</button>
                                    <button class="btn" onclick="post('reboot')">⚠️ Reboot</button>
                                </div>
                            </div>
                        </div>
                        <div class="card">
                            <div class="card-header"><span>🗂️ Recent</span></div>
                            <div class="card-body">
                                <div class="kv"><b>Photo</b><span>{last_photo}</span></div>
                                <div class="kv"><b>Video</b><span>{last_video}</span></div>
                                <div class="kv"><b>Audio</b><span>{last_audio}</span></div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            <script>
            function post(cmd) {{
                if (!confirm("Run command: " + cmd + "?")) return;
                fetch("/trigger", {{ method: "POST", headers: {{ "Content-Type": "application/x-www-form-urlencoded" }}, body: "cmd=" + cmd }})
                .then(res => res.text()).then(msg => {{ alert("✅ " + msg); location.reload(); }})
                .catch(err => {{ alert("❌ " + err); }});
            }}
            setInterval(() => location.reload(), 10000);
            </script>
        </body>
        </html>
        """

@app.route("/trigger", methods=["POST"])
def trigger():
    cmd = request.form.get("cmd")
    if cmd == "photo": take_photo()
    elif cmd == "video": toggle_video()
    elif cmd == "audio": toggle_audio()
    elif cmd == "stop": stop_recording()
    elif cmd == "stats": send_stats_report()
    elif cmd == "reboot": reboot_system()
    return "OK"

def telegram_listener():
    print("📡 Telegram listener started")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    last_update_id = load_last_update_id()
    while True:
        try:
            params = {"timeout": 5}
            if last_update_id: params["offset"] = last_update_id + 1
            r = requests.get(url, params=params, timeout=10)
            data = r.json()
            for update in data.get("result", []):
                last_update_id = update["update_id"]
                save_last_update_id(last_update_id)
                msg = update.get("message", {}).get("text", "")
                if msg == "/photo": take_photo_and_upload()
                elif msg == "/video": start_video_audio()
                elif msg == "/audio": start_audio_only()
                elif msg == "/stop": stop_recording()
                elif msg == "/stats": send_stats_report()
        except: time.sleep(5)
        time.sleep(1)

def load_last_update_id():
    try:
        with open("last_update_id.txt", "r") as f: return int(f.read().strip())
    except: return None

def save_last_update_id(update_id):
    try:
        with open("last_update_id.txt", "w") as f: f.write(str(update_id))
    except: pass

def main():
    global current_subject
    
    # Start Threads
    Thread(target=telegram_listener, daemon=True).start()
    Thread(target=lambda: app.run(host="0.0.0.0", port=5000, use_reloader=False), daemon=True).start()

    # Init Hardware
    buzzer = BuzzerWrapper(HW_CONFIG["buzzer"]["PIN"], HW_CONFIG["buzzer"]["beep_ms"])
    keypad = MembraneKeypad(HW_CONFIG["rows"], HW_CONFIG["cols"])
    nfc = NFCReaderPN532()
    
    Thread(target=reminder_loop, args=(buzzer,), daemon=True).start()

    print("🚀 Veronica System Started (Membrane + NFC)")
    buzzer.beep(3)

    try:
        while True:
            # 1. Check NFC
            if HW_CONFIG["nfc"]["enabled"]:
                subj = nfc.poll_subject()
                if subj and subj != current_subject:
                    current_subject = subj
                    print(f"🏷️ NFC Set: {current_subject}")
                    buzzer.beep(2)
                    send_telegram(f"📘 Subject Changed: {current_subject}")

            # 2. Check Keypad
            key = keypad.get_pressed_key()
            if key:
                print(f"🎹 Key: {key}")
                
                # ANY key stops recording (Pause logic)
                if recording_video or recording_audio:
                    if key not in ['A','B','C','D','*','#']: # Allow basic Nav, but generally stop
                        stop_recording()
                        buzzer.beep(2)
                        time.sleep(1) # Prevent immediate re-trigger
                        continue

                # Subject Selection (A-D + 1-2 virtual for cards)
                if key in SUBJECT_KEYS:
                    current_subject = SUBJECT_KEYS[key]
                    print(f"📘 Subject Set: {current_subject}")
                    buzzer.beep(2)
                
                # Mode Selection
                elif key in MODE_KEYS:
                    action = MODE_KEYS[key]
                    if action == "PHOTO": take_photo(); buzzer.beep(1)
                    elif action == "VIDEO": toggle_video(); buzzer.beep(1)
                    elif action == "AUDIO": toggle_audio(); buzzer.beep(1)
                    elif action == "STATS": send_stats_report(); buzzer.beep(1)
                    elif action == "CLEAR": current_subject = None; buzzer.beep(1)
                    elif action == "RESTART": reboot_system()

            time.sleep(0.05)

    except KeyboardInterrupt:
        print("👋 Exiting...")

if __name__ == "__main__":
    main()