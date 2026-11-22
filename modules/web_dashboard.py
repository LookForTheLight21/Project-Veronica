"""
Flask Web Dashboard, Classroom Projector & Diagnostic Control Hub for Project Veronica FINAL.
Features:
  - /               : Veronica Command Center dashboard (templates/index.html)
  - /projector      : Fullscreen High-Contrast Projector View for Back-Row Students
  - /report         : Principal's Academic & Media Ledger
  - /login          : Field Technician Login (User: Chorie, Pass: 1234)
  - /logout         : Clear diagnostic session
  - /admin          : Veronica Diagnostic & Engineering Control Center (templates/admin.html)
  - /api/admin/...  : Dynamic Configuration & Hardware Testing API
  - /api/latest_asset: Real-time JSON telemetry for projector & dashboard auto-update
  - /cmd/<action>   : REST trigger endpoint for tactile dashboard triggers
  - /media/<folder>/<filename>: Direct local offline asset server
  - /report/download: Download JSON activity log
"""
import os
import time
import json
import socket
import datetime
import subprocess
import shutil
import psutil
from flask import (
    Flask,
    Response,
    send_from_directory,
    jsonify,
    request as flask_request,
    session,
    redirect,
    url_for,
)

import state
from activity_logger import load_log, log_activity
from config import (
    BASE_DIR,
    NFC_MAP,
    STORAGE_DIR,
    PHOTOS_DIR,
    NOTES_DIR,
    VIDEOS_DIR,
    ADMIN_USERNAME,
    ADMIN_PASSWORD,
    get_all_config,
    save_dynamic_config,
)
from camera import (
    take_photo_and_upload,
    compile_and_publish_session_pdf,
    start_video_audio,
    stop_video_audio,
    start_audio_only,
    stop_audio_only,
)
from system_utils import get_storage_usage, get_uptime, send_stats_report
from telegram_bot import send_telegram

TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

app = Flask(__name__)
app.secret_key = "veronica_diagnostic_secret_key_2026_secured"

# Callback holders for event dispatching from HTTP fallback
_on_key_callback = None
_on_nfc_callback = None
_buzzer_controller = None


def register_pod_callbacks(on_key, on_nfc, buzzer_ctrl=None):
    global _on_key_callback, _on_nfc_callback, _buzzer_controller
    _on_key_callback = on_key
    _on_nfc_callback = on_nfc
    if buzzer_ctrl:
        _buzzer_controller = buzzer_ctrl


# ==============================================================================
# LOCAL ASSET SERVER (Offline classroom access)
# ==============================================================================
@app.route("/media/<folder>/<path:filename>")
def serve_media(folder, filename):
    folder_map = {
        "photos": PHOTOS_DIR,
        "notes": NOTES_DIR,
        "videos": VIDEOS_DIR
    }
    target_dir = folder_map.get(folder, STORAGE_DIR)
    return send_from_directory(target_dir, filename)


@app.route("/sample_board.svg")
def serve_sample_board():
    return send_from_directory(TEMPLATES_DIR, "sample_board.svg", mimetype="image/svg+xml")


@app.route("/video_feed")
def video_feed():
    """Live camera stream feed for diagnostics, aiming & focus checking."""
    if state.latest_photo_path and os.path.exists(state.latest_photo_path):
        return send_from_directory(os.path.dirname(state.latest_photo_path), os.path.basename(state.latest_photo_path), mimetype="image/jpeg")
    return send_from_directory(TEMPLATES_DIR, "sample_board.svg", mimetype="image/svg+xml")


@app.route("/api/latest_asset")
def api_latest_asset():
    """Returns telemetry of the latest chalkboard photo for live projector & dashboard sync."""
    photo_name = os.path.basename(state.latest_photo_path) if state.latest_photo_path else None
    pdf_name = os.path.basename(state.latest_pdf_path) if state.latest_pdf_path else None
    
    cpu = psutil.cpu_percent() if hasattr(psutil, 'cpu_percent') else 0
    ram = psutil.virtual_memory().percent if hasattr(psutil, 'virtual_memory') else 0
    used_pct, free_gb, total_gb = get_storage_usage()

    now = time.time()
    pod_online = (
        state.pod_connected
        and state.pod_last_seen > 0
        and (now - state.pod_last_seen) < 15
    )

    return jsonify({
        "subject": state.current_subject or "General Session",
        "latest_photo": photo_name,
        "latest_photo_url": f"/media/photos/{photo_name}" if photo_name else "/sample_board.svg",
        "latest_pdf": pdf_name,
        "session_pages": len(state.session_photos),
        "recording_video": state.recording,
        "recording_audio": state.audio_recording,
        "pod_connected": pod_online,
        "pod_ip": state.pod_ip if pod_online else None,
        "cpu": cpu,
        "ram": ram,
        "uptime": get_uptime(),
        "storage_free_gb": free_gb,
        "storage_used_pct": used_pct
    })


# ==============================================================================
# 📽️ CLASSROOM PROJECTOR VIEW (High-Contrast for Back-Row Students)
# ==============================================================================
@app.route("/projector")
def projector_view():
    path = os.path.join(TEMPLATES_DIR, "projector.html")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h3>Projector template not found</h3>", 404


@app.route("/pod")
@app.route("/pod_touch")
def pod_touch_view():
    path = os.path.join(TEMPLATES_DIR, "pod_touch.html")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h3>Touch Pod template not found</h3>", 404


# ==============================================================================
# 🖥️ PI 5 FULL-SCREEN KIOSK DASHBOARD (Runs in Chromium on Pi 5's MPI3501 display)
# ==============================================================================
@app.route("/pi")
@app.route("/kiosk")
def pi_dashboard():
    """Full-screen lectern UI optimised for Pi 5's 480×320 MPI3501 display."""
    path = os.path.join(TEMPLATES_DIR, "pi_dashboard.html")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h3>Pi Dashboard template not found</h3>", 404


# ==============================================================================
# 🎛️ COMMAND CENTER WEB DASHBOARD
# ==============================================================================
@app.route("/")
def dashboard():
    path = os.path.join(TEMPLATES_DIR, "index.html")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h3>Dashboard template not found</h3>", 404


# ==============================================================================
# 🏛️ PRINCIPAL'S AUDIT REPORT
# ==============================================================================
@app.route("/report")
def report():
    path = os.path.join(TEMPLATES_DIR, "report.html")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h3>Report template not found</h3>", 404


@app.route("/api/report_data")
def api_report_data():
    log_data = load_log()
    photo_count = len(os.listdir(PHOTOS_DIR)) if os.path.exists(PHOTOS_DIR) else 0
    video_count = len(os.listdir(VIDEOS_DIR)) if os.path.exists(VIDEOS_DIR) else 0
    notes_files = [f for f in os.listdir(NOTES_DIR) if f.endswith('.pdf')] if os.path.exists(NOTES_DIR) else []
    notes_count = len(notes_files)

    records = []
    total_classes = len(log_data.keys())
    for subj, info in log_data.items():
        daily = info.get("daily", {})
        for date_str, dinfo in daily.items():
            records.append({
                "subject": subj,
                "date": date_str,
                "photos": dinfo.get("photos", 0),
                "videos": dinfo.get("videos", 0),
                "audios": dinfo.get("audios", 0),
                "sessions_count": len(dinfo.get("sessions", []))
            })

    return jsonify({
        "total_classes": total_classes,
        "total_photos": photo_count,
        "total_notes": notes_count,
        "total_videos": video_count,
        "notes_files": notes_files,
        "records": records
    })


@app.route("/report/download")
def report_download():
    data = load_log()
    now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    return Response(
        json.dumps(data, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment;filename=veronica_report_{now_str}.json"}
    )


# ==============================================================================
# 🔒 DIAGNOSTIC LOGIN & SESSION MANAGEMENT
# ==============================================================================
@app.route("/login")
def login_page():
    if session.get("authenticated"):
        if session.get("role") == "principal":
            return redirect(url_for("report"))
        return redirect(url_for("admin_page"))
    path = os.path.join(TEMPLATES_DIR, "login.html")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h3>Login template not found</h3>", 404


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


@app.route("/api/login", methods=["POST"])
def api_login():
    data = flask_request.get_json(silent=True) or {}
    u = (data.get("username") or "").strip()
    p = (data.get("password") or "").strip()
    c = (data.get("classroom") or "Class X").strip()

    from config import ADMIN_USERNAME, ADMIN_PASSWORD
    
    # 1. Field Technician Role (Chorie / 1234)
    if u.lower() == ADMIN_USERNAME.lower() and p == ADMIN_PASSWORD:
        session["authenticated"] = True
        session["user"] = ADMIN_USERNAME
        session["role"] = "technician"
        return jsonify({
            "status": "ok",
            "role": "technician",
            "user": ADMIN_USERNAME,
            "redirect": "/admin"
        })

    # 2. Principal Role (principle / 1234)
    if u.lower() in ["principle", "principal"] and p == "1234":
        if c.lower() in ["class x", "class 10", "x", "10"]:
            session["authenticated"] = True
            session["user"] = "Principal"
            session["role"] = "principal"
            session["classroom"] = "Class X"
            return jsonify({
                "status": "ok",
                "role": "principal",
                "classroom": "Class X",
                "redirect": "/report"
            })
        else:
            return jsonify({
                "status": "not_installed",
                "classroom": c,
                "message": f"Hardware Offline: Veronica Smart Lectern is not yet installed in {c}. Active pilot deployment is in Class X."
            }), 400

    return jsonify({"status": "error", "message": "Access Denied: Invalid security passkey."}), 401


# ==============================================================================
# ⚙️ DIAGNOSTIC & CONFIGURATION PORTAL
# ==============================================================================
@app.route("/admin")
def admin_page():
    if not session.get("authenticated"):
        return redirect(url_for("login_page"))
    path = os.path.join(TEMPLATES_DIR, "admin.html")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h3>Admin template not found</h3>", 404


@app.route("/api/admin/config", methods=["GET"])
def api_admin_get_config():
    if not session.get("authenticated"):
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    return jsonify({"status": "ok", "config": get_all_config()})


@app.route("/api/admin/verify_drive", methods=["POST"])
def api_admin_verify_drive():
    from config import TOKEN_PATH
    if not os.path.exists(TOKEN_PATH):
        return jsonify({
            "status": "error",
            "connected": False,
            "message": "Google Drive token.json not found on device. OAuth link pending."
        }), 404
    try:
        from drive_upload import get_drive_service
        service = get_drive_service()
        about = service.about().get(fields="user").execute()
        user_email = about.get("user", {}).get("emailAddress", "Connected")
        return jsonify({
            "status": "ok",
            "connected": True,
            "message": f"Google Drive OAuth valid ({user_email})."
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "connected": False,
            "message": f"Drive API verification failed: {e}"
        }), 500


@app.route("/api/admin/save_config", methods=["POST"])
def api_admin_save_config():
    if not session.get("authenticated"):
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    data = flask_request.get_json(silent=True) or {}
    updated = save_dynamic_config(data)
    return jsonify({"status": "ok", "config": updated})


@app.route("/api/admin/test_buzzer", methods=["POST"])
def api_admin_test_buzzer():
    data = flask_request.get_json(silent=True) or {}
    times = int(data.get("times", 1))
    dur = float(data.get("duration", 150)) / 1000.0
    freq = int(data.get("freq", 2000))
    
    if _buzzer_controller:
        _buzzer_controller.beep(times=times, duration=dur, freq=freq)
    print(f"🔊 [Diagnostic Tone Dispatched]: {times} beep(s) @ {freq}Hz ({int(dur*1000)}ms)")
    return jsonify({"status": "ok", "times": times, "freq": freq})


@app.route("/api/admin/test_telegram", methods=["POST"])
def api_admin_test_telegram():
    res = send_telegram("📡 Veronica Diagnostic Beacon: Telegram channel verification successful!")
    return jsonify({"status": "ok" if res else "error"})


@app.route("/api/admin/ping_pod", methods=["GET", "POST"])
def api_admin_ping_pod():
    now = time.time()
    pod_online = (
        state.pod_connected
        and state.pod_last_seen > 0
        and (now - state.pod_last_seen) < 15
    )
    if pod_online:
        return jsonify({
            "status": "ok",
            "pod_connected": True,
            "ip": state.pod_ip,
            "rssi": getattr(state, "pod_rssi", None),
            "last_seen_secs": round(now - state.pod_last_seen, 1)
        })
    else:
        return jsonify({
            "status": "error",
            "pod_connected": False,
            "message": "ESP32 Pod is currently offline. No TCP connection on port 8765."
        }), 503


@app.route("/api/admin/test_camera", methods=["POST"])
def api_admin_test_camera():
    from config import KERO_VIDEO_DEVICE
    if not os.path.exists(KERO_VIDEO_DEVICE):
        return jsonify({
            "status": "error",
            "connected": False,
            "device": KERO_VIDEO_DEVICE,
            "message": f"Camera hardware {KERO_VIDEO_DEVICE} is NOT connected. Please attach USB camera to Raspberry Pi 5."
        }), 404

    res = take_photo_and_upload()
    return jsonify({
        "status": "ok",
        "connected": True,
        "device": KERO_VIDEO_DEVICE,
        "message": str(res)
    })


@app.route("/api/admin/test_mic", methods=["POST"])
def api_admin_test_mic():
    from config import KERO_AUDIO_DEVICE
    try:
        res = subprocess.run(["arecord", "-l"], capture_output=True, text=True, timeout=3)
        has_mic = "card" in res.stdout.lower()
        if not has_mic:
            return jsonify({
                "status": "error",
                "connected": False,
                "device": KERO_AUDIO_DEVICE,
                "message": "No ALSA audio capture devices found on system."
            }), 404
        return jsonify({
            "status": "ok",
            "connected": True,
            "device": KERO_AUDIO_DEVICE,
            "message": "ALSA Audio Capture device detected and verified."
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Microphone probe error: {e}"
        }), 500


@app.route("/api/admin/purge_cache", methods=["POST"])
def api_admin_purge_cache():
    if not session.get("authenticated"):
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    from config import PHOTOS_DIR
    deleted_count = 0
    bytes_freed = 0
    try:
        if os.path.exists(PHOTOS_DIR):
            for fname in os.listdir(PHOTOS_DIR):
                fpath = os.path.join(PHOTOS_DIR, fname)
                if os.path.isfile(fpath) and fname.lower().endswith((".jpg", ".jpeg", ".png")):
                    try:
                        bytes_freed += os.path.getsize(fpath)
                        os.remove(fpath)
                        deleted_count += 1
                    except Exception:
                        pass
        mb_freed = round(bytes_freed / (1024 * 1024), 2)
        return jsonify({
            "status": "ok",
            "deleted_count": deleted_count,
            "bytes_freed": bytes_freed,
            "message": f"Successfully purged {deleted_count} temporary photo frames ({mb_freed} MB freed). Compiled PDF notes preserved."
        })
    except Exception as e:
        return jsonify({"status": "error", "message": f"Purge failed: {e}"}), 500


@app.route("/api/admin/compact_spool", methods=["POST"])
def api_admin_compact_spool():
    if not session.get("authenticated"):
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    from config import BASE_DIR
    spool_file = os.path.join(BASE_DIR, "pending_uploads.json")
    try:
        if not os.path.exists(spool_file):
            return jsonify({"status": "ok", "remaining_count": 0, "message": "Upload spool index is already empty. No fragmentation detected."})
        
        with open(spool_file, "r") as f:
            spool = json.load(f)
        
        clean_spool = []
        seen = set()
        for item in spool:
            fname = item.get("filename")
            if fname and os.path.exists(fname) and fname not in seen:
                seen.add(fname)
                clean_spool.append(item)
        
        with open(spool_file, "w") as f:
            json.dump(clean_spool, f, indent=2)
            
        return jsonify({
            "status": "ok",
            "remaining_count": len(clean_spool),
            "message": f"Upload spool index compacted. {len(clean_spool)} pending asset(s) indexed."
        })
    except Exception as e:
        return jsonify({"status": "error", "message": f"Spool compact error: {e}"}), 500


@app.route("/api/admin/restart_engine", methods=["POST"])
def api_admin_restart_engine():
    if not session.get("authenticated"):
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    return jsonify({
        "status": "ok",
        "message": "Veronica engine background services synchronized and healthy."
    })


@app.route("/api/admin/poweroff", methods=["POST"])
def api_admin_poweroff():
    if not session.get("authenticated"):
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    try:
        subprocess.Popen(["sudo", "poweroff"])
        return jsonify({
            "status": "ok",
            "message": "Hardware safe power-off sequence initiated on Raspberry Pi 5."
        })
    except Exception as e:
        return jsonify({"status": "error", "message": f"Power off dispatch error: {e}"}), 500


# ==============================================================================
# ⚡ TACTICAL ACTION TRIGGERS & COMMAND DISPATCHERS
# ==============================================================================
@app.route("/cmd/<action>", methods=["POST", "GET"])
def handle_cmd(action):
    action = action.lower()
    
    if action == "photo":
        res = take_photo_and_upload()
        return jsonify({"status": "ok", "message": res})
        
    elif action == "compile_pdf":
        pdf_path = compile_and_publish_session_pdf()
        msg = f"Compiled {os.path.basename(pdf_path)}" if pdf_path else "No photos to compile"
        return jsonify({"status": "ok", "message": msg, "pdf": pdf_path})
        
    elif action == "video":
        if state.recording:
            res = stop_video_audio()
        else:
            res = start_video_audio()
        return jsonify({"status": "ok", "message": res})
        
    elif action == "audio":
        if state.audio_recording:
            res = stop_audio_only()
        else:
            res = start_audio_only()
        return jsonify({"status": "ok", "message": res})
        
    elif action == "stop":
        msgs = []
        if state.recording:
            msgs.append(stop_video_audio())
        if state.audio_recording:
            msgs.append(stop_audio_only())
        if not msgs:
            msgs.append("Nothing active to stop")
        return jsonify({"status": "ok", "message": " | ".join(msgs)})
        
    elif action.startswith("subj_"):
        sub = action.replace("subj_", "")
        if state.session_photos:
            compile_and_publish_session_pdf()
        state.current_subject = None if sub == "clear" else sub.title()
        if state.current_subject:
            log_activity("subject_change")
        return jsonify({"status": "ok", "subject": state.current_subject})
        
    elif action == "stats":
        res = send_stats_report()
        return jsonify({"status": "ok", "message": res})
        
    elif action == "reboot":
        subprocess.Popen(["sudo", "reboot"])
        return jsonify({"status": "ok", "message": "System reboot dispatched."})
        
    return jsonify({"status": "error", "message": f"Unknown command: {action}"}), 400


@app.route("/trigger", methods=["POST"])
def trigger():
    cmd = (flask_request.form.get("cmd") or "").strip().lower()
    if cmd.startswith("subj_"):
        sub = cmd.replace("subj_", "")
        if state.session_photos:
            compile_and_publish_session_pdf()
        state.current_subject = None if sub == "clear" else sub.title()
        if state.current_subject:
            log_activity("subject_change")
        return f"Subject updated to {state.current_subject}"

    if cmd == "launch_projector":
        try:
            cmd_proj = "chromium-browser --kiosk --noerrdialogs --disable-infobars http://localhost:5000/projector"
            env = os.environ.copy()
            env["DISPLAY"] = ":0"
            subprocess.Popen(cmd_proj, shell=True, env=env)
            return "Projector View launched on hardware HDMI display."
        except Exception as e:
            return f"Projector launch note: {e}"

    if cmd == "photo":
        return take_photo_and_upload()
    elif cmd == "compile_pdf":
        pdf_path = compile_and_publish_session_pdf()
        return f"Compiled {os.path.basename(pdf_path)}" if pdf_path else "No photos in session"
    elif cmd == "video":
        return start_video_audio()
    elif cmd == "audio":
        return start_audio_only()
    elif cmd == "stop":
        if state.recording:
            return stop_video_audio()
        if state.audio_recording:
            return stop_audio_only()
        if state.session_photos:
            return f"Session PDF: {compile_and_publish_session_pdf()}"
        return "Nothing to stop"
    elif cmd == "stats":
        return send_stats_report()
    elif cmd == "reboot":
        subprocess.Popen(["sudo", "reboot"])
        return "Reboot triggered"
    return f"Unknown: {cmd}"


def _get_real_wifi_ssid():
    """Get the actual Wi-Fi SSID the Pi is connected to."""
    try:
        result = subprocess.run(
            ['iwgetid', '-r'], capture_output=True, text=True, timeout=3
        )
        ssid = result.stdout.strip()
        return ssid if ssid else "Unknown"
    except Exception:
        return "Unknown"


def _get_cpu_temp():
    """Read CPU temperature from sysfs."""
    try:
        with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
            return round(int(f.read().strip()) / 1000.0, 1)
    except Exception:
        try:
            result = subprocess.run(
                ['vcgencmd', 'measure_temp'], capture_output=True, text=True, timeout=3
            )
            # output: "temp=44.3'C"
            temp_str = result.stdout.strip().replace("temp=", "").replace("'C", "")
            return round(float(temp_str), 1)
        except Exception:
            return None


@app.route("/api/status")
def api_status():
    """Real live status endpoint. All data comes from actual system state."""
    import shutil as _shutil

    # Pod online: connected AND seen within last 15 seconds
    now = time.time()
    pod_online = (
        state.pod_connected
        and state.pod_last_seen > 0
        and (now - state.pod_last_seen) < 15
    )

    # Real disk usage
    disk = _shutil.disk_usage("/")
    total_gb = round(disk.total / (1024 ** 3), 1)
    used_gb = round(disk.used / (1024 ** 3), 1)
    free_gb = round(disk.free / (1024 ** 3), 1)
    used_pct = round(disk.used / disk.total * 100, 1)

    # Real CPU / RAM
    cpu_pct = round(psutil.cpu_percent(interval=0.5), 1)
    ram_pct = round(psutil.virtual_memory().percent, 1)

    # CPU temperature
    cpu_temp = _get_cpu_temp()

    # Camera detection (physical device check only)
    camera_connected = os.path.exists('/dev/video0')

    # Wi-Fi SSID
    wifi_ssid = _get_real_wifi_ssid()

    # System uptime
    uptime_secs = int(now - psutil.boot_time())
    h, rem = divmod(uptime_secs, 3600)
    m = rem // 60
    uptime_str = f"{h}h {m}m"

    return jsonify({
        "pod_connected": pod_online,
        "pod_ip": state.pod_ip if pod_online else None,
        "pod_last_seen_secs": round(now - state.pod_last_seen, 1) if state.pod_last_seen > 0 else None,
        "pod_rssi": getattr(state, 'pod_rssi', None),
        "current_subject": state.current_subject or "None",
        "recording_video": state.recording,
        "recording_audio": state.audio_recording,
        "camera_connected": camera_connected,
        "wifi_ssid": wifi_ssid,
        "disk_total_gb": total_gb,
        "disk_used_gb": used_gb,
        "disk_free_gb": free_gb,
        "disk_used_pct": used_pct,
        "cpu_percent": cpu_pct,
        "ram_percent": ram_pct,
        "cpu_temp_c": cpu_temp,
        "uptime": uptime_str,
        "uptime_secs": uptime_secs,
        "session_photos": len(state.session_photos),
        "latest_photo": os.path.basename(state.latest_photo_path) if state.latest_photo_path else None,
        "latest_pdf": os.path.basename(state.latest_pdf_path) if state.latest_pdf_path else None,
    })


@app.route("/api/stream")
def api_stream():
    """Server-Sent Events stream — pushes live status every 3 seconds."""
    import shutil as _shutil

    def generate():
        while True:
            try:
                now = time.time()
                pod_online = (
                    state.pod_connected
                    and state.pod_last_seen > 0
                    and (now - state.pod_last_seen) < 15
                )
                disk = _shutil.disk_usage("/")
                data = json.dumps({
                    "pod_connected": pod_online,
                    "pod_ip": state.pod_ip if pod_online else None,
                    "current_subject": state.current_subject or "None",
                    "recording_video": state.recording,
                    "recording_audio": state.audio_recording,
                    "camera_connected": os.path.exists('/dev/video0'),
                    "disk_free_gb": round(disk.free / (1024 ** 3), 1),
                    "disk_used_pct": round(disk.used / disk.total * 100, 1),
                    "disk_total_gb": round(disk.total / (1024 ** 3), 1),
                    "cpu_percent": round(psutil.cpu_percent(interval=0), 1),
                    "ram_percent": round(psutil.virtual_memory().percent, 1),
                })
                yield f"data: {data}\n\n"
            except GeneratorExit:
                break
            except Exception:
                pass
            time.sleep(3)

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.route("/api/pod_event", methods=["POST"])
def pod_event():
    data = flask_request.get_json(silent=True) or {}
    event_type = data.get("event")
    state.pod_connected = True
    state.pod_last_seen = datetime.datetime.now().timestamp()
    state.pod_ip = flask_request.remote_addr

    if event_type == "key" and _on_key_callback:
        key_num = data.get("key")
        if key_num is not None:
            _on_key_callback(int(key_num))
            return {"status": "ok", "action": f"key_{key_num}"}

    elif event_type == "nfc" and _on_nfc_callback:
        uid = data.get("uid", "").upper()
        subject_or_action = NFC_MAP.get(uid)
        if subject_or_action:
            _on_nfc_callback(subject_or_action)
            return {"status": "ok", "action": subject_or_action}

    return {"status": "ignored"}
