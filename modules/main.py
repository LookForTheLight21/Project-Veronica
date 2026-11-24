"""
╔══════════════════════════════════════════════════════════════╗
║              PROJECT VERONICA  —  FINAL                     ║
║  Target Architecture: Two-Tier Distributed Edge-IoT          ║
║                                                              ║
║  TIER 1 (Desk):  ESP32 Lectern Pod (TTP229, PN532, Buzzer)   ║
║  TIER 2 (Ceiling): Raspberry Pi 5 Edge Hub                   ║
║                     - Kreo Owl 4K Pro (/dev/video0)          ║
║                     - USB Conference Mic                     ║
║                     - Classroom Projector View for Back-Row  ║
║                     - Zero-Friction Multi-Page PDF Notes     ║
║                     - Telegram, Drive & Web Dashboard        ║
╚══════════════════════════════════════════════════════════════╝
"""
import os
import sys
import time
import signal
import threading
import subprocess
import shutil

# Ensure module directory is on sys.path
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
if _MODULE_DIR not in sys.path:
    sys.path.insert(0, _MODULE_DIR)

import state
from config import (
    FFMPEG_BIN,
    SUBJECT_KEYS,
    MODE_KEYS,
    SECURE_CODE_SEQ,
    KERO_VIDEO_DEVICE,
    KERO_AUDIO_DEVICE,
    KERO_WIDTH,
    KERO_HEIGHT,
    KERO_FPS,
    POD_SERVER_HOST,
    POD_SERVER_PORT,
    enforce_anti_flicker_50hz,
    get_lan_ip,
)
from hardware import PodReceiverServer, BuzzerController
from activity_logger import log_activity
from telegram_bot import send_telegram, telegram_listener
from drive_upload import spooler_worker_loop
from camera import (
    take_photo_and_upload,
    compile_and_publish_session_pdf,
    start_video_audio,
    stop_video_audio,
    start_audio_only,
    stop_audio_only,
)
from system_utils import (
    send_stats_report,
    reboot_system,
    shutdown_system,
    watchdog_loop,
)
from web_dashboard import app, register_pod_callbacks

# Global reference to buzzer controller (talks to ESP32 wirelessly)
buzzer = None


# ═══════════════════════════════════════════════════════════════
#  KEYPAD HANDLER (Dispatched on ESP32 key events)
# ═══════════════════════════════════════════════════════════════

def handle_key(key_num):
    global buzzer

    # ── 1. Security Passcode Interceptor (Keys 1, 9, 2, 7) ────
    if state.secure_target_action:
        if time.time() - state.secure_timer > 10.0:
            state.secure_target_action = None
            state.secure_current_step = 0
            if buzzer: buzzer.beep(3, 0.1)
            print("⏳ Security passcode window expired.")
            return

        if key_num == SECURE_CODE_SEQ[state.secure_current_step]:
            state.secure_current_step += 1
            if buzzer: buzzer.beep(1, 0.05)
            if state.secure_current_step == len(SECURE_CODE_SEQ):
                if buzzer: buzzer.beep(2, 0.15)
                print(f"✅ Passcode Verified → Executing {state.secure_target_action}")
                if state.secure_target_action == "SHUTDOWN":
                    shutdown_system()
                elif state.secure_target_action == "RESTART":
                    reboot_system()
                state.secure_target_action = None
                state.secure_current_step = 0
        else:
            state.secure_target_action = None
            state.secure_current_step = 0
            if buzzer: buzzer.beep(3, 0.2)
            print("❌ Invalid security sequence entered.")
        return  # Intercept keypress during security entry

    # ── 2. Subject Selection Keys ─────────────────────────────
    if key_num in SUBJECT_KEYS:
        new_subject = SUBJECT_KEYS[key_num]

        # Seamless Handover: Auto-compile previous teacher's notes under their subject
        with state.state_lock:
            prev_photos = list(state.session_photos)
            prev_subject = state.current_subject or "General"
            state.session_photos = []
            state.current_subject = new_subject

        if prev_photos:
            threading.Thread(
                target=compile_and_publish_session_pdf,
                args=(prev_photos, prev_subject),
                daemon=True
            ).start()

        print(f"👆 Key {key_num} → Subject Context: {state.current_subject}")
        log_activity("subject_change")
        if buzzer: buzzer.beep(2)
        return

    # ── 3. Operational Mode Keys ──────────────────────────────
    if key_num not in MODE_KEYS:
        print(f"ℹ️ Key {key_num} not mapped")
        return

    action = MODE_KEYS[key_num]
    print(f"👆 Key {key_num} → Action: {action}")

    if action == "PHOTO":
        if buzzer: buzzer.beep(1)
        threading.Thread(target=take_photo_and_upload, daemon=True).start()

    elif action == "VIDEO_TOGGLE":
        if not state.recording:
            start_video_audio()
            if buzzer: buzzer.beep(1)
        else:
            stop_video_audio()
            if buzzer: buzzer.beep(2)

    elif action == "AUDIO_TOGGLE":
        if not state.audio_recording:
            start_audio_only()
            if buzzer: buzzer.beep(1)
        else:
            stop_audio_only()
            if buzzer: buzzer.beep(2)

    elif action == "PRIORITY_AUDIO_TOGGLE":
        if not state.audio_recording:
            start_audio_only(priority=True)
            if buzzer: buzzer.beep(1)
        else:
            stop_audio_only()
            if buzzer: buzzer.beep(2)

    elif action == "STOP":
        # Manual STOP fallback: Stops recording, or manually compiles PDF notes if clicked
        if state.recording:
            stop_video_audio()
            if buzzer: buzzer.beep(2)
        elif state.audio_recording:
            stop_audio_only()
            if buzzer: buzzer.beep(2)
        elif state.session_photos:
            if buzzer: buzzer.beep(2)
            with state.state_lock:
                photos_to_send = list(state.session_photos)
                subj_to_send = state.current_subject or "General"
                state.session_photos = []
            threading.Thread(
                target=compile_and_publish_session_pdf,
                args=(photos_to_send, subj_to_send),
                daemon=True
            ).start()
        else:
            print("ℹ️ No active recording or session notes to finalize.")

    elif action == "STATS":
        send_telegram(send_stats_report())
        if buzzer: buzzer.beep(1)

    elif action == "CLEAR_SUBJECT":
        # Manual Clear fallback: Finalize notes into PDF before clearing context
        if state.session_photos:
            with state.state_lock:
                photos_to_send = list(state.session_photos)
                subj_to_send = state.current_subject or "General"
                state.session_photos = []
            threading.Thread(
                target=compile_and_publish_session_pdf,
                args=(photos_to_send, subj_to_send),
                daemon=True
            ).start()
        state.current_subject = None
        if buzzer: buzzer.beep(1)

    elif action == "SECURE_SHUTDOWN":
        state.secure_target_action = "SHUTDOWN"
        state.secure_current_step = 0
        state.secure_timer = time.time()
        if buzzer: buzzer.beep(1)
        print("🔒 Security Armed: Enter 4-digit code (1-9-2-7) to SHUTDOWN…")

    elif action == "SECURE_RESTART":
        state.secure_target_action = "RESTART"
        state.secure_current_step = 0
        state.secure_timer = time.time()
        if buzzer: buzzer.beep(1)
        print("🔒 Security Armed: Enter 4-digit code (1-9-2-7) to REBOOT…")


# ═══════════════════════════════════════════════════════════════
#  NFC HANDLER (Dispatched on ESP32 PN532 card taps)
# ═══════════════════════════════════════════════════════════════

def handle_nfc(result):
    global buzzer

    if result.startswith("ACTION:"):
        action = result.split(":")[1]
        if action in ["PROJECTOR", "BROWSER"]:
            if buzzer: buzzer.beep(1)
            # Launch fullscreen Projector view on ceiling micro-HDMI display
            try:
                env = os.environ.copy()
                env["DISPLAY"] = ":0"
                subprocess.Popen(
                    "chromium-browser --kiosk --noerrdialogs --disable-infobars http://localhost:5000/projector",
                    shell=True,
                    env=env
                )
                print("📽️ Fullscreen Projector View displayed for back-row students.")
            except Exception as pe:
                print(f"⚠️ Projector launch error: {pe}")

        elif action == "SHUTDOWN":
            if buzzer: buzzer.beep(3)
            shutdown_system()
        elif action == "ADMIN_ALERT":
            if buzzer: buzzer.beep(5)
            send_telegram("🚨 ADMIN ALERT: Assistance requested at lectern!")
            threading.Thread(target=take_photo_and_upload, daemon=True).start()

    elif result != state.current_subject:
        # Zero-friction handover
        with state.state_lock:
            prev_photos = list(state.session_photos)
            prev_subject = state.current_subject or "General"
            state.session_photos = []
            state.current_subject = result

        if prev_photos:
            threading.Thread(
                target=compile_and_publish_session_pdf,
                args=(prev_photos, prev_subject),
                daemon=True
            ).start()

        print(f"🏷️ New Teacher Checked In → Subject Context: {state.current_subject}")
        log_activity("subject_change")
        if buzzer: buzzer.beep(2)


# ═══════════════════════════════════════════════════════════════
#  TOUCHSCREEN COMMAND HANDLER (Dispatched on ESP32 3.5" Pod events)
# ═══════════════════════════════════════════════════════════════

def handle_touch_cmd(action):
    """Dispatches direct touch screen commands streamed wirelessly from the ESP32 3.5\" Pod."""
    global buzzer
    action = action.lower()
    print(f"📱 [Touch Pod Action]: {action}")

    if action == "photo":
        if buzzer: buzzer.beep(1)
        threading.Thread(target=take_photo_and_upload, daemon=True).start()

    elif action == "compile_pdf":
        if buzzer: buzzer.beep(2)
        with state.state_lock:
            photos_to_send = list(state.session_photos)
            subj_to_send = state.current_subject or "General"
            state.session_photos = []
        if photos_to_send:
            threading.Thread(
                target=compile_and_publish_session_pdf,
                args=(photos_to_send, subj_to_send),
                daemon=True
            ).start()
        else:
            print("ℹ️ No chalkboard photos in active session to compile.")

    elif action == "video":
        if not state.recording:
            start_video_audio()
            if buzzer: buzzer.beep(1)
        else:
            stop_video_audio()
            if buzzer: buzzer.beep(2)

    elif action == "audio":
        if not state.audio_recording:
            start_audio_only()
            if buzzer: buzzer.beep(1)
        else:
            stop_audio_only()
            if buzzer: buzzer.beep(2)

    elif action == "stop":
        if state.recording:
            stop_video_audio()
            if buzzer: buzzer.beep(2)
        elif state.audio_recording:
            stop_audio_only()
            if buzzer: buzzer.beep(2)

    elif action.startswith("subj_"):
        new_subj = action.replace("subj_", "").capitalize()
        if new_subj == "Comp": new_subj = "Computer Science"
        elif new_subj == "Math": new_subj = "Mathematics"
        
        with state.state_lock:
            prev_photos = list(state.session_photos)
            prev_subject = state.current_subject or "General"
            state.session_photos = []
            state.current_subject = new_subj

        if prev_photos:
            threading.Thread(
                target=compile_and_publish_session_pdf,
                args=(prev_photos, prev_subject),
                daemon=True
            ).start()

        print(f"📘 [Touchscreen Handover] Subject Context: {state.current_subject}")
        log_activity("subject_change")
        if buzzer: buzzer.beep(2)


# ═══════════════════════════════════════════════════════════════
#  MAIN SYSTEM BOOTSTRAP
# ═══════════════════════════════════════════════════════════════

_instance_lock_file = None


def acquire_instance_lock(auto_takeover=True):
    """
    Ensures only a single instance of Veronica Core runs to prevent hardware (/dev/video0),
    port 5000 / 8765, and Telegram 409 conflict errors.
    If auto_takeover is True, it terminates any stale previous instance holding the lock
    so the new development or classroom session starts immediately.
    """
    global _instance_lock_file
    lock_path = "/tmp/veronica_app.lock"

    # Check if a previous instance is recorded in the lock file
    if os.path.exists(lock_path):
        try:
            with open(lock_path, "r") as rf:
                raw_pid = rf.read().strip()
            if raw_pid.isdigit():
                old_pid = int(raw_pid)
                if old_pid != os.getpid():
                    try:
                        # Check if process is currently running
                        os.kill(old_pid, 0)
                        if auto_takeover:
                            print(f"⚠️ Existing Veronica instance detected (PID {old_pid}).")
                            print(f"🔄 Releasing camera, ports, and Telegram polling from PID {old_pid}…")
                            os.kill(old_pid, signal.SIGTERM)
                            time.sleep(1.0)
                            try:
                                os.kill(old_pid, signal.SIGKILL)
                            except OSError:
                                pass
                            time.sleep(0.5)
                        else:
                            return False
                    except OSError:
                        # Process not alive (stale lock file)
                        pass
        except Exception as e:
            print(f"ℹ️ Lock check notice: {e}")

    try:
        import fcntl
        _instance_lock_file = open(lock_path, "w")
        fcntl.flock(_instance_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _instance_lock_file.write(str(os.getpid()))
        _instance_lock_file.flush()
        return True
    except (IOError, BlockingIOError):
        return False
    except Exception as e:
        print(f"⚠️ Lock notice: {e}")
        return True


def launch_kiosk_browser():
    """
    Auto-launches Chromium in fullscreen borderless kiosk mode on the Pi's touchscreen.
    Uses dedicated user-data-dir so it always opens in true fullscreen kiosk without
    conflicting with existing desktop browser sessions or session restore bubbles.
    """
    env = os.environ.copy()
    uid = os.getuid()

    # Search for active Wayland or X11 desktop display sockets (handles regular user or sudo)
    has_display = bool(env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))

    if not has_display:
        for check_uid in [uid, 1000]:
            runtime_dir = f"/run/user/{check_uid}"
            if os.path.exists(runtime_dir):
                for w_sock in ["wayland-0", "wayland-1"]:
                    if os.path.exists(os.path.join(runtime_dir, w_sock)):
                        env["WAYLAND_DISPLAY"] = w_sock
                        env["XDG_RUNTIME_DIR"] = runtime_dir
                        has_display = True
                        break
            if has_display:
                break

        if not has_display:
            if os.path.exists("/tmp/.X11-unix"):
                for entry in sorted(os.listdir("/tmp/.X11-unix")):
                    if entry.startswith("X"):
                        num = entry.replace("X", "")
                        env["DISPLAY"] = f":{num}"
                        has_display = True
                        break

    if not has_display:
        print("ℹ️ Headless or remote SSH session detected (no desktop display). Kiosk browser auto-launch skipped.")
        return

    if "DISPLAY" not in env and "WAYLAND_DISPLAY" not in env:
        env["DISPLAY"] = ":0"
    if "XDG_RUNTIME_DIR" not in env and os.path.exists(f"/run/user/{uid}"):
        env["XDG_RUNTIME_DIR"] = f"/run/user/{uid}"

    # Wait up to 5 seconds for local Flask server to be ready
    target_url = "http://localhost:5000/pi"
    for _ in range(25):
        time.sleep(0.2)
        try:
            import urllib.request
            with urllib.request.urlopen("http://127.0.0.1:5000/api/status", timeout=0.5) as resp:
                if resp.status == 200:
                    break
        except Exception:
            pass

    browser_bin = None
    for b in ["chromium-browser", "chromium", "google-chrome-stable", "google-chrome"]:
        found = shutil.which(b)
        if found:
            browser_bin = found
            break

    if not browser_bin:
        # Fallback to xdg-open if specific browser binary not directly found
        xdg_bin = shutil.which("xdg-open")
        if xdg_bin:
            try:
                subprocess.Popen([xdg_bin, target_url], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print(f"🖥️ Launched default browser via xdg-open -> {target_url}")
            except Exception as e:
                print(f"⚠️ Could not launch browser: {e}")
        else:
            print("⚠️ Browser not found; please open http://localhost:5000/pi in your browser.")
        return

    # Dedicated kiosk profile directory to guarantee true fullscreen and prevent profile locking
    kiosk_data_dir = "/tmp/veronica_chromium_kiosk"
    os.makedirs(kiosk_data_dir, exist_ok=True)

    cmd = [
        browser_bin,
        "--kiosk",
        f"--user-data-dir={kiosk_data_dir}",
        f"--app={target_url}",
        "--window-size=800,480",
        "--window-position=0,0",
        "--noerrdialogs",
        "--disable-infobars",
        "--disable-session-crashed-bubble",
        "--disable-translate",
        "--no-first-run",
        "--fast",
        "--fast-start",
        "--check-for-update-interval=31536000",
        target_url
    ]

    try:
        print(f"🖥️  Launching Fullscreen Kiosk Mode: {browser_bin} -> {target_url}")
        subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
    except Exception as e:
        print(f"⚠️ Could not auto-launch kiosk browser: {e}")


def main():
    global buzzer

    if not acquire_instance_lock():
        print("❌ Another instance of Project Veronica is already running.")
        print("   Exiting to prevent camera device, ALSA audio, port 5000, and Telegram 409 conflicts.")
        sys.exit(1)

    print("═════════════════════════════════════════════════════════")
    print("🚀 PROJECT VERONICA — Two-Tier Edge Hub Starting")
    print("═════════════════════════════════════════════════════════")

    if not os.path.exists(FFMPEG_BIN):
        print(f"⚠️ FFmpeg not found at {FFMPEG_BIN} (run: sudo apt install ffmpeg)")
    else:
        print(f"✅ FFmpeg Binary: {FFMPEG_BIN}")

    # Enforce 50Hz Anti-Flicker / Anti-Banding on Kreo Owl 4K camera hardware
    enforce_anti_flicker_50hz(KERO_VIDEO_DEVICE)

    # 1. Start Tier 1 Pod Wireless Link Receiver
    pod_server = PodReceiverServer(
        host=POD_SERVER_HOST,
        port=POD_SERVER_PORT,
        on_key=handle_key,
        on_nfc=handle_nfc,
        on_cmd=handle_touch_cmd
    )
    pod_server.start()
    buzzer = BuzzerController(pod_server)

    # 2. Register HTTP fallback endpoints on Flask
    register_pod_callbacks(on_key=handle_key, on_nfc=handle_nfc, buzzer_ctrl=buzzer)

    # 3. Start Background Daemons
    threading.Thread(target=telegram_listener, daemon=True).start()
    threading.Thread(target=watchdog_loop, daemon=True).start()
    threading.Thread(target=spooler_worker_loop, daemon=True).start()
    threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=5000, use_reloader=False),
        daemon=True
    ).start()

    lan_ip = get_lan_ip()
    print("=" * 72)
    print("           PROJECT VERONICA — CLASSROOM SYSTEM ACCESS DIRECTORY")
    print("=" * 72)
    print("  🖥️  LOCAL ACCESS (Raspberry Pi Touchscreen / Kiosk):")
    print("      • Pi Touchscreen UI   : http://localhost:5000/pi")
    print("      • Fullscreen Kiosk    : http://localhost:5000/kiosk")
    print()
    print("  💻  REMOTE ACCESS (Teacher's Laptop / Classroom Projector / Wi-Fi):")
    print(f"      • Classroom Projector : http://{lan_ip}:5000/projector")
    print(f"      • Command Center (Web): http://{lan_ip}:5000/")
    print(f"      • Touch Pod Remote    : http://{lan_ip}:5000/pod")
    print(f"      • Principal's Ledger  : http://{lan_ip}:5000/report")
    print(f"      • Diagnostic Hub      : http://{lan_ip}:5000/admin  [Login: Chorie / 1234]")
    if lan_ip == "127.0.0.1":
        print("      *(Wi-Fi not yet connected: using 127.0.0.1. Connect Pi to Wi-Fi to use laptop)*")
    print()
    print("  📡  HARDWARE & SERVICES:")
    print(f"      • Camera Sensor       : {KERO_VIDEO_DEVICE} ({KERO_WIDTH}x{KERO_HEIGHT} MJPEG @ {KERO_FPS}fps)")
    print(f"      • Microphone          : {KERO_AUDIO_DEVICE}")
    print(f"      • Pod Receiver        : Port {POD_SERVER_PORT} (Listening for ESP32 Pod)")
    print(f"      • Detected Network IP : {lan_ip}")
    print("=" * 72)

    # Three boot-up beeps
    time.sleep(0.5)
    buzzer.beep(3, 0.1)

    # 4. Auto-launch Fullscreen Kiosk on Pi Touchscreen Display
    if "--no-kiosk" not in sys.argv and "--headless" not in sys.argv:
        threading.Thread(target=launch_kiosk_browser, daemon=True).start()

    # 5. Main Keepalive Thread
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 Graceful system shutdown requested…")
    finally:
        if state.session_photos:
            compile_and_publish_session_pdf()
        if state.recording:
            stop_video_audio()
        if state.audio_recording:
            stop_audio_only()


if __name__ == "__main__":
    main()
