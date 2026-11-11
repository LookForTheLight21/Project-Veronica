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
import json
import socket
import datetime
import subprocess
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

    return jsonify({
        "subject": state.current_subject or "General Session",
        "latest_photo": photo_name,
        "latest_photo_url": f"/media/photos/{photo_name}" if photo_name else "/sample_board.svg",
        "latest_pdf": pdf_name,
        "session_pages": len(state.session_photos),
        "recording_video": state.recording,
        "recording_audio": state.audio_recording,
        "pod_connected": state.pod_connected,
        "pod_ip": state.pod_ip,
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
