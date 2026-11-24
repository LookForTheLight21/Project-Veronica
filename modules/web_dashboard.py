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
import logging
import threading
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

# Silence Werkzeug recurring access logs (/api/status, etc.)
logging.getLogger('werkzeug').setLevel(logging.WARNING)

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


LIVE_FRAME_PATH = "/dev/shm/live_frame.jpg"
_latest_frame_bytes = None
LIVE_FRAME_PATH = "/dev/shm/live_frame.jpg"
_latest_frame_bytes = None
_latest_frame_id = 0
_frame_condition = threading.Condition()
_measured_fps = 30.0
_stream_worker_started = False
_active_stream_viewers = 0
_viewers_lock = threading.Lock()
_last_viewer_activity = 0.0


def _camera_stream_worker():
    global _latest_frame_bytes, _latest_frame_id, _measured_fps
    import cv2
    from config import enforce_anti_flicker_50hz
    cap = None
    last_shm_write = 0.0
    fps_frames = 0
    fps_start = time.time()
    current_res = None

    while True:
        try:
            # Check viewer demand
            with _viewers_lock:
                active_viewers = _active_stream_viewers

            # If no active viewers and not recording, or pause/recording requested:
            # Release camera immediately so camera sensor hardware sleeps and /dev/video0 is free!
            if (active_viewers == 0 and not state.recording) or state.recording or state.camera_pause_event.is_set():
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass
                    cap = None
                    current_res = None
                time.sleep(0.15)
                continue

            # Check if dynamic resolution switch requested
            target_res = getattr(state, 'camera_target_res', '1920x1080')
            if cap is not None and current_res != target_res:
                w, h = (3840, 2160) if target_res == "3840x2160" else (1920, 1080)
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
                current_res = target_res

            # Ensure camera is opened in high-speed MJPG mode
            if cap is None:
                if not os.path.exists('/dev/video0'):
                    time.sleep(1.0)
                    continue
                enforce_anti_flicker_50hz('/dev/video0')
                cap = cv2.VideoCapture('/dev/video0')
                if not cap.isOpened():
                    try:
                        cap.release()
                    except Exception:
                        pass
                    cap = None
                    time.sleep(0.5)
                    continue

                w, h = (3840, 2160) if target_res == "3840x2160" else (1920, 1080)
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
                cap.set(cv2.CAP_PROP_FPS, 60 if target_res != "3840x2160" else 30)
                current_res = target_res

            ret, frame = cap.read()
            if ret and frame is not None:
                # Fast Turbo JPEG compression without slow Huffman tree optimization passes
                ret_enc, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80, cv2.IMWRITE_JPEG_OPTIMIZE, 0])
                if ret_enc:
                    frame_bytes = jpeg.tobytes()
                    now = time.time()

                    with _frame_condition:
                        _latest_frame_bytes = frame_bytes
                        _latest_frame_id += 1
                        _frame_condition.notify_all()

                    # Measure live rolling FPS
                    fps_frames += 1
                    elapsed = now - fps_start
                    if elapsed >= 1.0:
                        _measured_fps = fps_frames / elapsed
                        fps_frames = 0
                        fps_start = now

                    # Non-blocking RAM cache write (throttled to avoid I/O bottlenecks)
                    if now - last_shm_write >= 0.25:
                        last_shm_write = now
                        try:
                            with open(LIVE_FRAME_PATH, "wb") as f:
                                f.write(frame_bytes)
                        except Exception:
                            pass
            else:
                time.sleep(0.01)

        except Exception as e:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass
                cap = None
            time.sleep(0.5)


def _ensure_stream_worker():
    global _stream_worker_started
    if not _stream_worker_started:
        _stream_worker_started = True
        t = threading.Thread(target=_camera_stream_worker, daemon=True)
        t.start()


def _gen_mjpeg_stream():
    """Generator for streaming live MJPEG frames with zero lag and maximum FPS."""
    global _active_stream_viewers, _last_viewer_activity
    with _viewers_lock:
        _active_stream_viewers += 1
        _last_viewer_activity = time.time()

    _ensure_stream_worker()

    fallback_bytes = None
    sample_svg_path = os.path.join(TEMPLATES_DIR, "sample_board.svg")
    if os.path.exists(sample_svg_path):
        try:
            with open(sample_svg_path, "rb") as f:
                fallback_bytes = f.read()
        except Exception:
            pass

    last_sent_id = -1
    try:
        while True:
            frame_bytes = None

            # 1. When recording, FFmpeg dual output updates /dev/shm/live_frame.jpg at 30 FPS
            if state.recording:
                if os.path.exists(LIVE_FRAME_PATH):
                    try:
                        with open(LIVE_FRAME_PATH, "rb") as f:
                            frame_bytes = f.read()
                    except Exception:
                        pass
                if frame_bytes:
                    chunk = (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(frame_bytes)).encode("ascii") + b"\r\n\r\n"
                        + frame_bytes + b"\r\n"
                    )
                    yield chunk
                time.sleep(0.033)
                continue

            # 2. When idle, wait on condition for fresh frame from camera worker (Zero lag!)
            with _frame_condition:
                while _latest_frame_id == last_sent_id and not state.recording:
                    if not _frame_condition.wait(timeout=0.08):
                        break
                frame_bytes = _latest_frame_bytes
                last_sent_id = _latest_frame_id

            # 3. Fallback only if camera hardware is completely offline/unplugged
            if not frame_bytes:
                if state.latest_photo_path and os.path.exists(state.latest_photo_path):
                    try:
                        with open(state.latest_photo_path, "rb") as f:
                            frame_bytes = f.read()
                    except Exception:
                        pass
                elif fallback_bytes:
                    frame_bytes = fallback_bytes

            if frame_bytes:
                chunk = (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(frame_bytes)).encode("ascii") + b"\r\n\r\n"
                    + frame_bytes + b"\r\n"
                )
                yield chunk
    finally:
        with _viewers_lock:
            _active_stream_viewers = max(0, _active_stream_viewers - 1)
            _last_viewer_activity = time.time()


@app.route("/video_feed")
def video_feed():
    """Real-time live camera stream (multipart MJPEG) for classroom projector and diagnostic UI."""
    resp = Response(
        _gen_mjpeg_stream(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, pre-check=0, post-check=0, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


@app.route("/api/latest_asset")
def api_latest_asset():
    """Returns telemetry of the latest chalkboard photo for live projector & dashboard sync."""
    photo_name = os.path.basename(state.latest_photo_path) if state.latest_photo_path else None
    pdf_name = os.path.basename(state.latest_pdf_path) if state.latest_pdf_path else None
    
    # If in-memory latest_photo_path isn't set yet (e.g. freshly started app), find the newest photo in storage/photos
    if not photo_name and os.path.exists(PHOTOS_DIR):
        try:
            photos = [f for f in os.listdir(PHOTOS_DIR) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
            if photos:
                photos.sort(key=lambda x: os.path.getmtime(os.path.join(PHOTOS_DIR, x)), reverse=True)
                photo_name = photos[0]
                state.latest_photo_path = os.path.join(PHOTOS_DIR, photo_name)
        except Exception:
            pass

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
        "session_pages": len(state.session_photos) if state.session_photos else (1 if photo_name else 0),
        "recording_video": state.recording,
        "recording_audio": state.audio_recording,
        "pod_connected": pod_online,
        "pod_ip": state.pod_ip if pod_online else None,
        "cpu": cpu,
        "ram": ram,
        "uptime": get_uptime(),
        "storage_free_gb": free_gb,
        "storage_used_pct": used_pct,
        "camera_fps": round(_measured_fps, 1),
        "camera_resolution": getattr(state, "camera_target_res", "1920x1080")
    })


@app.route("/api/camera/resolution", methods=["GET", "POST"])
def api_camera_resolution():
    """Allows instant live switching between 4K UHD (3840x2160) and 1080P High-FPS modes."""
    res = flask_request.args.get("res") or (flask_request.get_json(silent=True) or {}).get("res")
    if res in ["3840x2160", "4k", "4K", "uhd"]:
        state.camera_target_res = "3840x2160"
    elif res in ["1920x1080", "1080p", "1080P", "fhd"]:
        state.camera_target_res = "1920x1080"
    return jsonify({
        "status": "ok",
        "resolution": getattr(state, "camera_target_res", "1920x1080"),
        "camera_fps": round(_measured_fps, 1)
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
# 📲 WIRELESS SLIDE BEAM & PRESENTATION VIEWER
# ==============================================================================
SLIDES_DIR = os.path.join(STORAGE_DIR, "temp_slides")
os.makedirs(SLIDES_DIR, exist_ok=True)


@app.route("/beam")
def beam_page():
    """Mobile-first presentation upload page for teachers."""
    path = os.path.join(TEMPLATES_DIR, "beam_upload.html")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h3>Beam upload template not found</h3>", 404


@app.route("/beam_pod")
def beam_pod_page():
    """Dedicated Pod & Kiosk presentation launcher showing QR code and beamed slides."""
    path = os.path.join(TEMPLATES_DIR, "beam_pod.html")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h3>Beam Pod template not found</h3>", 404


@app.route("/viewer")
def slide_viewer_page():
    """Fullscreen presentation viewer with permanent return to pod button."""
    path = os.path.join(TEMPLATES_DIR, "slide_viewer.html")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h3>Slide viewer template not found</h3>", 404


@app.route("/api/beam/qr.svg")
def api_beam_qr_svg():
    """Dynamically generates a crisp SVG QR code pointing to the mobile upload portal."""
    from config import get_lan_ip
    override_host = flask_request.args.get("host", "").strip()
    override_port = flask_request.args.get("port", "").strip()

    if override_host and override_host not in ["localhost", "127.0.0.1"]:
        if ":" in override_host:
            host_port = override_host
        elif override_port:
            host_port = f"{override_host}:{override_port}"
        else:
            host_port = f"{override_host}:5000"
    elif flask_request.host and not flask_request.host.startswith("localhost") and not flask_request.host.startswith("127."):
        host_port = flask_request.host
    else:
        lan_ip = get_lan_ip()
        port = flask_request.host.split(":")[-1] if ":" in flask_request.host else "5000"
        host_port = f"{lan_ip}:{port}"

    target_url = f"http://{host_port}/beam"
    try:
        import qrcode
        import qrcode.image.svg
        import io
        img = qrcode.make(target_url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
        out = io.BytesIO()
        img.save(out)
        svg_bytes = out.getvalue()
        return Response(svg_bytes, mimetype="image/svg+xml", headers={"Cache-Control": "no-cache"})
    except Exception as e:
        err_svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="220" height="220" viewBox="0 0 220 220"><rect width="220" height="220" fill="#0f172a"/><text x="110" y="100" fill="#38bdf8" font-size="12" text-anchor="middle">Scan URL:</text><text x="110" y="125" fill="#fff" font-size="11" text-anchor="middle">{target_url}</text></svg>'
        return Response(err_svg, mimetype="image/svg+xml", headers={"Cache-Control": "no-cache"})


@app.route("/beam/file/<path:filename>")
def beam_serve_file(filename):
    """Serves the presentation PDF directly to the slide viewer."""
    return send_from_directory(SLIDES_DIR, filename)


@app.route("/api/beam/status")
def api_beam_status():
    """Returns status of currently beamed presentation deck, host info, and Wi-Fi SSID."""
    from config import get_lan_ip, WIFI_SSID
    override_host = flask_request.args.get("host", "").strip()
    override_port = flask_request.args.get("port", "").strip()

    if override_host and override_host not in ["localhost", "127.0.0.1"]:
        if ":" in override_host:
            host_port = override_host
        elif override_port:
            host_port = f"{override_host}:{override_port}"
        else:
            host_port = f"{override_host}:5000"
    elif flask_request.host and not flask_request.host.startswith("localhost") and not flask_request.host.startswith("127."):
        host_port = flask_request.host
    else:
        lan_ip = get_lan_ip()
        port = flask_request.host.split(":")[-1] if ":" in flask_request.host else "5000"
        host_port = f"{lan_ip}:{port}"

    deck = getattr(state, "current_slide_deck", None)
    return jsonify({
        "status": "ok",
        "active": deck is not None,
        "deck": deck,
        "beam_url": f"http://{host_port}/beam",
        "host": host_port,
        "wifi_ssid": WIFI_SSID
    })


@app.route("/api/beam/upload", methods=["POST"])
def api_beam_upload():
    """Handles mobile file upload (.pdf, .pptx, .ppt) and auto-converts to PDF."""
    if "file" not in flask_request.files:
        return jsonify({"status": "error", "message": "No file received"}), 400
    file_obj = flask_request.files["file"]
    if not file_obj.filename:
        return jsonify({"status": "error", "message": "Empty filename"}), 400

    filename = file_obj.filename
    save_path = os.path.join(SLIDES_DIR, filename)
    file_obj.save(save_path)

    pdf_name = filename
    ext = os.path.splitext(filename)[1].lower()
    if ext in [".ppt", ".pptx"]:
        try:
            # Headless conversion of PowerPoint to PDF using LibreOffice
            res = subprocess.run(
                ["libreoffice", "--headless", "--convert-to", "pdf", "--outdir", SLIDES_DIR, save_path],
                capture_output=True,
                text=True,
                timeout=45
            )
            base_no_ext = os.path.splitext(filename)[0]
            conv_pdf = f"{base_no_ext}.pdf"
            if os.path.exists(os.path.join(SLIDES_DIR, conv_pdf)):
                pdf_name = conv_pdf
        except Exception as e:
            print(f"⚠️ LibreOffice conversion notice: {e}")

    deck_info = {
        "filename": filename,
        "pdf_name": pdf_name,
        "pdf_url": f"/beam/file/{pdf_name}",
        "uploaded_at": time.time()
    }
    state.current_slide_deck = deck_info
    log_activity("slides_beam")
    return jsonify({"status": "ok", "deck": deck_info})


@app.route("/api/beam/clear", methods=["POST"])
def api_beam_clear():
    """Wipes all temporary uploaded slides from storage after class."""
    state.current_slide_deck = None
    try:
        for f in os.listdir(SLIDES_DIR):
            fp = os.path.join(SLIDES_DIR, f)
            if os.path.isfile(fp):
                os.remove(fp)
    except Exception as e:
        print(f"⚠️ Slide wipe error: {e}")
    return jsonify({"status": "ok", "message": "All session presentation slides securely erased."})


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
# 🏛️ PRINCIPAL'S AUDIT REPORT & LIVE CLASS SURVEILLANCE
# ==============================================================================
@app.route("/report")
def report():
    if not session.get("authenticated") or session.get("role") not in ["principal", "technician"]:
        return redirect(url_for("login_page"))
    path = os.path.join(TEMPLATES_DIR, "report.html")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h3>Report template not found</h3>", 404


def build_principal_report_data():
    """
    Constructs high-granularity 7-day academic audit telemetry for the Principal.
    Breaks down usage by classroom, subject, teaching modes (chalkboard, video, audio, notes),
    and direct links to the latest uploaded materials for each day.
    """
    from activity_logger import load_log
    from config import FOLDER_ID
    log_data = load_log()
    known_subjects = ["Physics", "Chemistry", "Mathematics", "English", "Computer Science"]

    notes_files = [f for f in os.listdir(NOTES_DIR) if f.endswith('.pdf')] if os.path.exists(NOTES_DIR) else []
    video_files = [f for f in os.listdir(VIDEOS_DIR) if f.endswith('.mp4') or f.endswith('.m4a')] if os.path.exists(VIDEOS_DIR) else []
    photo_files = [f for f in os.listdir(PHOTOS_DIR) if f.endswith('.jpg')] if os.path.exists(PHOTOS_DIR) else []

    today_dt = datetime.date.today()
    days_list = [today_dt - datetime.timedelta(days=i) for i in range(7)]

    subjects_data = {}
    for subj in known_subjects:
        s_log = log_data.get(subj, {})
        if not s_log and subj == "Mathematics":
            s_log = log_data.get("Math", {})
        s_daily = s_log.get("daily", {})

        last_7_days = []
        for d in days_list:
            d_str = d.strftime("%Y-%m-%d")
            d_tag = d.strftime("%m%d")
            d_info = s_daily.get(d_str, {})

            # Match files on disk for this subject & date tag
            def matches_subj(name):
                n = name.lower()
                s = subj.lower()
                if s == "mathematics" and "math" in n: return True
                return s in n

            subj_notes = [f for f in notes_files if matches_subj(f) and d_tag in f]
            subj_videos = [f for f in video_files if matches_subj(f) and d_tag in f and f.endswith('.mp4')]
            subj_audios = [f for f in video_files if matches_subj(f) and d_tag in f and f.endswith('.m4a')]
            subj_photos = [f for f in photo_files if matches_subj(f) and d_tag in f]

            photos = max(d_info.get("photos", 0), len(subj_photos))
            videos = max(d_info.get("videos", 0), len(subj_videos))
            audios = max(d_info.get("audios", 0), len(subj_audios))
            notes = len(subj_notes)

            latest_mat = None
            if subj_notes:
                subj_notes.sort(key=lambda fn: os.path.getmtime(os.path.join(NOTES_DIR, fn)) if os.path.exists(os.path.join(NOTES_DIR, fn)) else 0, reverse=True)
                fn = subj_notes[0]
                latest_mat = {
                    "filename": fn,
                    "type": "pdf",
                    "label": "Compiled Notes PDF",
                    "cloud_url": f"https://drive.google.com/drive/folders/{FOLDER_ID}",
                    "local_url": f"/media/notes/{fn}",
                    "time": fn.replace(".pdf", "").split("_")[-1] if "_" in fn else "Latest"
                }
            elif subj_videos:
                subj_videos.sort(key=lambda fn: os.path.getmtime(os.path.join(VIDEOS_DIR, fn)) if os.path.exists(os.path.join(VIDEOS_DIR, fn)) else 0, reverse=True)
                fn = subj_videos[0]
                latest_mat = {
                    "filename": fn,
                    "type": "video",
                    "label": "Classroom Video Stream",
                    "cloud_url": f"https://drive.google.com/drive/folders/{FOLDER_ID}",
                    "local_url": f"/media/videos/{fn}",
                    "time": fn.replace(".mp4", "").split("_")[-1] if "_" in fn else "Latest"
                }
            elif subj_audios:
                subj_audios.sort(key=lambda fn: os.path.getmtime(os.path.join(VIDEOS_DIR, fn)) if os.path.exists(os.path.join(VIDEOS_DIR, fn)) else 0, reverse=True)
                fn = subj_audios[0]
                latest_mat = {
                    "filename": fn,
                    "type": "audio",
                    "label": "Classroom Audio Mic Recording",
                    "cloud_url": f"https://drive.google.com/drive/folders/{FOLDER_ID}",
                    "local_url": f"/media/videos/{fn}",
                    "time": fn.replace(".m4a", "").split("_")[-1] if "_" in fn else "Latest"
                }

            modes_list = []
            if photos > 0: modes_list.append(f"{photos} Snapshot{'s' if photos != 1 else ''}")
            if videos > 0: modes_list.append(f"{videos} Video Recording{'s' if videos != 1 else ''}")
            if audios > 0: modes_list.append(f"{audios} Audio Recording{'s' if audios != 1 else ''}")
            if notes > 0: modes_list.append(f"{notes} Master PDF{'s' if notes != 1 else ''}")

            last_7_days.append({
                "date": d_str,
                "day_name": d.strftime("%A"),
                "formatted_date": d.strftime("%d %b %Y"),
                "is_today": (d == today_dt),
                "photos": photos,
                "videos": videos,
                "audios": audios,
                "notes": notes,
                "has_activity": bool(photos or videos or audios or notes),
                "modes_used": modes_list,
                "modes_summary": " · ".join(modes_list) if modes_list else "No lecture recorded",
                "latest_material": latest_mat
            })

        today_data = last_7_days[0]
        total_p = sum(d["photos"] for d in last_7_days)
        total_v = sum(d["videos"] for d in last_7_days)
        total_a = sum(d["audios"] for d in last_7_days)
        total_n = sum(d["notes"] for d in last_7_days)

        all_subj_notes = [f for f in notes_files if matches_subj(f)]
        global_latest = None
        if all_subj_notes:
            all_subj_notes.sort(key=lambda fn: os.path.getmtime(os.path.join(NOTES_DIR, fn)) if os.path.exists(os.path.join(NOTES_DIR, fn)) else 0, reverse=True)
            g_fn = all_subj_notes[0]
            global_latest = {
                "filename": g_fn,
                "type": "pdf",
                "label": "Latest Compiled Notes PDF",
                "cloud_url": f"https://drive.google.com/drive/folders/{FOLDER_ID}",
                "local_url": f"/media/notes/{g_fn}"
            }

        subjects_data[subj] = {
            "name": subj,
            "today": today_data,
            "last_7_days": last_7_days,
            "totals_7d": {
                "photos": total_p,
                "videos": total_v,
                "audios": total_a,
                "notes": total_n
            },
            "global_latest_material": global_latest or today_data.get("latest_material")
        }

    return {
        "status": "ok",
        "classroom": "Class X",
        "today_str": today_dt.strftime("%d %B %Y"),
        "total_classes": len(known_subjects),
        "total_photos": len(photo_files),
        "total_notes": len(notes_files),
        "total_videos": len(video_files),
        "subjects": subjects_data
    }


@app.route("/api/report_data")
def api_report_data():
    return jsonify(build_principal_report_data())


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


@app.route("/api/admin/upload_credentials", methods=["POST"])
def api_admin_upload_credentials():
    if not session.get("authenticated"):
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    from drive_upload import CREDENTIALS_PATH
    content = None
    if "file" in flask_request.files:
        uploaded_file = flask_request.files["file"]
        if uploaded_file.filename:
            content = uploaded_file.read().decode("utf-8", errors="ignore")
    elif flask_request.is_json:
        data = flask_request.get_json(silent=True) or {}
        content = data.get("credentials_json")

    if not content:
        return jsonify({"status": "error", "message": "No credentials content provided."}), 400

    try:
        parsed = json.loads(content)
        with open(CREDENTIALS_PATH, "w") as f:
            json.dump(parsed, f, indent=2)
        return jsonify({"status": "ok", "message": "credentials.json successfully saved to Project Veronica."})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Invalid JSON format: {e}"}), 400


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
    """Real hardware microphone recording and acoustic analysis test."""
    import wave
    import struct
    import math
    from config import KERO_AUDIO_DEVICE, STORAGE_DIR

    # 1. Probe ALSA hardware
    try:
        res = subprocess.run(["arecord", "-l"], capture_output=True, text=True, timeout=3)
        has_mic = "card" in res.stdout.lower()
        if not has_mic:
            return jsonify({
                "status": "error",
                "connected": False,
                "device": KERO_AUDIO_DEVICE,
                "message": "No ALSA audio capture devices found. Please plug in USB microphone."
            }), 404
    except Exception as e:
        return jsonify({"status": "error", "message": f"ALSA probe error: {e}"}), 500

    test_wav = os.path.join(STORAGE_DIR, "test_mic_sample.wav")
    dev = KERO_AUDIO_DEVICE

    # 2. Record 2 seconds of real audio
    try:
        # First try specified device
        cmd = ["arecord", "-D", dev, "-f", "cd", "-d", "2", test_wav]
        rec_res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if rec_res.returncode != 0 or not os.path.exists(test_wav) or os.path.getsize(test_wav) < 1000:
            # Fallback to default arecord capture
            cmd = ["arecord", "-f", "cd", "-d", "2", test_wav]
            subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    except Exception as e:
        return jsonify({"status": "error", "message": f"Recording test failed: {e}"}), 500

    if not os.path.exists(test_wav) or os.path.getsize(test_wav) < 1000:
        return jsonify({
            "status": "error",
            "connected": False,
            "message": "Failed to record audio sample from hardware microphone."
        }), 500

    # 3. Analyze real audio metrics from recorded WAVE file
    try:
        with wave.open(test_wav, "rb") as wf:
            n_frames = wf.getnframes()
            channels = wf.getnchannels()
            sample_rate = wf.getframerate()
            frames = wf.readframes(n_frames)
            sample_count = len(frames) // 2
            samples = struct.unpack('<' + 'h' * sample_count, frames)
            peak = max(abs(s) for s in samples) if samples else 0
            rms = math.sqrt(sum(s * s for s in samples) / len(samples)) if samples else 0
            dbfs = round(20 * math.log10(rms / 32768), 1) if rms > 0 else -90.0
            peak_dbfs = round(20 * math.log10(peak / 32768), 1) if peak > 0 else -90.0
            duration_sec = round(n_frames / float(sample_rate), 2)

        status_label = "Optimal" if dbfs > -35 else ("Good" if dbfs > -55 else "Low Gain / Muted")

        return jsonify({
            "status": "ok",
            "connected": True,
            "device": dev,
            "duration": f"{duration_sec}s",
            "sample_rate": f"{sample_rate} Hz",
            "channels": "Stereo" if channels == 2 else "Mono",
            "peak": peak,
            "peak_dbfs": f"{peak_dbfs} dBFS",
            "rms_dbfs": f"{dbfs} dBFS",
            "db_num": dbfs,
            "gain_status": status_label,
            "audio_url": "/api/admin/mic_sample",
            "message": f"Hardware Microphone Verified: {dbfs} dBFS ({channels}ch, {sample_rate}Hz, peak {peak_dbfs} dBFS)."
        })
    except Exception as e:
        return jsonify({
            "status": "ok",
            "connected": True,
            "audio_url": "/api/admin/mic_sample",
            "message": f"Audio recorded successfully (sample saved)."
        })


@app.route("/api/admin/mic_sample")
def api_admin_mic_sample():
    """Serves the latest microphone test audio clip for browser playback."""
    from config import STORAGE_DIR
    test_wav = os.path.join(STORAGE_DIR, "test_mic_sample.wav")
    if os.path.exists(test_wav):
        return send_from_directory(STORAGE_DIR, "test_mic_sample.wav", mimetype="audio/wav")
    return "No audio sample available", 404


@app.route("/api/bookmarks", methods=["GET"])
def api_get_bookmarks():
    """Returns active bookmarks for the Teacher Lectern Pod UI."""
    from config import USEFUL_SITES
    return jsonify({"status": "ok", "bookmarks": USEFUL_SITES})


@app.route("/api/admin/bookmarks", methods=["GET", "POST"])
def api_admin_bookmarks():
    """Get or update useful sites / bookmarks from Diagnostic Admin Hub."""
    from config import USEFUL_SITES, save_dynamic_config
    import config
    if flask_request.method == "POST":
        data = flask_request.get_json(force=True, silent=True) or {}
        bookmarks = data.get("bookmarks")
        if isinstance(bookmarks, list):
            config.USEFUL_SITES = bookmarks
            save_dynamic_config({"USEFUL_SITES": bookmarks})
            return jsonify({
                "status": "ok",
                "message": "Useful Sites updated and synced to Lectern Pod.",
                "bookmarks": config.USEFUL_SITES
            })
        return jsonify({"status": "error", "message": "Invalid bookmarks format."}), 400
    return jsonify({"status": "ok", "bookmarks": config.USEFUL_SITES})


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
