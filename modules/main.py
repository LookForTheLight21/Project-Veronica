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
import threading
import subprocess

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
    POD_SERVER_HOST,
    POD_SERVER_PORT,
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
            send_telegram(f"📚 Previous class [{prev_subject}] ended. Compiling notes PDF…")
            threading.Thread(
                target=compile_and_publish_session_pdf,
                args=(prev_photos, prev_subject),
                daemon=True
            ).start()

        print(f"👆 Key {key_num} → Subject Context: {state.current_subject}")
        log_activity("subject_change")
        if buzzer: buzzer.beep(2)
        send_telegram(f"📘 Subject: {state.current_subject}")
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
            send_telegram("📚 Manual End-of-Class triggered: Compiling lecture notes PDF…")
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
            send_telegram("📚 Class session closed. Compiling final PDF notes…")
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
        send_telegram("⚪ Subject context cleared.")

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
            send_telegram(f"📚 Previous period [{prev_subject}] ended. Compiling lecture notes PDF…")
            threading.Thread(
                target=compile_and_publish_session_pdf,
                args=(prev_photos, prev_subject),
                daemon=True
            ).start()

        print(f"🏷️ New Teacher Checked In → Subject Context: {state.current_subject}")
        log_activity("subject_change")
        if buzzer: buzzer.beep(2)
        send_telegram(f"🏷️ Subject Switched: {state.current_subject}")


# ═══════════════════════════════════════════════════════════════
#  MAIN SYSTEM BOOTSTRAP
# ═══════════════════════════════════════════════════════════════

def main():
    global buzzer

    print("═════════════════════════════════════════════════════════")
    print("🚀 PROJECT VERONICA — Two-Tier Edge Hub Starting")
    print("═════════════════════════════════════════════════════════")

    if not os.path.exists(FFMPEG_BIN):
        print(f"⚠️ FFmpeg not found at {FFMPEG_BIN} (run: sudo apt install ffmpeg)")
    else:
        print(f"✅ FFmpeg Binary: {FFMPEG_BIN}")

    # 1. Start Tier 1 Pod Wireless Link Receiver
    pod_server = PodReceiverServer(
        host=POD_SERVER_HOST,
        port=POD_SERVER_PORT,
        on_key=handle_key,
        on_nfc=handle_nfc
    )
    pod_server.start()
    buzzer = BuzzerController(pod_server)

    # 2. Register HTTP fallback endpoints on Flask
    register_pod_callbacks(on_key=handle_key, on_nfc=handle_nfc)

    # 3. Start Background Daemons
    threading.Thread(target=telegram_listener, daemon=True).start()
    threading.Thread(target=watchdog_loop, daemon=True).start()
    threading.Thread(target=spooler_worker_loop, daemon=True).start()
    threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=5000, use_reloader=False),
        daemon=True
    ).start()

    print(f"   Camera Sensor  : {KERO_VIDEO_DEVICE} ({KERO_WIDTH}x{KERO_HEIGHT} MJPEG)")
    print(f"   Microphone     : {KERO_AUDIO_DEVICE}")
    print(f"   Pod Receiver   : Port {POD_SERVER_PORT} (Listening for ESP32 Pod)")
    print(f"   Web Dashboard  : http://0.0.0.0:5000")
    print(f"   Projector View : http://0.0.0.0:5000/projector")
    print(f"   Admin Report   : http://0.0.0.0:5000/report")

    # Three boot-up beeps
    time.sleep(0.5)
    buzzer.beep(3, 0.1)

    # 4. Main Keepalive Thread
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
