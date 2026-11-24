"""
System utilities and watchdog for Project Veronica FINAL.
Functions:
  - get_storage_usage, get_uptime, send_stats_report, report_status
  - reboot_system, shutdown_system
  - watchdog_loop: Recovers crashed FFmpeg and auto-flushes idle lecture notes (last period of the day)
"""
import os
import time
import shutil
import psutil
import threading
import subprocess

import state
from config import KERO_VIDEO_DEVICE, PHOTOS_DIR, VIDEOS_DIR, NOTES_DIR
from telegram_bot import send_telegram


def get_storage_usage():
    u = shutil.disk_usage("/")
    return (
        round(u.used / u.total * 100, 1),
        round(u.free / (1024 ** 3), 2),
        round(u.total / (1024 ** 3), 2)
    )


def get_uptime():
    secs = int(time.time() - psutil.boot_time())
    h, rem = divmod(secs, 3600)
    m = rem // 60
    return f"{h}h {m}m"


def send_stats_report():
    cpu = psutil.cpu_percent(interval=1)
    ram = psutil.virtual_memory().percent
    used_pct, free_gb, _ = get_storage_usage()

    photo_count = len(os.listdir(PHOTOS_DIR)) if os.path.exists(PHOTOS_DIR) else 0
    video_count = len(os.listdir(VIDEOS_DIR)) if os.path.exists(VIDEOS_DIR) else 0
    notes_count = len(os.listdir(NOTES_DIR)) if os.path.exists(NOTES_DIR) else 0
    cam_ok = os.path.exists(KERO_VIDEO_DEVICE)

    return (
        f"📊 Veronica Stats\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"📝 Subject : {state.current_subject or 'None'}\n"
        f"⏱️ Uptime  : {get_uptime()}\n"
        f"🖥️ CPU     : {cpu}%\n"
        f"🧠 RAM     : {ram}%\n"
        f"💾 Storage : {used_pct}% · {free_gb} GB free\n"
        f"📸 Photos  : {photo_count}\n"
        f"🎥 Videos  : {video_count}\n"
        f"📚 PDF Note: {notes_count}\n"
        f"📷 Camera  : {'✅' if cam_ok else '❌'}\n"
        f"🎬 Mode    : {'Video' if state.recording else 'Audio' if state.audio_recording else 'Idle'}"
    )


def report_status():
    if state.recording:
        send_telegram(f"🎬 Recording video → {state.raw_filename}")
    elif state.audio_recording:
        send_telegram(f"🎙️ Recording audio → {state.audio_filename}")
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


def watchdog_loop():
    from camera import start_video_audio, start_audio_only, compile_and_publish_session_pdf

    consecutive_video_crashes = 0
    consecutive_audio_crashes = 0
    MAX_CRASH_RETRIES = 3

    while True:
        # 1. Recover crashed video recording (with retry limit to prevent infinite restart loop)
        if state.recording and (state.ffmpeg_proc is None or state.ffmpeg_proc.poll() is not None):
            consecutive_video_crashes += 1
            if consecutive_video_crashes <= MAX_CRASH_RETRIES:
                print(f"🛡️ Watchdog: video crashed (recovery attempt {consecutive_video_crashes}/{MAX_CRASH_RETRIES}) — restarting…")
                start_video_audio()
            else:
                send_telegram("⚠️ Something went wrong with video recording. Please contact the developer.")
                with state.state_lock:
                    state.recording = False
                    state.ffmpeg_proc = None
                consecutive_video_crashes = 0
        elif state.recording and state.ffmpeg_proc and state.ffmpeg_proc.poll() is None:
            consecutive_video_crashes = 0

        # 2. Recover crashed audio recording (with retry limit)
        elif state.audio_recording and (state.audio_proc is None or state.audio_proc.poll() is not None):
            consecutive_audio_crashes += 1
            if consecutive_audio_crashes <= MAX_CRASH_RETRIES:
                print(f"🛡️ Watchdog: audio crashed (recovery attempt {consecutive_audio_crashes}/{MAX_CRASH_RETRIES}) — restarting…")
                start_audio_only()
            else:
                send_telegram("⚠️ Something went wrong with audio recording. Please contact the developer.")
                with state.state_lock:
                    state.audio_recording = False
                    state.audio_proc = None
                    state.audio_is_priority = False
                consecutive_audio_crashes = 0
        elif state.audio_recording and state.audio_proc and state.audio_proc.poll() is None:
            consecutive_audio_crashes = 0

        # 3. Inactivity Auto-Flush: If 20 minutes pass after last photo (e.g. final class of the day),
        # automatically wrap up and publish the lecture PDF so notes are never stranded!
        if state.session_photos and state.last_photo_time > 0:
            if time.time() - state.last_photo_time > 1200:  # 20 minutes idle
                with state.state_lock:
                    idle_photos = list(state.session_photos)
                    idle_subj = state.current_subject or "General"
                    state.session_photos = []
                    state.last_photo_time = 0.0

                print(f"⏰ Session Timeout (Class Ended): Auto-compiling PDF notes for [{idle_subj}]…")
                threading.Thread(
                    target=compile_and_publish_session_pdf,
                    args=(idle_photos, idle_subj),
                    daemon=True
                ).start()

        time.sleep(10)

