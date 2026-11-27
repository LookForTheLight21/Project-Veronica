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
import shutil
from PIL import Image

import state
from config import (
    STORAGE_DIR,
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
from telegram_bot import send_telegram, send_telegram_photo, send_telegram_document, send_telegram_audio
from drive_upload import upload_to_drive
from activity_logger import log_activity


# ═══════════════════════════════════════════════════════════════
#  MEDIA — Chalkboard Photo Capture & Session Queueing
# ═══════════════════════════════════════════════════════════════

def take_photo_and_upload():
    if not os.path.exists(KERO_VIDEO_DEVICE):
        msg = f"❌ Camera hardware not detected: {KERO_VIDEO_DEVICE} is offline or unplugged."
        print(msg)
        return msg

    ts = datetime.datetime.now().strftime("%m%d_%H%M%S")
    prefix = f"{state.current_subject}_" if state.current_subject else ""
    filename_only = f"{prefix}photo_{ts}.jpg"
    full_photo_path = os.path.join(PHOTOS_DIR, filename_only)

    # If full video recording is rolling, grab frame instantaneously from live RAM buffer
    if state.recording and os.path.exists("/dev/shm/live_frame.jpg"):
        try:
            shutil.copyfile("/dev/shm/live_frame.jpg", full_photo_path)
            with state.state_lock:
                state.session_photos.append(full_photo_path)
                state.last_photo_time = time.time()
                state.latest_photo_path = full_photo_path
                page_num = len(state.session_photos)

            msg = f"📸 Board Derivation #{page_num} Saved (from live video feed): {filename_only}"
            print(msg)
            log_activity("photo")
            return msg
        except Exception as e:
            print(f"⚠️ Live frame photo grab failed: {e}")

    # Prevent Linux V4L2 Device Busy conflict if full video recording is rolling
    if state.recording:
        msg = "⚠️ Video recording is currently active on camera."
        print(msg)
        return msg

    # Pause live stream capture worker to release /dev/video0 for fswebcam
    state.camera_pause_event.set()
    time.sleep(0.15)

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

        # NOTE: We do NOT upload raw JPEGs to Telegram or Google Drive to prevent channel spam.
        # All pages are neatly compiled into a single high-res PDF when class ends!
        return msg

    except Exception as e:
        err_msg = f"❌ Photo capture failed: {e}"
        print(err_msg)
        send_telegram("⚠️ Something went wrong with the classroom camera. Please contact the developer.")
        return err_msg
    finally:
        state.camera_pause_event.clear()


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

        caption = f"📚 {subj} Lecture Notes — {num_pages} Pages"

        # 1. Dispatch PDF directly to Telegram students channel
        threading.Thread(
            target=send_telegram_document,
            args=(full_pdf_path, caption),
            daemon=True
        ).start()

        # 2. Upload compiled PDF to Google Drive under Month / Subject folder
        threading.Thread(
            target=upload_to_drive,
            args=(full_pdf_path, FOLDER_ID, False, subj),
            daemon=True
        ).start()

        # 3. Securely clean up any temporary presentation slides beamed during this session
        try:
            slides_dir = os.path.join(STORAGE_DIR, "temp_slides")
            if os.path.exists(slides_dir):
                for f in os.listdir(slides_dir):
                    fp = os.path.join(slides_dir, f)
                    if os.path.isfile(fp):
                        os.remove(fp)
            if hasattr(state, "current_slide_deck"):
                state.current_slide_deck = None
        except Exception as se:
            print(f"ℹ️ Clean session slides notice: {se}")

        return full_pdf_path

    except Exception as e:
        err_msg = f"❌ Failed to compile session PDF: {e}"
        print(err_msg)
        send_telegram("⚠️ Something went wrong compiling today's lecture notes. Please contact the developer.")
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
        filename,
        "-map", "0:v",
        "-c:v", "mjpeg",
        "-q:v", "3",
        "-f", "image2",
        "-update", "1",
        "/dev/shm/live_frame.jpg"
    ]


def start_video_audio():
    if not os.path.exists(KERO_VIDEO_DEVICE):
        msg = f"❌ Video recording failed: Camera {KERO_VIDEO_DEVICE} not detected."
        print(msg)
        return msg

    # Pause live stream capture worker to release /dev/video0 for FFmpeg
    state.camera_pause_event.set()
    time.sleep(0.2)

    ts = datetime.datetime.now().strftime("%m%d_%H%M")
    prefix = f"{state.current_subject}_" if state.current_subject else ""
    filename_only = f"{prefix}video_{ts}.mp4"
    full_path = os.path.join(VIDEOS_DIR, filename_only)
    state.raw_filename = full_path

    cmd = _build_video_cmd(full_path)
    print(f"▶️ Video cmd: {' '.join(cmd)}")
    try:
        log_path = os.path.join(STORAGE_DIR, "ffmpeg_video.log")
        ffmpeg_log = open(log_path, "w")
        state.ffmpeg_proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=ffmpeg_log
        )
        # Give ffmpeg a brief moment to initialize drivers and check for startup failure
        time.sleep(0.5)
        poll = state.ffmpeg_proc.poll()
        if poll is not None:
            state.recording = False
            state.ffmpeg_proc = None
            state.camera_pause_event.clear()
            err_details = ""
            try:
                with open(log_path, "r") as lf:
                    err_lines = [l.strip() for l in lf.readlines() if l.strip()]
                    err_details = " | ".join(err_lines[-3:])
            except Exception:
                pass
            msg = f"❌ Video recording crashed on startup (code {poll}): {err_details}"
            print(msg)
            send_telegram("⚠️ Something went wrong with video recording. Please contact the developer.")
            return msg

        state.recording = True
        log_activity("video_start")
        sub_msg = f" [{state.current_subject}]" if state.current_subject else ""
        msg = f"🎥 Recording started{sub_msg} → {filename_only}"
        return msg
    except Exception as e:
        msg = f"❌ Video start failed: {e}"
        print(msg)
        send_telegram("⚠️ Something went wrong with video recording. Please contact the developer.")
        state.recording = False
        state.ffmpeg_proc = None
        state.camera_pause_event.clear()
        return msg


def stop_video_audio():
    if not (state.ffmpeg_proc and state.recording):
        if state.recording:
            state.recording = False
        state.camera_pause_event.clear()
        return "⚠️ No active video recording."

    proc = state.ffmpeg_proc
    try:
        if proc.poll() is None:
            if proc.stdin:
                try:
                    proc.stdin.write(b"q\n")
                    proc.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
        else:
            print(f"ℹ️ Video process had already exited with code {proc.poll()}")
    except Exception as e:
        print(f"⚠️ Stop video exception: {e}")
    finally:
        state.recording = False
        state.ffmpeg_proc = None
        # Resume live stream capture worker
        state.camera_pause_event.clear()

    fname = state.raw_filename
    current_subj = state.current_subject or "General"
    state.raw_filename = None
    if fname and os.path.exists(fname) and os.path.getsize(fname) > 1024:
        threading.Thread(
            target=upload_to_drive,
            args=(fname, FOLDER_ID, False, current_subj),
            daemon=True
        ).start()
        msg = f"🛑 Video stopped → uploading {os.path.basename(fname)}"
    else:
        msg = "🛑 Video stopped (no file generated)"
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
        log_path = os.path.join(STORAGE_DIR, "ffmpeg_audio.log")
        audio_log = open(log_path, "w")
        state.audio_proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=audio_log
        )
        time.sleep(0.5)
        poll = state.audio_proc.poll()
        if poll is not None:
            state.audio_recording = False
            state.audio_proc = None
            state.audio_is_priority = False
            err_details = ""
            try:
                with open(log_path, "r") as lf:
                    err_lines = [l.strip() for l in lf.readlines() if l.strip()]
                    err_details = " | ".join(err_lines[-3:])
            except Exception:
                pass
            msg = f"❌ Audio recording crashed on startup (code {poll}): {err_details}"
            print(msg)
            send_telegram("⚠️ Something went wrong with audio recording. Please contact the developer.")
            return msg

        state.audio_recording = True
        log_activity("audio_start")
        icon = "🚨" if priority else "🎙️"
        sub_msg = f" [{state.current_subject}]" if state.current_subject else ""
        msg = f"{icon} Audio recording started{sub_msg} → {filename_only}"
        return msg
    except Exception as e:
        msg = f"❌ Audio start failed: {e}"
        print(msg)
        send_telegram("⚠️ Something went wrong with audio recording. Please contact the developer.")
        state.audio_recording = False
        state.audio_proc = None
        state.audio_is_priority = False
        return msg


def stop_audio_only():
    if not state.audio_recording:
        return "⚠️ No active audio recording."
    proc = state.audio_proc
    try:
        if proc and proc.poll() is None:
            if proc.stdin:
                try:
                    proc.stdin.write(b"q\n")
                    proc.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass
            else:
                proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        elif proc:
            print(f"ℹ️ Audio process had already exited with code {proc.poll()}")
    except Exception as e:
        print(f"⚠️ Stop audio exception: {e}")
    finally:
        state.audio_recording = False
        state.audio_proc = None

    fname = state.audio_filename
    current_subj = state.current_subject or "General"
    state.audio_filename = None
    was_priority = state.audio_is_priority
    state.audio_is_priority = False
    if fname and os.path.exists(fname) and os.path.getsize(fname) > 1024:
        # 1. Send audio file directly to Telegram group
        sub_label = f" [{current_subj}]" if current_subj != "General" else ""
        threading.Thread(
            target=send_telegram_audio,
            args=(fname,),
            kwargs={"caption": f"🎙️ Audio Recording{sub_label} — {os.path.basename(fname)}"},
            daemon=True
        ).start()
        # 2. Upload to Google Drive
        threading.Thread(
            target=upload_to_drive,
            args=(fname, FOLDER_ID, was_priority, current_subj),
            daemon=True
        ).start()
        msg = f"🛑 Audio stopped → uploading {os.path.basename(fname)}"
    else:
        msg = "🛑 Audio stopped (no file generated)"
    return msg

