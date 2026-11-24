"""
Zero-dependency Preview Server for Project Veronica.
Simulates all Operational & Diagnostic features locally (Windows/Mac/Linux)
without requiring hardware sensors, cameras, or external pip packages!
"""
import os
import json
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

PREVIEW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

# In-Memory Simulated State & Configuration
sim_state = {
    "subject": "Physics",
    "session_pages": 3,
    "recording_video": False,
    "recording_audio": False,
    "pod_connected": True,
    "pod_ip": "192.168.4.15",
    "latest_photo_url": "/sample_board.svg",
    "latest_pdf": "Physics_LectureNotes_1111_0950.pdf"
}

sim_config = {
    "WIFI_SSID": "Veronica_AP",
    "WIFI_PASSWORD": "veronica_access",
    "POD_SERVER_HOST": "0.0.0.0",
    "POD_SERVER_PORT": 8765,
    "BOT_TOKEN": "8365210789:AAFbiu9hyMDwTkvLNq7vOnGLDI7g9WT-BEg",
    "CHAT_ID": "1356709538",
    "ALLOWED_USERS": ["1356709538"],
    "FOLDER_ID": "12l5mNFGeAIcPHt-GZSti8KvHNAf-OENf",
    "BUZZER_FREQ": 2000,
    "INACTIVITY_TIMEOUT_SEC": 1200,
    "ADMIN_USERNAME": "Chorie",
    "ADMIN_PASSWORD": "1234",
    "USEFUL_SITES": [
        {"name": "Google", "url": "https://www.google.com", "icon": "search", "color": "#4285f4"},
        {"name": "YouTube", "url": "https://www.youtube.com", "icon": "video", "color": "#ef4444"},
        {"name": "Gmail", "url": "https://mail.google.com", "icon": "mail", "color": "#ea4335"},
        {"name": "Gemini", "url": "https://gemini.google.com", "icon": "ai", "color": "#8e75ff"},
        {"name": "Google Drive", "url": "https://drive.google.com/drive/folders/12l5mNFGeAIcPHt-GZSti8KvHNAf-OENf", "icon": "drive", "color": "#10b981"},
    ],
    "NFC_MAP": {
        "D035D95F": "Physics",
        "89D14906": "Chemistry",
        "0D5AFA06": "Computer Science",
        "149680A7": "English",
        "CC9BE931": "Math",
        "A30CF40D": "ACTION:PROJECTOR",
        "5ACFFB3F": "ACTION:SHUTDOWN"
    }
}

authenticated_tokens = set()

class VeronicaPreviewHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = self.path.split("?")[0]
        
        if url in ["/", "/index.html"]:
            self._serve_file("index.html", "text/html; charset=utf-8")
        elif url in ["/pi", "/kiosk", "/pi_dashboard.html"]:
            self._serve_file("pi_dashboard.html", "text/html; charset=utf-8")
        elif url in ["/pod", "/pod_touch", "/pod.html", "/pod_touch.html"]:
            self._serve_file("pod_touch.html", "text/html; charset=utf-8")
        elif url == "/projector":
            self._serve_file("projector.html", "text/html; charset=utf-8")
        elif url == "/report":
            cookie = self.headers.get("Cookie", "")
            if "veronica_principal_session=active" not in cookie and "veronica_admin_session=active" not in cookie:
                self.send_response(302)
                self.send_header("Location", "/login")
                self.end_headers()
                return
            self._serve_file("report.html", "text/html; charset=utf-8")
        elif url == "/beam":
            self._serve_file("beam_upload.html", "text/html; charset=utf-8")
        elif url == "/beam_pod":
            self._serve_file("beam_pod.html", "text/html; charset=utf-8")
        elif url == "/viewer":
            self._serve_file("slide_viewer.html", "text/html; charset=utf-8")
        elif url.startswith("/beam/file/"):
            # Serve sample svg if file not on disk
            fname = url.replace("/beam/file/", "")
            slides_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "storage", "temp_slides")
            fpath = os.path.join(slides_dir, fname)
            if os.path.exists(fpath):
                with open(fpath, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf" if fname.endswith(".pdf") else "application/octet-stream")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            else:
                self._serve_file("sample_board.svg", "image/svg+xml")
        elif url.startswith("/api/beam/qr.svg"):
            import urllib.parse
            parsed_url = urllib.parse.urlparse(self.path)
            query_params = urllib.parse.parse_qs(parsed_url.query)
            override_host = (query_params.get("host", [""])[0]).strip()
            override_port = (query_params.get("port", [""])[0]).strip()
            host_header = self.headers.get("Host", "")

            if override_host and override_host not in ["localhost", "127.0.0.1"]:
                if ":" in override_host:
                    host_port = override_host
                elif override_port:
                    host_port = f"{override_host}:{override_port}"
                else:
                    host_port = f"{override_host}:{host_header.split(':')[-1] if ':' in host_header else '5000'}"
            elif host_header and not host_header.startswith("localhost") and not host_header.startswith("127."):
                host_port = host_header
            else:
                lan_ip = get_lan_ip()
                p = host_header.split(":")[-1] if ":" in host_header else "5000"
                host_port = f"{lan_ip}:{p}"

            target_url = f"http://{host_port}/beam"
            try:
                import qrcode
                import qrcode.image.svg
                import io
                img = qrcode.make(target_url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
                out = io.BytesIO()
                img.save(out)
                svg_data = out.getvalue()
            except Exception:
                svg_data = f'<svg xmlns="http://www.w3.org/2000/svg" width="220" height="220" viewBox="0 0 220 220"><rect width="220" height="220" fill="#0f172a"/><text x="110" y="100" fill="#38bdf8" font-size="12" text-anchor="middle">Scan URL:</text><text x="110" y="125" fill="#fff" font-size="11" text-anchor="middle">{target_url}</text></svg>'.encode('utf-8')
            self.send_response(200)
            self.send_header("Content-Type", "image/svg+xml")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(svg_data)))
            self.end_headers()
            self.wfile.write(svg_data)
        elif url.startswith("/api/beam/status"):
            import urllib.parse
            parsed_url = urllib.parse.urlparse(self.path)
            query_params = urllib.parse.parse_qs(parsed_url.query)
            override_host = (query_params.get("host", [""])[0]).strip()
            override_port = (query_params.get("port", [""])[0]).strip()
            host_header = self.headers.get("Host", "")

            if override_host and override_host not in ["localhost", "127.0.0.1"]:
                if ":" in override_host:
                    host_port = override_host
                elif override_port:
                    host_port = f"{override_host}:{override_port}"
                else:
                    host_port = f"{override_host}:{host_header.split(':')[-1] if ':' in host_header else '5000'}"
            elif host_header and not host_header.startswith("localhost") and not host_header.startswith("127."):
                host_port = host_header
            else:
                lan_ip = get_lan_ip()
                p = host_header.split(":")[-1] if ":" in host_header else "5000"
                host_port = f"{lan_ip}:{p}"

            deck = sim_state.get("current_slide_deck")
            self._send_json({
                "status": "ok",
                "active": deck is not None,
                "deck": deck,
                "beam_url": f"http://{host_port}/beam",
                "host": host_port,
                "wifi_ssid": sim_config.get("WIFI_SSID", "Poor_soul_5G")
            })
        elif url == "/login":
            self._serve_file("login.html", "text/html; charset=utf-8")
        elif url == "/logout":
            self.send_response(302)
            self.send_header("Set-Cookie", "veronica_admin_session=deleted; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT")
            self.send_header("Set-Cookie", "veronica_principal_session=deleted; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT")
            self.send_header("Location", "/login")
            self.end_headers()
        elif url == "/admin":
            cookie = self.headers.get("Cookie", "")
            if "veronica_admin_session=active" not in cookie:
                self.send_response(302)
                self.send_header("Location", "/login")
                self.end_headers()
                return
            self._serve_file("admin.html", "text/html; charset=utf-8")
        elif url in ["/sample_board.svg", "/media/photos/sample_board.svg"]:
            self._serve_file("sample_board.svg", "image/svg+xml")
        elif url == "/video_feed":
            live_shm = "/dev/shm/live_frame.jpg"
            if os.path.exists(live_shm):
                try:
                    with open(live_shm, "rb") as f:
                        data = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                    self.end_headers()
                    self.wfile.write(data)
                    return
                except Exception:
                    pass
            self.send_response(200)
            self.send_header("Content-Type", "image/svg+xml")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            with open(os.path.join(PREVIEW_DIR, "sample_board.svg"), "rb") as f:
                self.wfile.write(f.read())
        elif url == "/api/status":
            self._send_json({
                "pod_connected": sim_state.get("pod_connected", True),
                "pod_ip": sim_state.get("pod_ip", "192.168.4.15"),
                "current_subject": sim_state.get("subject", "Physics"),
                "recording_video": sim_state.get("recording_video", False),
                "recording_audio": sim_state.get("recording_audio", False),
                "camera_connected": True,
                "disk_free_gb": 42.5,
                "disk_used_pct": 28.4,
                "disk_total_gb": 59.2,
                "cpu_percent": 18.2,
                "ram_percent": 34.5,
                "cpu_temp_c": 44.2,
                "wifi_ssid": sim_config.get("WIFI_SSID", "Veronica_AP")
            })
        elif url in ["/api/bookmarks", "/api/admin/bookmarks"]:
            self._send_json({"status": "ok", "bookmarks": sim_config.get("USEFUL_SITES", [])})
        elif url == "/api/admin/mic_sample":
            import io, wave, struct, math
            buf = io.BytesIO()
            with wave.open(buf, 'wb') as wf:
                wf.setnchannels(2)
                wf.setsampwidth(2)
                wf.setframerate(44100)
                # Generate 2 seconds of pleasant 440Hz harmonic chime
                frames = bytearray()
                for i in range(44100 * 2):
                    t = i / 44100.0
                    decay = math.exp(-t * 2.0)
                    val = int(12000 * math.sin(2 * math.pi * 440 * t) * decay)
                    frames.extend(struct.pack('<hh', val, val))
                wf.writeframes(frames)
            content = buf.getvalue()
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        elif url == "/api/latest_asset":
            self._send_json(sim_state)
        elif url == "/api/report_data":
            # Real or simulated rich 7-day multi-subject report for Principal
            import datetime
            base_dir = os.path.dirname(os.path.abspath(__file__))
            act_path = os.path.join(base_dir, "activity_log.json")
            notes_dir = os.path.join(base_dir, "storage", "notes")
            videos_dir = os.path.join(base_dir, "storage", "videos")
            photos_dir = os.path.join(base_dir, "storage", "photos")

            log_data = {}
            if os.path.exists(act_path):
                try:
                    with open(act_path, "r", encoding="utf-8") as f:
                        log_data = json.load(f)
                except Exception:
                    pass

            notes_files = [f for f in os.listdir(notes_dir) if f.endswith('.pdf')] if os.path.exists(notes_dir) else []
            video_files = [f for f in os.listdir(videos_dir) if f.endswith('.mp4') or f.endswith('.m4a')] if os.path.exists(videos_dir) else []
            photo_files = [f for f in os.listdir(photos_dir) if f.endswith('.jpg')] if os.path.exists(photos_dir) else []

            today_dt = datetime.date.today()
            days_list = [today_dt - datetime.timedelta(days=i) for i in range(7)]
            known_subjects = ["Physics", "Chemistry", "Mathematics", "English", "Computer Science"]
            folder_id = sim_config.get("FOLDER_ID", "12l5mNFGeAIcPHt-GZSti8KvHNAf-OENf")

            subjects_data = {}
            for subj in known_subjects:
                s_log = log_data.get(subj, {})
                if not s_log and subj == "Mathematics":
                    s_log = log_data.get("Math", {})
                s_daily = s_log.get("daily", {})

                def matches_subj(name):
                    n = name.lower()
                    s = subj.lower()
                    if s == "mathematics" and "math" in n: return True
                    return s in n

                last_7_days = []
                for d in days_list:
                    d_str = d.strftime("%Y-%m-%d")
                    d_tag = d.strftime("%m%d")
                    d_info = s_daily.get(d_str, {})

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
                        subj_notes.sort(key=lambda fn: os.path.getmtime(os.path.join(notes_dir, fn)) if os.path.exists(os.path.join(notes_dir, fn)) else 0, reverse=True)
                        fn = subj_notes[0]
                        latest_mat = {
                            "filename": fn,
                            "type": "pdf",
                            "label": "Compiled Notes PDF",
                            "cloud_url": f"https://drive.google.com/drive/folders/{folder_id}",
                            "local_url": f"/media/notes/{fn}",
                            "time": fn.replace(".pdf", "").split("_")[-1] if "_" in fn else "Latest"
                        }
                    elif subj_videos:
                        subj_videos.sort(key=lambda fn: os.path.getmtime(os.path.join(videos_dir, fn)) if os.path.exists(os.path.join(videos_dir, fn)) else 0, reverse=True)
                        fn = subj_videos[0]
                        latest_mat = {
                            "filename": fn,
                            "type": "video",
                            "label": "Classroom Video Stream",
                            "cloud_url": f"https://drive.google.com/drive/folders/{folder_id}",
                            "local_url": f"/media/videos/{fn}",
                            "time": fn.replace(".mp4", "").split("_")[-1] if "_" in fn else "Latest"
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
                    all_subj_notes.sort(key=lambda fn: os.path.getmtime(os.path.join(notes_dir, fn)) if os.path.exists(os.path.join(notes_dir, fn)) else 0, reverse=True)
                    g_fn = all_subj_notes[0]
                    global_latest = {
                        "filename": g_fn,
                        "type": "pdf",
                        "label": "Latest Compiled Notes PDF",
                        "cloud_url": f"https://drive.google.com/drive/folders/{folder_id}",
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

            self._send_json({
                "status": "ok",
                "classroom": "Class X",
                "today_str": today_dt.strftime("%d %B %Y"),
                "total_classes": len(known_subjects),
                "total_photos": len(photo_files),
                "total_notes": len(notes_files),
                "total_videos": len(video_files),
                "subjects": subjects_data
            })
        elif url == "/api/admin/config":
            self._send_json({"status": "ok", "config": sim_config})
        elif url == "/report/download":
            dummy_report = {
                "Physics": { "total_photos": 12, "total_videos": 2, "daily": { "2026-11-11": { "photos": 3, "videos": 1 } } },
                "Chemistry": { "total_photos": 8, "total_videos": 1, "daily": { "2026-11-11": { "photos": 2, "videos": 0 } } }
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Disposition", "attachment; filename=veronica_diagnostic_report.json")
            self.end_headers()
            self.wfile.write(json.dumps(dummy_report, indent=2).encode("utf-8"))
        else:
            # Fallback
            fname = os.path.basename(url)
            fpath = os.path.join(PREVIEW_DIR, fname)
            if os.path.exists(fpath):
                ext = fname.split(".")[-1].lower()
                mime = "text/html" if ext == "html" else "image/svg+xml" if ext == "svg" else "application/octet-stream"
                self._serve_file(fname, mime)
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"404 Not Found")

    def do_POST(self):
        url = self.path.split("?")[0]
        content_len = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_len).decode('utf-8') if content_len > 0 else "{}"
        try:
            data = json.loads(body)
        except Exception:
            data = {}

        if url == "/api/login":
            u = (data.get("username") or "").strip()
            p = (data.get("password") or "").strip()
            c = (data.get("classroom") or "Class X").strip()

            # 1. Field Technician Role (Chorie / 1234)
            if u.lower() == sim_config["ADMIN_USERNAME"].lower() and p == sim_config["ADMIN_PASSWORD"]:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Set-Cookie", "veronica_admin_session=active; path=/; max-age=86400")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "ok",
                    "role": "technician",
                    "user": sim_config["ADMIN_USERNAME"],
                    "redirect": "/admin"
                }).encode("utf-8"))

            # 2. Principal Role (principle / 1234)
            elif u.lower() in ["principle", "principal"] and p == "1234":
                if c.lower() in ["class x", "class 10", "x", "10"]:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Set-Cookie", "veronica_principal_session=active; path=/; max-age=86400")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "status": "ok",
                        "role": "principal",
                        "classroom": "Class X",
                        "redirect": "/report"
                    }).encode("utf-8"))
                else:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "status": "not_installed",
                        "classroom": c,
                        "message": f"Hardware Offline: Veronica Smart Lectern is not yet installed in {c}. Active pilot deployment is in Class X."
                    }).encode("utf-8"))
            else:
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": "Access Denied: Invalid security passkey."}).encode("utf-8"))

        elif url == "/api/camera/resolution":
            res = data.get("res") if isinstance(data, dict) else "1920x1080"
            sim_state["resolution"] = res
            self._send_json({"status": "ok", "resolution": res, "camera_fps": 30.0})
        elif url in ["/api/admin/test_camera", "/api/admin/ping_pod"]:
            self._send_json({"status": "ok", "connected": True, "message": "Camera optical feed /dev/video0 verified (1080P @ 30 FPS)."})
        elif url == "/api/admin/test_mic":
            self._send_json({
                "status": "ok",
                "connected": True,
                "device": "plughw:CARD=webcam,DEV=0",
                "duration": "2.0s",
                "sample_rate": "44100 Hz",
                "channels": "Stereo",
                "peak": 14250,
                "peak_dbfs": "-7.2 dBFS",
                "rms_dbfs": "-18.5 dBFS",
                "db_num": -18.5,
                "gain_status": "Optimal",
                "audio_url": "/api/admin/mic_sample",
                "message": "ALSA Audio Capture verified: -18.5 dBFS (44.1kHz Stereo, peak -7.2 dBFS)."
            })
        elif url == "/api/admin/bookmarks":
            bms = data.get("bookmarks")
            if isinstance(bms, list):
                sim_config["USEFUL_SITES"] = bms
                self._send_json({"status": "ok", "message": "Bookmarks updated successfully.", "bookmarks": bms})
            else:
                self._send_json({"status": "error", "message": "Invalid format."}, 400)
        elif url == "/api/admin/save_config":
            sim_config.update(data)
            print(f"⚙️ [DIAGNOSTIC CONFIG UPDATED]: {data.keys()}")
            # Persist to config.json
            config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
            try:
                with open(config_file, "w", encoding="utf-8") as f:
                    json.dump(sim_config, f, indent=2)
            except Exception as e:
                print(f"⚠️ Error saving config.json: {e}")
            self._send_json({"status": "ok", "config": sim_config})

        elif url == "/api/admin/upload_credentials":
            content = data.get("credentials_json") if isinstance(data, dict) else None
            cred_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials.json")
            if content:
                try:
                    parsed = json.loads(content)
                    with open(cred_path, "w", encoding="utf-8") as f:
                        json.dump(parsed, f, indent=2)
                    self._send_json({"status": "ok", "message": "credentials.json saved to Project Veronica."})
                except Exception as e:
                    self._send_json({"status": "error", "message": f"Invalid JSON: {e}"}, 400)
            else:
                self._send_json({"status": "ok", "message": "credentials.json received."})

        elif url == "/api/admin/test_buzzer":
            times = data.get("times", 1)
            dur = data.get("duration", 150)
            freq = data.get("freq", sim_config["BUZZER_FREQ"])
            print(f"🔊 [DIAGNOSTIC TONE TEST]: Dispatched {times} beep(s) @ {freq}Hz ({dur}ms) to ESP32 Pod")
            self._send_json({"status": "ok", "times": times, "freq": freq})

        elif url == "/api/admin/test_telegram":
            print(f"📡 [DIAGNOSTIC TELEGRAM TEST]: Test beacon sent to chat {sim_config['CHAT_ID']}")
            self._send_json({"status": "ok"})

        elif url == "/api/admin/purge_cache":
            print("🗑️ [SIMULATION]: Purged raw uncompiled JPEG cache")
            self._send_json({"status": "ok", "deleted_count": 0, "bytes_freed": 0, "message": "Raw JPEG cache cleared (simulated)."})

        elif url == "/api/admin/compact_spool":
            print("📦 [SIMULATION]: Compacted upload spool queue")
            self._send_json({"status": "ok", "remaining_count": 0, "message": "Upload spool index compacted (simulated)."})

        elif url == "/api/admin/restart_engine":
            print("🔄 [SIMULATION]: Soft restarted Veronica core daemons")
            self._send_json({"status": "ok", "message": "Veronica engine background services synchronized."})

        elif url == "/api/admin/poweroff":
            print("🛑 [SIMULATION]: Safe hardware power off dispatched")
            self._send_json({"status": "ok", "message": "Hardware power-off sequence initiated (simulated)."})

        elif url == "/api/beam/clear":
            sim_state["current_slide_deck"] = None
            print("🗑️ [SIMULATION]: Cleared beamed lecture slides from memory.")
            self._send_json({"status": "ok", "message": "All session presentation slides securely erased."})

        elif url.startswith("/cmd/"):
            action = url.replace("/cmd/", "")
            self._handle_action(action)
            self._send_json({"status": "ok", "state": sim_state})
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_action(self, action):
        if action == "photo":
            sim_state["session_pages"] += 1
            print(f"📸 [SIMULATION]: Snapped board note derivation page #{sim_state['session_pages']}")
        elif action == "compile_pdf":
            print(f"📚 [SIMULATION]: Compiled {sim_state['session_pages']} pages into PDF for [{sim_state['subject']}]")
            sim_state["session_pages"] = 0
        elif action == "video":
            sim_state["recording_video"] = not sim_state["recording_video"]
            if sim_state["recording_video"]:
                sim_state["recording_audio"] = False
            print(f"🎥 [SIMULATION]: Video recording {'STARTED' if sim_state['recording_video'] else 'STOPPED'}")
        elif action == "audio":
            sim_state["recording_audio"] = not sim_state["recording_audio"]
            if sim_state["recording_audio"]:
                sim_state["recording_video"] = False
            print(f"🎙️ [SIMULATION]: Audio recording {'STARTED' if sim_state['recording_audio'] else 'STOPPED'}")
        elif action == "stop":
            sim_state["recording_video"] = False
            sim_state["recording_audio"] = False
            print("⏹ [SIMULATION]: Stopped all active recordings")
        elif action.startswith("subj_"):
            new_subj = action.replace("subj_", "").capitalize()
            if new_subj.lower() == "clear":
                sim_state["subject"] = "General Session"
            else:
                sim_state["subject"] = new_subj
            print(f"🏷️ [SIMULATION]: Subject switched to [{sim_state['subject']}]")

    def _send_json(self, payload):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def _serve_file(self, filename, content_type):
        path = os.path.join(PREVIEW_DIR, filename)
        if not os.path.exists(path):
            self.send_response(404)
            self.end_headers()
            return
        with open(path, "rb") as f:
            content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        # Filter out high-frequency polling endpoints from console logs
        if len(args) > 0:
            req_line = str(args[0])
            if any(endpoint in req_line for endpoint in ["/api/status", "/api/latest_asset", "/video_feed"]):
                return
        print(f"🌐 [Preview]: {self.address_string()} - {args[0]}")

def get_lan_ip():
    """Detects host's actual LAN IP address."""
    try:
        import subprocess
        out = subprocess.check_output(["ip", "route", "get", "1.1.1.1"], stderr=subprocess.DEVNULL, text=True, timeout=1).strip()
        parts = out.split()
        if "src" in parts:
            src_idx = parts.index("src")
            if src_idx + 1 < len(parts):
                cand = parts[src_idx + 1].strip()
                if cand and not cand.startswith("127."):
                    return cand
    except Exception:
        pass
    try:
        import subprocess
        out = subprocess.check_output(["hostname", "-I"], text=True, timeout=1).strip()
        ips = [ip.strip() for ip in out.split() if ip.strip() and not ip.startswith("127.")]
        if ips:
            return ips[0]
    except Exception:
        pass
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    try:
        import socket
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    return "127.0.0.1"


def run_server(port=5000):
    server_address = ('', port)
    lan_ip = get_lan_ip()
    try:
        httpd = HTTPServer(server_address, VeronicaPreviewHandler)
        print("=" * 72)
        print("       PROJECT VERONICA — PREVIEW SERVER (SIMULATION & DIAGNOSTICS)")
        print("=" * 72)
        print("  🖥️  LOCAL ACCESS (Raspberry Pi Touchscreen / Kiosk):")
        print(f"      • Pi Touchscreen UI   : http://localhost:{port}/pi")
        print(f"      • Fullscreen Kiosk    : http://localhost:{port}/kiosk")
        print()
        print("  💻  REMOTE ACCESS (Teacher's Laptop / Classroom Projector / Wi-Fi):")
        print(f"      • Classroom Projector : http://{lan_ip}:{port}/projector")
        print(f"      • Command Center (Web): http://{lan_ip}:{port}/")
        print(f"      • Touch Pod Remote    : http://{lan_ip}:{port}/pod")
        print(f"      • Principal's Ledger  : http://{lan_ip}:{port}/report")
        print(f"      • Diagnostic Hub      : http://{lan_ip}:{port}/admin  [Login: Chorie / 1234]")
        if lan_ip == "127.0.0.1":
            print("      *(Wi-Fi not yet connected: using 127.0.0.1. Connect to Wi-Fi to use laptop)*")
        print()
        print("  📡  NETWORK:")
        print(f"      • Detected Network IP : {lan_ip}")
        print(f"      • Server Port         : {port}")
        print("=" * 72)
        httpd.serve_forever()
    except OSError as e:
        if port == 5000:
            print(f"Port 5000 in use, falling back to 8080...")
            run_server(8080)
        else:
            print(f"Error starting preview server: {e}")

if __name__ == "__main__":
    run_server()
