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
        elif url == "/projector":
            self._serve_file("projector.html", "text/html; charset=utf-8")
        elif url == "/report":
            self._serve_file("report.html", "text/html; charset=utf-8")
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
            self.send_response(200)
            self.send_header("Content-Type", "image/svg+xml")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            with open(os.path.join(PREVIEW_DIR, "sample_board.svg"), "rb") as f:
                self.wfile.write(f.read())
        elif url == "/api/latest_asset":
            self._send_json(sim_state)
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

        elif url == "/api/admin/test_buzzer":
            times = data.get("times", 1)
            dur = data.get("duration", 150)
            freq = data.get("freq", sim_config["BUZZER_FREQ"])
            print(f"🔊 [DIAGNOSTIC TONE TEST]: Dispatched {times} beep(s) @ {freq}Hz ({dur}ms) to ESP32 Pod")
            self._send_json({"status": "ok", "times": times, "freq": freq})

        elif url == "/api/admin/test_telegram":
            print(f"📡 [DIAGNOSTIC TELEGRAM TEST]: Test beacon sent to chat {sim_config['CHAT_ID']}")
            self._send_json({"status": "ok"})

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
        print(f"🌐 [Preview]: {self.address_string()} - {args[0]}")

def run_server(port=5000):
    server_address = ('', port)
    try:
        httpd = HTTPServer(server_address, VeronicaPreviewHandler)
        print("=" * 65)
        print("  PROJECT VERONICA — DIAGNOSTIC & OPERATIONAL PREVIEW SERVER")
        print("=" * 65)
        print(f"  👉 Teacher Command Center:  http://localhost:{port}/")
        print(f"  👉 Classroom Projector:    http://localhost:{port}/projector")
        print(f"  👉 Principal Ledger:       http://localhost:{port}/report")
        print(f"  👉 Diagnostic Login:       http://localhost:{port}/login")
        print(f"  👉 Diagnostic Hub:         http://localhost:{port}/admin")
        print(f"     [Credentials: Username: Chorie  |  Password: 1234]")
        print("=" * 65)
        httpd.serve_forever()
    except OSError as e:
        if port == 5000:
            print(f"Port 5000 in use, falling back to 8080...")
            run_server(8080)
        else:
            print(f"Error starting preview server: {e}")

if __name__ == "__main__":
    run_server()
