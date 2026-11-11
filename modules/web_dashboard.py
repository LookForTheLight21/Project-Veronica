"""
Flask Web Dashboard & Classroom Projector View for Project Veronica FINAL.
Features:
  - /               : Veronica Command Center dashboard
  - /projector      : Fullscreen High-Contrast Projector View for Back-Row Students
  - /api/latest_asset: Real-time JSON telemetry for projector auto-update
  - /media/<folder>/<filename>: Direct local offline asset server
  - /report         : Principal's Activity Report
  - /report/download: Download JSON activity log
"""
import os
import json
import socket
import datetime
import subprocess
import psutil
from flask import Flask, Response, send_from_directory, jsonify, request as flask_request

import state
from activity_logger import load_log, log_activity
from config import NFC_MAP, STORAGE_DIR, PHOTOS_DIR, NOTES_DIR, VIDEOS_DIR
from camera import (
    take_photo_and_upload,
    compile_and_publish_session_pdf,
    start_video_audio,
    stop_video_audio,
    start_audio_only,
    stop_audio_only,
)
from system_utils import get_storage_usage, get_uptime, send_stats_report

app = Flask(__name__)

# Callback holders for event dispatching from HTTP fallback
_on_key_callback = None
_on_nfc_callback = None

def register_pod_callbacks(on_key, on_nfc):
    global _on_key_callback, _on_nfc_callback
    _on_key_callback = on_key
    _on_nfc_callback = on_nfc


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


@app.route("/api/latest_asset")
def api_latest_asset():
    """Returns telemetry of the latest chalkboard photo for live projector sync."""
    photo_name = os.path.basename(state.latest_photo_path) if state.latest_photo_path else None
    pdf_name = os.path.basename(state.latest_pdf_path) if state.latest_pdf_path else None
    return jsonify({
        "subject": state.current_subject or "General Session",
        "latest_photo": photo_name,
        "latest_photo_url": f"/media/photos/{photo_name}" if photo_name else None,
        "latest_pdf": pdf_name,
        "session_pages": len(state.session_photos),
        "recording_video": state.recording,
        "recording_audio": state.audio_recording,
        "pod_connected": state.pod_connected
    })


# ==============================================================================
# 📽️ CLASSROOM PROJECTOR VIEW (High-Contrast for Back-Row Students)
# ==============================================================================
@app.route("/projector")
def projector_view():
    """
    Dedicated fullscreen high-contrast display for ceiling projectors.
    Enlarges fine chalkboard derivations so students in the back rows can read clearly.
    """
    return """
    <!doctype html>
    <html lang="en">
    <head>
        <meta charset="utf-8"/>
        <meta name="viewport" content="width=device-width, initial-scale=1"/>
        <title>Veronica — Classroom Projector</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body {
                font-family: 'Inter', sans-serif;
                background-color: #000000;
                color: #ffffff;
                height: 100vh;
                display: flex;
                flex-direction: column;
                overflow: hidden;
            }
            /* High-Visibility Header */
            .proj-header {
                height: 58px;
                background: #0d1117;
                border-bottom: 2px solid #30363d;
                display: flex;
                align-items: center;
                justify-content: space-between;
                padding: 0 32px;
                font-size: 18px;
                font-weight: 700;
                letter-spacing: 0.5px;
            }
            .subj-pill {
                background: #1f6feb;
                color: #ffffff;
                padding: 6px 18px;
                border-radius: 20px;
                font-size: 16px;
                text-transform: uppercase;
                letter-spacing: 1px;
            }
            .page-counter {
                color: #58a6ff;
                font-family: monospace;
                font-size: 16px;
            }
            .clock {
                font-family: monospace;
                color: #8b949e;
                font-size: 16px;
            }
            /* High-Contrast Canvas */
            .proj-stage {
                flex-grow: 1;
                display: flex;
                align-items: center;
                justify-content: center;
                background: #000000;
                padding: 16px;
                position: relative;
            }
            .board-img {
                max-width: 100%;
                max-height: 100%;
                object-fit: contain;
                border-radius: 8px;
                box-shadow: 0 0 40px rgba(0,0,0,0.8);
                transition: opacity 0.3s ease;
            }
            .standby-box {
                text-align: center;
                color: #8b949e;
            }
            .standby-title {
                font-size: 38px;
                font-weight: 700;
                color: #f0f6fc;
                margin-bottom: 12px;
            }
            .standby-desc {
                font-size: 18px;
                line-height: 1.6;
            }
        </style>
    </head>
    <body>
        <div class="proj-header">
            <div style="display:flex; align-items:center; gap:16px;">
                <span class="subj-pill" id="disp-subj">CLASSROOM READY</span>
                <span class="page-counter" id="disp-page">No Board Active</span>
            </div>
            <div class="clock" id="disp-clock">00:00:00</div>
        </div>

        <div class="proj-stage" id="stage">
            <div class="standby-box" id="standby">
                <div class="standby-title">Project Veronica</div>
                <div class="standby-desc">
                    Tap NFC Teacher Card or press <b style="color:#58a6ff;">Key 1 (Photo)</b> to project the chalkboard.
                </div>
            </div>
            <img id="board" class="board-img" style="display:none;" alt="Live Chalkboard Projection"/>
        </div>

        <script>
        function updateClock() {
            document.getElementById('disp-clock').innerText = new Date().toLocaleTimeString('en-US', {hour12: false});
        }
        setInterval(updateClock, 1000);
        updateClock();

        let currentPhotoUrl = null;

        function syncProjector() {
            fetch('/api/latest_asset')
            .then(res => res.json())
            .then(data => {
                document.getElementById('disp-subj').innerText = data.subject;
                if (data.session_pages > 0) {
                    document.getElementById('disp-page').innerText = `Board Derivation [Page ${data.session_pages}]`;
                } else {
                    document.getElementById('disp-page').innerText = 'Ready for Lecture';
                }

                if (data.latest_photo_url && data.latest_photo_url !== currentPhotoUrl) {
                    currentPhotoUrl = data.latest_photo_url;
                    const img = document.getElementById('board');
                    img.src = data.latest_photo_url + '?t=' + Date.now();
                    img.onload = () => {
                        img.style.display = 'block';
                        document.getElementById('standby').style.display = 'none';
                    };
                }
            })
            .catch(() => {});
        }

        // Poll every 2 seconds for new chalkboard photos
        setInterval(syncProjector, 2000);
        syncProjector();
        </script>
    </body>
    </html>
    """


# ==============================================================================
# 🎛️ COMMAND CENTER WEB DASHBOARD
# ==============================================================================
@app.route("/")
def dashboard():
    with state.state_lock:
        status_text = "System Idle"
        status_color = "#3fb950"
        pulse_css = ""

        if state.recording:
            status_text = "LIVE: Video Feed Active"
            status_color = "#ff4b82"
            pulse_css = "animation: pulse-red 2s infinite;"
        elif state.audio_recording:
            status_text = "LIVE: Audio Feed Active"
            status_color = "#f1fa8c"
            pulse_css = "animation: pulse-yellow 2s infinite;"

        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        used_pct, free_gb2, total_gb = get_storage_usage()

        photo_files = sorted(os.listdir(PHOTOS_DIR), reverse=True) if os.path.exists(PHOTOS_DIR) else []
        video_files = sorted(os.listdir(VIDEOS_DIR), reverse=True) if os.path.exists(VIDEOS_DIR) else []
        pdf_files   = sorted(os.listdir(NOTES_DIR), reverse=True) if os.path.exists(NOTES_DIR) else []

        last_photo = photo_files[0] if photo_files else "No assets detected"
        last_video = video_files[0] if video_files else "No assets detected"
        last_pdf   = pdf_files[0] if pdf_files else "No PDF compiled"

        uptime_str = get_uptime()
        hostname = socket.gethostname()
        active_subj = state.current_subject if state.current_subject else "Unassigned"
        session_pages_count = len(state.session_photos)

        is_rec_js = "true" if (state.recording or state.audio_recording) else "false"

        pod_status_badge = (
            f"<span style='color:#3fb950;'>● Pod Linked ({state.pod_ip})</span>"
            if state.pod_connected else
            "<span style='color:#f85149;'>○ Pod Offline</span>"
        )

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
                .ambient-orb {{ position: fixed; border-radius: 50%; filter: blur(140px); z-index: -1; pointer-events: none; opacity: 0.45; animation: breathe 15s infinite alternate ease-in-out; }}
                @keyframes breathe {{ 0% {{ transform: scale(1); opacity: 0.3; }} 100% {{ transform: scale(1.1) translate(30px, -30px); opacity: 0.5; }} }}
                .orb-1 {{ top: -10%; left: -5%; width: 50vw; height: 50vw; background: rgba(88, 166, 255, 0.2); }}
                .orb-2 {{ bottom: -20%; right: -10%; width: 60vw; height: 60vw; background: rgba(162, 119, 255, 0.15); animation-delay: -7s; }}
                .orb-3 {{ top: 40%; left: 40%; width: 30vw; height: 30vw; background: rgba(0, 242, 254, 0.1); }}

                @keyframes pulse-red {{ 0% {{ box-shadow: 0 0 10px #ff4b82; }} 50% {{ box-shadow: 0 0 25px #ff4b82; }} 100% {{ box-shadow: 0 0 10px #ff4b82; }} }}
                @keyframes pulse-yellow {{ 0% {{ box-shadow: 0 0 10px #f1fa8c; }} 50% {{ box-shadow: 0 0 25px #f1fa8c; }} 100% {{ box-shadow: 0 0 10px #f1fa8c; }} }}

                .topbar-wrapper {{ padding: 24px 32px 0 32px; position: sticky; top: 0; z-index: 100; }}
                .topbar {{ max-width: 1400px; margin: 0 auto; display: flex; align-items: center; justify-content: space-between; gap: 16px; }}
                .glass-pill {{
                    display: flex; align-items: center; gap: 10px; font-size: 13px; font-weight: 600;
                    background: rgba(10, 12, 16, 0.6); backdrop-filter: blur(40px);
                    padding: 10px 20px; border-radius: 30px; border: 1px solid var(--glass-border); border-top: 1px solid var(--glass-edge-top);
                    box-shadow: 0 15px 35px rgba(0,0,0,0.5);
                }}
                .status-dot {{ width: 10px; height: 10px; background-color: {status_color}; border-radius: 50%; box-shadow: 0 0 12px {status_color}; {pulse_css} }}

                .container {{ max-width: 1400px; margin: 0 auto; padding: 32px; width: 100%; flex-grow: 1; display: grid; grid-template-columns: 300px 1fr 320px; gap: 28px; align-items: start; }}
                @media (max-width: 1100px) {{ .container {{ grid-template-columns: 1fr 1fr; }} }}
                @media (max-width: 800px) {{ .container {{ grid-template-columns: 1fr; padding: 20px; }} }}
                .column-stack {{ display: flex; flex-direction: column; gap: 28px; }}

                .card {{
                    background: var(--glass-bg); backdrop-filter: blur(40px);
                    border: 1px solid var(--glass-border); border-top: 1px solid var(--glass-edge-top); border-left: 1px solid var(--glass-edge-left);
                    border-radius: 20px; box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.6); overflow: hidden;
                }}
                .card-header {{ display: flex; justify-content: space-between; align-items: center; padding: 18px 24px; border-bottom: 1px solid rgba(255,255,255,0.03); background: rgba(0,0,0,0.2); }}
                .card-title {{ display: flex; align-items: center; gap: 10px; font-weight: 600; font-size: 13px; text-transform: uppercase; letter-spacing: 1px; color: var(--neon-cyan); }}
                .card-body {{ padding: 24px; }}

                .clock-display {{ font-size: 36px; font-weight: 700; letter-spacing: -1px; margin-bottom: 4px; color: #fff; }}
                .date-display {{ font-size: 13px; color: var(--neon-cyan); font-weight: 600; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 24px; }}

                .subject-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }}
                .subj-btn {{
                    background: rgba(0,0,0,0.2); border: 1px solid rgba(255,255,255,0.06); border-radius: 12px;
                    padding: 14px 8px; color: var(--text-muted); font-size: 12px; font-weight: 600; cursor: pointer;
                }}
                .subj-active {{ background: rgba(255,255,255,0.1); color: #fff; border-color: #fff; }}

                .actions-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }}
                .action-btn {{
                    background: linear-gradient(180deg, rgba(40, 46, 56, 0.5) 0%, rgba(25, 30, 38, 0.5) 100%);
                    border: 1px solid var(--glass-border); border-top: 1px solid var(--glass-edge-top); border-radius: 16px; 
                    padding: 18px 14px; color: var(--text-main); cursor: pointer;
                    display: flex; flex-direction: column; align-items: flex-start; gap: 8px;
                }}
                .action-btn-highlight {{
                    border-color: #58a6ff;
                    background: rgba(88, 166, 255, 0.15);
                }}

                .sys-row {{ display: flex; justify-content: space-between; align-items: center; padding: 12px 0; border-bottom: 1px dashed rgba(255,255,255,0.06); font-size: 13px; }}
                .sys-label {{ color: var(--text-muted); font-weight: 500; }}
                .sys-tag {{ font-family: monospace; font-size: 11px; background: rgba(63, 185, 80, 0.1); color: #3fb950; padding: 4px 8px; border-radius: 6px; border: 1px solid rgba(63, 185, 80, 0.3); }}

                .kv-row {{ display: flex; justify-content: space-between; align-items: center; padding: 12px 0; font-size: 13px; }}
                .kv-row.dashed {{ border-bottom: 1px dashed rgba(255,255,255,0.06); }}
                .kv-label {{ color: var(--text-muted); font-weight: 500; }}
                .kv-value {{ font-weight: 600; font-family: monospace; font-size: 12px; }}

                .progress-track {{ width: 100%; height: 6px; background: rgba(0, 0, 0, 0.6); border-radius: 10px; overflow: hidden; margin: 16px 0 10px 0; }}
                .progress-fill {{ height: 100%; width: {used_pct}%; background: linear-gradient(90deg, #00f2fe, var(--neon-cyan)); border-radius: 10px; }}
            </style>
        </head>
        <body>
            <div class="ambient-orb orb-1"></div>
            <div class="ambient-orb orb-2"></div>
            <div class="ambient-orb orb-3"></div>
            
            <div class="topbar-wrapper">
                <div class="topbar">
                    <div class="glass-pill"><div style="color:var(--neon-cyan)">✦</div> Veronica Core <span style="color:var(--text-muted);font-weight:400;margin-left:6px;">{hostname}.local</span></div>
                    <div class="glass-pill">{pod_status_badge}</div>
                    <div class="glass-pill"><div class="status-dot"></div> {status_text}</div>
                </div>
            </div>

            <div class="container">
                <div class="column-stack">
                    <div class="card">
                        <div class="card-body">
                            <div class="clock-display" id="clock">00:00:00</div>
                            <div class="date-display" id="date">Classroom Gateway</div>
                            <a href="/projector" target="_blank" class="action-btn action-btn-highlight" style="text-decoration:none; width:100%; text-align:center;">
                                📽️ Open Fullscreen Projector View
                            </a>
                        </div>
                    </div>

                    <div class="card">
                        <div class="card-header"><div class="card-title">Classroom Operations</div></div>
                        <div class="card-body">
                            <div class="kv-row dashed"><span class="kv-label">Local Offline Storage</span><span class="kv-value">/storage</span></div>
                            <div class="kv-row dashed"><span class="kv-label">Projector Wall View</span><span class="kv-value"><a href="/projector" target="_blank" style="color:#7cd0ff;">Open View</a></span></div>
                            <div class="kv-row"><span class="kv-label">Admin Report</span><span class="kv-value"><a href="/report" style="color:#7cd0ff;">View Ledger</a></span></div>
                        </div>
                    </div>
                </div>

                <div class="column-stack">
                    <div class="card">
                        <div class="card-header"><div class="card-title">Subject & Session Status</div></div>
                        <div class="card-body">
                            <div class="subject-grid">
                                <button class="subj-btn {'subj-active' if active_subj=='Physics' else ''}" onclick="post('subj_physics')">Physics</button>
                                <button class="subj-btn {'subj-active' if active_subj=='Chemistry' else ''}" onclick="post('subj_chemistry')">Chemistry</button>
                                <button class="subj-btn {'subj-active' if active_subj=='Math' else ''}" onclick="post('subj_math')">Math</button>
                                <button class="subj-btn {'subj-active' if active_subj=='English' else ''}" onclick="post('subj_english')">English</button>
                                <button class="subj-btn {'subj-active' if active_subj=='Computer Science' else ''}" onclick="post('subj_computer science')">Comp Sci</button>
                                <button class="subj-btn" onclick="post('subj_clear')">Clear</button>
                            </div>
                            <div style="margin-top: 16px; font-size: 13px; color: var(--text-muted); display:flex; justify-content:space-between;">
                                <span>Focus: <b style="color:#fff;">{active_subj}</b></span>
                                <span>Session Notes: <b style="color:var(--neon-cyan);">{session_pages_count} Page(s)</b></span>
                            </div>
                        </div>
                    </div>

                    <div class="card">
                        <div class="card-header"><div class="card-title">Tactical Controls</div></div>
                        <div class="card-body">
                            <div class="actions-grid">
                                <button class="action-btn" onclick="post('photo')">📷 Snap Board Note</button>
                                <button class="action-btn action-btn-highlight" onclick="post('compile_pdf')">📚 End Class & PDF</button>
                                <button class="action-btn" onclick="post('launch_projector')">📽️ Project on Wall</button>
                                <button class="action-btn" onclick="post('video')">🎥 Toggle Video</button>
                                <button class="action-btn" onclick="post('audio')">🎙️ Toggle Audio</button>
                                <button class="action-btn" onclick="post('stop')">⏹ Stop Recording</button>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="column-stack">
                    <div class="card">
                        <div class="card-header"><div class="card-title">System Overseer</div></div>
                        <div class="card-body">
                            <div class="sys-row"><span class="sys-label">Compute Core</span><span class="sys-tag">CPU {cpu}%</span></div>
                            <div class="sys-row"><span class="sys-label">Memory Matrix</span><span class="sys-tag">RAM {ram}%</span></div>
                            <div class="sys-row"><span class="sys-label">Lectern Link</span><span class="sys-tag">{pod_status_badge}</span></div>
                        </div>
                    </div>

                    <div class="card">
                        <div class="card-header"><div class="card-title">Storage Drive</div></div>
                        <div class="card-body">
                            <div style="display: flex; justify-content: space-between; font-size: 13px;">
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
                        <div class="card-header"><div class="card-title">Asset Ledger</div></div>
                        <div class="card-body">
                            <div class="kv-row dashed"><span class="kv-label">Latest Lecture PDF</span><span class="kv-value" style="color:#7cd0ff;"><a href="/media/notes/{last_pdf}" target="_blank" style="color:#7cd0ff;text-decoration:none;">{last_pdf}</a></span></div>
                            <div class="kv-row dashed"><span class="kv-label">Latest Photo</span><span class="kv-value"><a href="/media/photos/{last_photo}" target="_blank" style="color:#8b949e;text-decoration:none;">{last_photo}</a></span></div>
                            <div class="kv-row"><span class="kv-label">Latest Video</span><span class="kv-value">{last_video}</span></div>
                        </div>
                    </div>
                </div>
            </div>

            <script>
            function updateTime() {{
                const now = new Date();
                document.getElementById('clock').innerText = now.toLocaleTimeString('en-US', {{hour12: false}});
            }}
            setInterval(updateTime, 1000);
            updateTime();

            function post(cmd) {{
                fetch("/trigger", {{ method: "POST", headers: {{ "Content-Type": "application/x-www-form-urlencoded" }}, body: "cmd=" + cmd }})
                .then(res => res.text()).then(msg => {{ location.reload(); }})
                .catch(err => {{ alert("❌ " + err); }});
            }}
            setInterval(() => location.reload(), 15000);
            </script>
        </body>
        </html>
        """


@app.route("/api/pod_event", methods=["POST"])
def pod_event():
    """HTTP REST fallback for ESP32 Lectern Pod events."""
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
        # Launch Chromium directly into Projector View on the ceiling display
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


@app.route("/report")
def report():
    """Principal's Activity Report — strictly per-subject tracking."""
    data = load_log()
    hostname = socket.gethostname()
    now_str = datetime.datetime.now().strftime("%A, %d %B %Y  %H:%M")
    subject_cards_html = ""
    all_subjects = sorted(data.keys())

    if not all_subjects:
        subject_cards_html = """
        <div style="grid-column:1/-1;text-align:center;padding:60px;color:var(--text-muted);">
            No activity recorded yet. Start teaching!
        </div>"""
    else:
        for subj in all_subjects:
            s = data[subj]
            t_photos = s.get("total_photos", 0)
            t_videos = s.get("total_videos", 0)
            t_audios = s.get("total_audios", 0)
            t_changes = s.get("subject_changes", 0)
            daily = s.get("daily", {})
            days_active = len(daily)

            subject_cards_html += f"""
            <div class="card" style="padding:20px;border-radius:16px;background:rgba(20,24,32,0.6);margin-bottom:16px;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
                    <b style="color:var(--neon-cyan);font-size:16px;">{subj}</b>
                    <span style="font-size:11px;color:var(--text-muted);">{days_active} active day(s)</span>
                </div>
                <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;text-align:center;">
                    <div><div style="font-size:20px;font-weight:700;color:#a277ff;">{t_photos}</div><small style="color:#8b949e;">PHOTOS</small></div>
                    <div><div style="font-size:20px;font-weight:700;color:#ff4b82;">{t_videos}</div><small style="color:#8b949e;">VIDEOS</small></div>
                    <div><div style="font-size:20px;font-weight:700;color:#f1fa8c;">{t_audios}</div><small style="color:#8b949e;">AUDIOS</small></div>
                    <div><div style="font-size:20px;font-weight:700;color:#7cd0ff;">{t_changes}</div><small style="color:#8b949e;">SESSIONS</small></div>
                </div>
            </div>"""

    return f"""<!doctype html>
    <html><head><meta charset="utf-8"/><title>Principal's Report</title>
    <style>body{{font-family:Inter,sans-serif;background:#05070a;color:#f0f6fc;padding:32px;}}
    .back{{color:#7cd0ff;text-decoration:none;margin-right:16px;}}</style></head>
    <body>
        <h2>Principal's Classroom Ledger &mdash; {hostname}</h2>
        <p style="color:#8b949e;margin-bottom:24px;">Generated: {now_str}</p>
        <div>{subject_cards_html}</div>
        <div style="margin-top:24px;">
            <a class="back" href="/">← Dashboard</a>
            <a class="back" href="/report/download">⬇ Download JSON</a>
        </div>
    </body></html>"""


@app.route("/report/download")
def report_download():
    data = load_log()
    now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    return Response(
        json.dumps(data, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment;filename=veronica_report_{now_str}.json"}
    )
