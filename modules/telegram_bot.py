"""
Telegram Bot integration for Project Veronica FINAL.
Functions:
  - send_telegram: Send text messages with optional pin
  - send_telegram_photo: Upload and send photo preview directly into Telegram chat
  - send_telegram_document: Send compiled PDF lecture notes directly to chat
  - telegram_listener: Long-polling background command dispatcher
"""
import os
import time
import requests
from config import BASE_DIR, BOT_TOKEN, CHAT_ID, ALLOWED_USERS
import state

LAST_UPDATE_ID_PATH = os.path.join(BASE_DIR, "last_update_id.txt")

HELP_TEXT = (
    "📋 Project Veronica — Commands\n\n"
    "📸 /photo    — Snap chalkboard note\n"
    "📚 /notes    — End class & compile today's board photos into PDF\n"
    "🎥 /video    — Start/toggle video+audio recording\n"
    "🎙 /audio    — Start/toggle audio recording\n"
    "⏹ /stop     — Stop current recording\n"
    "📊 /stats    — Live hardware & system stats\n"
    "📡 /status   — Recording & lectern pod link status\n"
    "🔁 /reboot   — Reboot Pi 5\n"
    "❓ /help     — This guide"
)


def send_telegram(msg, retries=3, delay=2, pin=False):
    """Send text message to Telegram chat."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
            if r.status_code == 200:
                print(f"✅ Telegram text sent: {msg[:60]}")
                if pin:
                    _pin_message(r.json().get("result", {}).get("message_id"))
                return True
            print(f"⚠️ Telegram HTTP {r.status_code}: {r.text}")
        except Exception as e:
            print(f"⚠️ Telegram attempt {attempt}: {e}")
        time.sleep(delay)
    return False


def send_telegram_photo(photo_path, caption=None, retries=3, delay=2, pin=False):
    """
    Directly upload and display the chalkboard photo preview in Telegram.
    Allows absent students and teachers to view blackboard notes instantly on their phones.
    """
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    if not os.path.exists(photo_path):
        print(f"⚠️ Photo file does not exist: {photo_path}")
        return False

    for attempt in range(1, retries + 1):
        try:
            with open(photo_path, "rb") as photo_file:
                files = {"photo": photo_file}
                data = {"chat_id": CHAT_ID}
                if caption:
                    data["caption"] = caption

                r = requests.post(url, data=data, files=files, timeout=30)
                if r.status_code == 200:
                    print(f"📸 Telegram Photo Preview sent: {photo_path}")
                    if pin:
                        _pin_message(r.json().get("result", {}).get("message_id"))
                    return True
                print(f"⚠️ Telegram Photo HTTP {r.status_code}: {r.text}")
        except Exception as e:
            print(f"⚠️ Telegram Photo attempt {attempt}: {e}")
        time.sleep(delay)
    return False


def send_telegram_document(doc_path, caption=None, retries=3, delay=2, pin=False):
    """
    Upload and send a document (e.g. multi-page lecture notes PDF) directly to Telegram.
    Students can open, print, or share the compiled PDF note file immediately.
    """
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    if not os.path.exists(doc_path):
        print(f"⚠️ Document file does not exist: {doc_path}")
        return False

    for attempt in range(1, retries + 1):
        try:
            with open(doc_path, "rb") as doc_file:
                files = {"document": doc_file}
                data = {"chat_id": CHAT_ID}
                if caption:
                    data["caption"] = caption

                r = requests.post(url, data=data, files=files, timeout=60)
                if r.status_code == 200:
                    print(f"📄 Telegram Document sent: {doc_path}")
                    if pin:
                        _pin_message(r.json().get("result", {}).get("message_id"))
                    return True
                print(f"⚠️ Telegram Document HTTP {r.status_code}: {r.text}")
        except Exception as e:
            print(f"⚠️ Telegram Document attempt {attempt}: {e}")
        time.sleep(delay)
    return False


def _pin_message(message_id):
    if not message_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/pinChatMessage",
            data={"chat_id": CHAT_ID, "message_id": message_id},
            timeout=5
        )
        print("📌 Message pinned on Telegram channel")
    except Exception as pe:
        print(f"⚠️ Pin failed: {pe}")


def load_last_update_id():
    try:
        with open(LAST_UPDATE_ID_PATH) as f:
            return int(f.read().strip())
    except Exception:
        return None


def save_last_update_id(uid):
    try:
        with open(LAST_UPDATE_ID_PATH, "w") as f:
            f.write(str(uid))
    except Exception as e:
        print(f"⚠️ Save update ID: {e}")


def _handle_telegram_command(cmd):
    from camera import (
        take_photo_and_upload,
        compile_and_publish_session_pdf,
        start_video_audio,
        stop_video_audio,
        start_audio_only,
        stop_audio_only,
    )
    from system_utils import send_stats_report, report_status, reboot_system

    cmd = cmd.lower().split()[0]
    if cmd == "/photo":
        take_photo_and_upload()
    elif cmd in ["/notes", "/endclass", "/pdf"]:
        pdf_res = compile_and_publish_session_pdf()
        if not pdf_res:
            send_telegram("ℹ️ No photos have been snapped in this session yet.")
    elif cmd == "/video":
        if state.recording or state.audio_recording:
            send_telegram("⚠️ Already recording. Send /stop first.")
        else:
            send_telegram(start_video_audio())
    elif cmd == "/audio":
        if state.recording or state.audio_recording:
            send_telegram("⚠️ Already recording. Send /stop first.")
        else:
            send_telegram(start_audio_only())
    elif cmd == "/stop":
        if state.recording:
            send_telegram(stop_video_audio())
        elif state.audio_recording:
            send_telegram(stop_audio_only())
        else:
            send_telegram("ℹ️ Nothing currently recording.")
    elif cmd == "/stats":
        send_telegram(send_stats_report())
    elif cmd == "/status":
        report_status()
    elif cmd == "/reboot":
        reboot_system()
    elif cmd == "/help":
        send_telegram(HELP_TEXT)
    else:
        send_telegram(f"❓ Unknown: {cmd}\nSend /help")


def telegram_listener():
    print("📡 Telegram listener daemon online")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    last_update_id = load_last_update_id()
    while True:
        try:
            params = {"timeout": 30, "allowed_updates": ["message"]}
            if last_update_id is not None:
                params["offset"] = last_update_id + 1
            resp = requests.get(url, params=params, timeout=40)
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                time.sleep(5)
                continue
            for update in data.get("result", []):
                uid = update["update_id"]
                last_update_id = uid
                save_last_update_id(uid)
                msg_obj = update.get("message", {})
                text = (msg_obj.get("text") or "").strip()
                sender_id = str(msg_obj.get("from", {}).get("id", ""))
                if not text:
                    continue
                print(f"📩 [{sender_id}] {text}")
                if sender_id not in ALLOWED_USERS:
                    send_telegram("🚫 Unauthorized sender.")
                    continue
                _handle_telegram_command(text)
        except requests.exceptions.Timeout:
            pass
        except Exception as e:
            print(f"⚠️ Telegram listener: {e}")
            time.sleep(5)

