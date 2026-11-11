"""
Camera & Multi-Page PDF Notes Compiler for Project Veronica FINAL (Kero 4K Owl + USB Mic).
Functions:
  - take_photo_and_upload: Captures 5-frame averaged note, previews to Telegram, updates Projector live view.
  - compile_and_publish_session_pdf: Assembles session snapshots into a single digital PDF notebook & uploads to Drive.
  - start_video_audio, stop_video_audio: 1080p real-time H.264 + AAC with +faststart flag.
  - start_audio_only, stop_audio_only: Room microphone audio recording with +faststart flag.
"""
import os
import time
import signal
import datetime
import subprocess
import threading
from PIL import Image

import state
from config import (
    PHOTOS_DIR,
    VIDEOS_DIR,
    NOTES_DIR,
    FOLDER_ID,
    FFMPEG_BIN,
    KERO_VIDEO_DEVICE,
    KERO_AUDIO_DEVICE,
    KERO_WIDTH,
    KERO_HEIGHT,
    KERO_FPS,
    KERO_INPUT_FORMAT,
)
from telegram_bot import send_telegram, send_telegram_photo, send_telegram_document
from drive_upload import upload_to_drive
from activity_logger import log_activity


# ═══════════════════════════════════════════════════════════════
#  MEDIA — Chalkboard Photo Capture & Session Queueing
# ═══════════════════════════════════════════════════════════════

def take_photo_and_upload():
    # Prevent Linux V4L2 Device Busy conflict if full video recording is rolling
    if state.recording:
        msg = "⚠️ Video recording is currently active on camera. Stop video recording (Key 2 or 7) before taking a high-res photo."
        print(msg)
        send_telegram(msg)
        return msg

    ts = datetime.datetime.now().strftime("%m%d_%H%M%S")
    prefix = f"{state.current_subject}_" if state.current_subject else ""
    filename_only = f"{prefix}photo_{ts}.jpg"
    full_photo_path = os.path.join(PHOTOS_DIR, filename_only)

    # CPU-blended computational photography via fswebcam (5-frame averaging)
    cmd = [
        "fswebcam",
        "-d", KERO_VIDEO_DEVICE,
        "-r", f"{KERO_WIDTH}x{KERO_HEIGHT}",
        "-D", "1",             # Delay to let USB settle
        "-S", "30",            # Skip frames to allow auto-exposure
        "-F", "5",             # Average 5 frames to crush noise & glare
        "--no-banner",
        "--jpeg", "100",       # Max quality
        full_photo_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)

        if not os.path.exists(full_photo_path):
            raise RuntimeError(f"fswebcam execution failed:\n{result.stderr}")

        # Accumulate this board snapshot into the active session queue
        with state.state_lock:
            state.session_photos.append(full_photo_path)
            state.last_photo_time = time.time()
            state.latest_photo_path = full_photo_path
            page_num = len(state.session_photos)

        msg = f"📸 Board Derivation #{page_num} Saved: {filename_only}"
        print(msg)
        log_activity("photo")

        # Instant in-line preview for students watching the channel
        subject_label = state.current_subject if state.current_subject else "General Session"
        caption = (
            f"📸 Chalkboard Note [Page {page_num}] — {subject_label}\n"
            f"⏱️ {datetime.datetime.now().strftime('%d %b %Y, %H:%M')}\n"
            f"💡 Note: All pages will be compiled into a single PDF when the next period begins."
        )
        threading.Thread(
            target=send_telegram_photo,
            args=(full_photo_path, caption),
            daemon=True
        ).start()

        # NOTE: We do NOT upload raw JPEGs to Google Drive to preserve the free 15GB tier.
        # Only the clean compiled PDF lecture notebook is uploaded to Drive at end of class!
        return msg

    except Exception as e:
        err_msg = f"❌ Photo capture failed: {e}"
        print(err_msg)
        send_telegram(err_msg)
        return err_msg


# ═══════════════════════════════════════════════════════════════
#  DIGITAL NOTEBOOK — Multi-Page PDF Compiler
# ═══════════════════════════════════════════════════════════════

def compile_and_publish_session_pdf(photos_to_compile=None, subject_name=None):
    """
    Assembles session chalkboard photos into a clean multi-page PDF notebook.
    Uploads ONLY the final PDF to Google Drive (preserving free cloud storage).
    """
    if photos_to_compile is not None:
        photos = list(photos_to_compile)
        subj = subject_name or "General"
    else:
        with state.state_lock:
            photos = list(state.session_photos)
            subj = subject_name or state.current_subject or "General"
            state.session_photos = []

    if not photos:
        print("ℹ️ No session photos to compile into PDF.")
        return None

    # Filter to files that exist on disk
    valid_photos = [p for p in photos if os.path.exists(p)]
    if not valid_photos:
        print("⚠️ Session photo files are missing from disk.")
        return None

    ts = datetime.datetime.now().strftime("%m%d_%H%M")
    pdf_filename_only = f"{subj}_LectureNotes_{ts}.pdf"
    full_pdf_path = os.path.join(NOTES_DIR, pdf_filename_only)
    print(f"📄 Compiling {len(valid_photos)} chalkboard pages into {pdf_filename_only} for [{subj}]…")

    try:
        pil_images = []
        for path in valid_photos:
            img = Image.open(path).convert("RGB")
            pil_images.append(img)

        # Save as single multi-page PDF document
        first_img = pil_images[0]
        remaining_imgs = pil_images[1:] if len(pil_images) > 1 else []
        first_img.save(
            full_pdf_path,
            save_all=True,
            append_images=remaining_imgs,
            resolution=100.0
        )

        with state.state_lock:
            state.latest_pdf_path = full_pdf_path

        num_pages = len(valid_photos)
        print(f"✅ PDF Compiled successfully: {pdf_filename_only} ({num_pages} pages)")

        caption = (
            f"📚 Complete Lecture Notes: {subj}\n"
            f"📄 {num_pages} Board Derivation Page(s)\n"
            f"📅 Date: {datetime.datetime.now().strftime('%d %B %Y')}\n"
            f"🏫 Project Veronica — Frugal Digital Classroom"
        )

        # 1. Dispatch PDF directly to Telegram students channel
        threading.Thread(
            target=send_telegram_document,
            args=(full_pdf_path, caption),
            daemon=True
        ).start()

        # 2. Upload compiled PDF to Google Drive under Month / Subject folder
        threading.Thread(
            target=upload_to_drive,
            args=(full_pdf_path, FOLDER_ID),
            daemon=True
        ).start()

        return full_pdf_path

    except Exception as e:
        err_msg = f"❌ Failed to compile session PDF: {e}"
        print(err_msg)
        send_telegram(err_msg)
        return None


# ═══════════════════════════════════════════════════════════════
#  MEDIA — Video + Audio (Kero 4K Owl + Mic via FFmpeg)
# ═══════════════════════════════════════════════════════════════

def _build_video_cmd(filename):
    return [
        FFMPEG_BIN, "-y",
        "-thread_queue_size", "1024",
        "-f", "v4l2",
        "-input_format", KERO_INPUT_FORMAT,
        "-video_size", "1920x1080",
        "-framerate", str(KERO_FPS),
        "-i", KERO_VIDEO_DEVICE,
        "-thread_queue_size", "1024",
        "-f", "alsa",
        "-ar", "48000",
        "-ac", "2",
        "-i", KERO_AUDIO_DEVICE,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        filename
    ]


def start_video_audio():
    ts = datetime.datetime.now().strftime("%m%d_%H%M")
    prefix = f"{state.current_subject}_" if state.current_subject else ""
    filename_only = f"{prefix}video_{ts}.mp4"
    full_path = os.path.join(VIDEOS_DIR, filename_only)
    state.raw_filename = full_path

    cmd = _build_video_cmd(full_path)
    print(f"▶️ Video cmd: {' '.join(cmd)}")
    try:
        state.ffmpeg_proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
        state.recording = True
        log_activity("video_start")
        sub_msg = f" [{state.current_subject}]" if state.current_subject else ""
        msg = f"🎥 Recording started{sub_msg} → {filename_only}"
        send_telegram(msg)
        return msg
    except Exception as e:
        msg = f"❌ Video start failed: {e}"
        print(msg)
        send_telegram(msg)
        state.recording = False
        state.ffmpeg_proc = None
        return msg


def stop_video_audio():
    if not (state.ffmpeg_proc and state.recording):
        return "⚠️ No active video recording."
    try:
        if state.ffmpeg_proc.stdin:
            state.ffmpeg_proc.stdin.write(b"q\n")
            state.ffmpeg_proc.stdin.flush()
        state.ffmpeg_proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        state.ffmpeg_proc.kill()
    except Exception as e:
        print(f"⚠️ Stop video exception: {e}")
    finally:
        state.recording = False
        state.ffmpeg_proc = None

    fname = state.raw_filename
    state.raw_filename = None
    if fname and os.path.exists(fname):
        threading.Thread(target=upload_to_drive, args=(fname, FOLDER_ID), daemon=True).start()
        msg = f"🛑 Video stopped → uploading {os.path.basename(fname)}"
    else:
        msg = "🛑 Video stopped (no file generated)"
    send_telegram(msg)
    return msg


# ═══════════════════════════════════════════════════════════════
#  MEDIA — Audio Only
# ═══════════════════════════════════════════════════════════════

def _build_audio_cmd(filename):
    return [
        FFMPEG_BIN, "-y",
        "-f", "alsa",
        "-ar", "48000",
        "-ac", "2",
        "-i", KERO_AUDIO_DEVICE,
        "-c:a", "aac", "-b:a", "256k",
        "-movflags", "+faststart",
        filename
    ]


def start_audio_only(priority=False):
    state.audio_is_priority = priority
    ts = datetime.datetime.now().strftime("%m%d_%H%M")
    prefix = f"{state.current_subject}_" if state.current_subject else ""
    filename_only = f"{prefix}{'PRIORITY_' if priority else ''}audio_{ts}.m4a"
    full_path = os.path.join(VIDEOS_DIR, filename_only)
    state.audio_filename = full_path

    cmd = _build_audio_cmd(full_path)
    print(f"▶️ Audio cmd: {' '.join(cmd)}")
    try:
        state.audio_proc = subprocess.Popen(cmd, stderr=subprocess.DEVNULL)
        state.audio_recording = True
        log_activity("audio_start")
        icon = "🚨" if priority else "🎙️"
        sub_msg = f" [{state.current_subject}]" if state.current_subject else ""
        msg = f"{icon} Audio recording started{sub_msg} → {filename_only}"
        send_telegram(msg)
        return msg
    except Exception as e:
        msg = f"❌ Audio start failed: {e}"
        print(msg)
        send_telegram(msg)
        state.audio_recording = False
        state.audio_proc = None
        state.audio_is_priority = False
        return msg


def stop_audio_only():
    if not state.audio_recording:
        return "⚠️ No active audio recording."
    try:
        if state.audio_proc and state.audio_proc.poll() is None:
            state.audio_proc.send_signal(signal.SIGINT)
            try:
                state.audio_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                state.audio_proc.kill()
    except Exception as e:
        print(f"⚠️ Stop audio exception: {e}")
    finally:
        state.audio_recording = False
        state.audio_proc = None

    fname = state.audio_filename
    state.audio_filename = None
    was_priority = state.audio_is_priority
    state.audio_is_priority = False
    if fname and os.path.exists(fname):
        threading.Thread(target=upload_to_drive, args=(fname, FOLDER_ID, was_priority), daemon=True).start()
        msg = f"🛑 Audio stopped → uploading {os.path.basename(fname)}"
    else:
        msg = "🛑 Audio stopped (no file generated)"
    send_telegram(msg)
    return msg

