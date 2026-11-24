"""
Telegram Bot integration for Project Veronica FINAL.
Functions:
  - send_telegram: Send text messages with optional pin
  - send_telegram_photo: Upload and send photo preview directly into Telegram chat
  - send_telegram_document: Send compiled PDF lecture notes directly to chat
  - telegram_listener: Long-polling background command dispatcher
"""
import os
import re
import glob
import time
import requests
from config import BASE_DIR, BOT_TOKEN, CHAT_ID, ALLOWED_USERS
import state

LAST_UPDATE_ID_PATH = os.path.join(BASE_DIR, "last_update_id.txt")

HELP_TEXT = (
    "📋 Project Veronica — Commands\n\n"
    "🔍 /sr       — Search past lecture notes & videos (e.g. /sr English/23/11/26)\n"
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


def send_telegram(msg, retries=3, delay=2, pin=False, chat_id=None):
    """Send text message to Telegram chat."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    target_chat = chat_id or CHAT_ID
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(url, data={"chat_id": target_chat, "text": msg}, timeout=10)
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


def search_lecture_materials(subject, dd, mm, yy):
    """
    Searches Google Drive and local storage for lecture notes (PDF)
    and class video recordings (MP4) matching the specified subject and date.
    """
    date_tag = f"{mm}{dd}"
    results = {"pdfs": [], "videos": []}

    # 1. Search Google Drive
    try:
        from drive_upload import get_drive_service
        service = get_drive_service()
        # Query files matching subject and date_tag
        q = f"name contains '{subject}' and name contains '{date_tag}' and trashed=false"
        items = service.files().list(q=q, fields="files(id, name, webViewLink, mimeType)").execute().get("files", [])
        for item in items:
            name = item.get("name", "")
            link = item.get("webViewLink", "")
            if name.lower().endswith(".pdf"):
                results["pdfs"].append((name, link))
            elif name.lower().endswith(".mp4") or name.lower().endswith(".m4a"):
                results["videos"].append((name, link))
    except Exception as e:
        print(f"ℹ️ Google Drive archive search notice: {e}")

    # 2. Check local storage if Drive returned nothing (e.g. offline or un-synced)
    if not results["pdfs"] and not results["videos"]:
        from config import NOTES_DIR, VIDEOS_DIR
        for p in glob.glob(os.path.join(NOTES_DIR, f"*{subject}*{date_tag}*.pdf")):
            results["pdfs"].append((os.path.basename(p), "Stored Locally on Veronica Hub"))
        for p in glob.glob(os.path.join(VIDEOS_DIR, f"*{subject}*{date_tag}*.mp4")):
            results["videos"].append((os.path.basename(p), "Stored Locally on Veronica Hub"))

    return results


def _handle_sr_search_command(text, chat_id=None):
    """
    Handles student archive search requests:
      e.g. /sr English/23/11/26 or /sr. English/23/11/26
    """
    cleaned = re.sub(r"^/(?:sr|search)[\.\s]*", "", text.strip(), flags=re.IGNORECASE).strip()
    if not cleaned:
        msg = (
            "🔍 *Class X Lecture Archive Search*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "To retrieve any past lecture, send:\n"
            "👉 `/sr Subject/DD/MM/YY`\n\n"
            "*Examples:*\n"
            "• `/sr English/23/11/26`\n"
            "• `/sr Physics/24/11/26`\n"
            "• `/sr Math/21/11/26`\n"
            "• `/sr Chemistry/22/11/26`\n"
            "• `/sr Computer Science/23/11/26`\n\n"
            "You will instantly receive direct cloud links for the PDF notes and class video recording!"
        )
        send_telegram(msg, chat_id=chat_id)
        return

    m = re.match(r"^([a-zA-Z\s]+)[/\s,]+(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{2,4})$", cleaned)
    if not m:
        msg = (
            "⚠️ *Invalid Search Format*\n"
            "Please format your query as:\n"
            "`/sr Subject/DD/MM/YY`\n"
            "Example: `/sr English/23/11/26`"
        )
        send_telegram(msg, chat_id=chat_id)
        return

    raw_subj, dd, mm, yy = m.groups()
    dd = dd.zfill(2)
    mm = mm.zfill(2)
    yy_full = f"20{yy}" if len(yy) == 2 else yy
    subject = raw_subj.strip().title()

    send_telegram(f"🔍 Searching Class X archives for *{subject}* on {dd}/{mm}/{yy_full}…", chat_id=chat_id)
    results = search_lecture_materials(subject, dd, mm, yy_full)

    if not results["pdfs"] and not results["videos"]:
        msg = (
            f"ℹ️ *No Materials Found*\n"
            f"No lecture notes or video recordings were found for *{subject}* on *{dd}/{mm}/{yy_full}*.\n\n"
            f"💡 Double-check the subject name and date."
        )
        send_telegram(msg, chat_id=chat_id)
        return

    response_lines = [
        f"📚 *Class X Lecture Archive — {subject}*",
        f"📅 Date: {dd}/{mm}/{yy_full}",
        "━━━━━━━━━━━━━━━━━━━━━━"
    ]
    if results["pdfs"]:
        response_lines.append("\n📄 *PDF Lecture Notes:*")
        for name, link in results["pdfs"]:
            response_lines.append(f"• `{name}`\n  🔗 {link}")
    if results["videos"]:
        response_lines.append("\n🎥 *Classroom Video Recording:*")
        for name, link in results["videos"]:
            response_lines.append(f"• `{name}`\n  🔗 {link}")

    send_telegram("\n".join(response_lines), chat_id=chat_id)


def _handle_telegram_command(cmd, chat_id=None):
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
            send_telegram("ℹ️ No photos have been snapped in this session yet.", chat_id=chat_id)
    elif cmd == "/video":
        if state.recording or state.audio_recording:
            send_telegram("⚠️ Already recording. Send /stop first.", chat_id=chat_id)
        else:
            send_telegram(start_video_audio(), chat_id=chat_id)
    elif cmd == "/audio":
        if state.recording or state.audio_recording:
            send_telegram("⚠️ Already recording. Send /stop first.", chat_id=chat_id)
        else:
            send_telegram(start_audio_only(), chat_id=chat_id)
    elif cmd == "/stop":
        if state.recording:
            send_telegram(stop_video_audio(), chat_id=chat_id)
        elif state.audio_recording:
            send_telegram(stop_audio_only(), chat_id=chat_id)
        else:
            send_telegram("ℹ️ Nothing currently recording.", chat_id=chat_id)
    elif cmd == "/stats":
        send_telegram(send_stats_report(), chat_id=chat_id)
    elif cmd == "/status":
        report_status()
    elif cmd == "/reboot":
        reboot_system()
    elif cmd == "/help":
        send_telegram(HELP_TEXT, chat_id=chat_id)
    else:
        send_telegram(f"❓ Unknown: {cmd}\nSend /help", chat_id=chat_id)


_listener_running = False


def telegram_listener():
    global _listener_running
    if _listener_running:
        print("⚠️ Telegram listener is already active in this process.")
        return
    _listener_running = True

    print("📡 Telegram listener daemon online")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"

    # Clear any active webhook to prevent 409 Conflict with getUpdates long polling
    try:
        del_resp = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook",
            json={"drop_pending_updates": False},
            timeout=10
        )
        if del_resp.status_code == 200:
            print("✅ Telegram webhook cleared (ready for getUpdates polling)")
    except Exception as we:
        print(f"ℹ️ Telegram deleteWebhook notice: {we}")

    last_update_id = load_last_update_id()
    conflict_count = 0
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

            if conflict_count > 0:
                print("✅ Telegram listener conflict resolved — bot is actively receiving commands.")
                conflict_count = 0

            for update in data.get("result", []):
                uid = update["update_id"]
                last_update_id = uid
                save_last_update_id(uid)
                msg_obj = update.get("message", {})
                text = (msg_obj.get("text") or "").strip()
                sender_id = str(msg_obj.get("from", {}).get("id", ""))
                chat_id = str(msg_obj.get("chat", {}).get("id", CHAT_ID))
                if not text:
                    continue
                print(f"📩 [{sender_id} @ {chat_id}] {text}")

                # Public command: /sr or /search is accessible to all students!
                if text.lower().startswith("/sr") or text.lower().startswith("/search"):
                    _handle_sr_search_command(text, chat_id=chat_id)
                    continue

                if sender_id not in ALLOWED_USERS:
                    send_telegram("🚫 Unauthorized sender.", chat_id=chat_id)
                    continue
                _handle_telegram_command(text, chat_id=chat_id)
        except requests.exceptions.Timeout:
            if conflict_count > 0:
                print("✅ Telegram listener polling resumed.")
                conflict_count = 0
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else 0
            if status_code == 409:
                conflict_count += 1
                if conflict_count <= 2:
                    print("⚠️ Telegram listener conflict (409): Another bot client or instance is polling getUpdates.")
                    print("   Backing off to allow single listener stabilization...")
                elif conflict_count == 3:
                    print("⚠️ Telegram 409 conflict persists: Multiple active processes are querying the same bot token.")
                    print("   To terminate background runners: pkill -f 'python.*main.py'")
                backoff = min(30, 5 + conflict_count * 5)
                time.sleep(backoff)
            else:
                conflict_count = 0
                print(f"⚠️ Telegram listener HTTP {status_code}: {e}")
                time.sleep(5)
        except Exception as e:
            print(f"⚠️ Telegram listener: {e}")
            time.sleep(5)

