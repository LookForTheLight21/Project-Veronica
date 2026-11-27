"""
Telegram Bot integration for Project Veronica FINAL.
Functions:
  - send_telegram: Send text messages with optional pin
  - send_telegram_photo: Upload and send photo preview directly into Telegram chat
  - send_telegram_document: Send compiled PDF lecture notes directly to chat
  - send_telegram_audio: Send audio/voice files directly to Telegram chat
  - telegram_listener: Long-polling background command dispatcher with interactive student menu
"""
import os
import re
import glob
import json
import time
import datetime
import requests
from config import BASE_DIR, BOT_TOKEN, CHAT_ID, ALLOWED_USERS, NOTES_DIR, VIDEOS_DIR, PHOTOS_DIR
import state

LAST_UPDATE_ID_PATH = os.path.join(BASE_DIR, "last_update_id.txt")

# ==============================================================================
# SUBJECTS LIST (Synced with NFC_MAP in config.py)
# ==============================================================================
SUBJECTS = ["English", "Computer Science", "Physics", "Chemistry", "Math"]

HELP_TEXT = (
    "📋 Project Veronica — Commands\n\n"
    "🏫 /start    — Open Class X Student Menu\n"
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


# ==============================================================================
# TELEGRAM SEND FUNCTIONS
# ==============================================================================

def send_telegram(msg, retries=3, delay=2, pin=False, chat_id=None, reply_markup=None, parse_mode=None):
    """Send text message to Telegram chat with optional inline keyboard."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    target_chat = chat_id or CHAT_ID
    data = {"chat_id": target_chat, "text": msg}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    if parse_mode:
        data["parse_mode"] = parse_mode
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(url, data=data, timeout=10)
            if r.status_code == 200:
                print(f"✅ Telegram text sent: {msg[:60]}")
                if pin:
                    _pin_message(r.json().get("result", {}).get("message_id"), target_chat)
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


def send_telegram_document(doc_path, caption=None, retries=3, delay=2, pin=False, chat_id=None):
    """
    Upload and send a document (e.g. multi-page lecture notes PDF) directly to Telegram.
    Students can open, print, or share the compiled PDF note file immediately.
    """
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    if not os.path.exists(doc_path):
        print(f"⚠️ Document file does not exist: {doc_path}")
        return False

    target_chat = chat_id or CHAT_ID
    for attempt in range(1, retries + 1):
        try:
            with open(doc_path, "rb") as doc_file:
                files = {"document": doc_file}
                data = {"chat_id": target_chat}
                if caption:
                    data["caption"] = caption

                r = requests.post(url, data=data, files=files, timeout=120)
                if r.status_code == 200:
                    print(f"📄 Telegram Document sent: {doc_path}")
                    if pin:
                        _pin_message(r.json().get("result", {}).get("message_id"), target_chat)
                    return True
                print(f"⚠️ Telegram Document HTTP {r.status_code}: {r.text}")
        except Exception as e:
            print(f"⚠️ Telegram Document attempt {attempt}: {e}")
        time.sleep(delay)
    return False


def send_telegram_audio(audio_path, caption=None, retries=3, delay=2, chat_id=None):
    """
    Upload and send an audio file (.m4a / .mp3) directly to Telegram chat.
    Sends as a document so Telegram doesn't truncate or transcode it.
    """
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    if not os.path.exists(audio_path):
        print(f"⚠️ Audio file does not exist: {audio_path}")
        return False

    target_chat = chat_id or CHAT_ID
    # Telegram document upload limit is 50MB via Bot API
    file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
    if file_size_mb > 49:
        print(f"⚠️ Audio file too large for Telegram ({file_size_mb:.1f}MB > 50MB limit): {audio_path}")
        send_telegram(
            f"⚠️ Audio file `{os.path.basename(audio_path)}` is {file_size_mb:.1f}MB which exceeds Telegram's 50MB upload limit.\n"
            f"The file has been uploaded to Google Drive instead.",
            chat_id=target_chat
        )
        return False

    for attempt in range(1, retries + 1):
        try:
            with open(audio_path, "rb") as af:
                files = {"document": af}
                data = {"chat_id": target_chat}
                if caption:
                    data["caption"] = caption

                r = requests.post(url, data=data, files=files, timeout=120)
                if r.status_code == 200:
                    print(f"🎵 Telegram Audio sent: {audio_path}")
                    return True
                print(f"⚠️ Telegram Audio HTTP {r.status_code}: {r.text}")
        except Exception as e:
            print(f"⚠️ Telegram Audio attempt {attempt}: {e}")
        time.sleep(delay)
    return False


def _pin_message(message_id, chat_id=None):
    if not message_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/pinChatMessage",
            data={"chat_id": chat_id or CHAT_ID, "message_id": message_id},
            timeout=5
        )
        print("📌 Message pinned on Telegram channel")
    except Exception as pe:
        print(f"⚠️ Pin failed: {pe}")


def answer_callback_query(callback_query_id, text=None):
    """Acknowledge a callback query to dismiss the loading spinner on the button."""
    try:
        data = {"callback_query_id": callback_query_id}
        if text:
            data["text"] = text
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery",
            data=data, timeout=5
        )
    except Exception:
        pass


# ==============================================================================
# INLINE KEYBOARD BUILDERS
# ==============================================================================

def _build_classroom_keyboard():
    """Main menu: Class X button."""
    return {
        "inline_keyboard": [
            [{"text": "🏫 Class X — Lecture Archive", "callback_data": "class_x"}],
        ]
    }


def _build_subject_keyboard():
    """Subject selection grid after choosing Class X."""
    rows = []
    # 2 subjects per row for clean mobile layout
    for i in range(0, len(SUBJECTS), 2):
        row = []
        for subj in SUBJECTS[i:i+2]:
            emoji = {"English": "📖", "Computer Science": "💻", "Physics": "⚡", "Chemistry": "🧪", "Math": "📐"}.get(subj, "📚")
            row.append({"text": f"{emoji} {subj}", "callback_data": f"subj_{subj}"})
        rows.append(row)
    rows.append([{"text": "⬅️ Back to Main Menu", "callback_data": "main_menu"}])
    return {"inline_keyboard": rows}


def _build_mode_keyboard(subject):
    """Mode selection after choosing a subject: Search, PDFs, Videos, Audio, Date Range."""
    return {
        "inline_keyboard": [
            [
                {"text": "🔍 Search by Date", "callback_data": f"mode_search_{subject}"},
                {"text": "📄 All PDFs", "callback_data": f"mode_pdf_{subject}"},
            ],
            [
                {"text": "🎥 All Videos", "callback_data": f"mode_video_{subject}"},
                {"text": "🎙️ All Audio", "callback_data": f"mode_audio_{subject}"},
            ],
            [
                {"text": "📅 Date Range (Max 7 Days)", "callback_data": f"mode_range_{subject}"},
            ],
            [{"text": "⬅️ Back to Subjects", "callback_data": "class_x"}],
        ]
    }


# ==============================================================================
# LOCAL FILE SEARCH ENGINE
# ==============================================================================

def _parse_file_date(filename):
    """
    Extracts the date from Veronica's file naming convention.
    e.g. 'Physics_photo_1122_230312.jpg' → date string '1122' → (month=11, day=22)
    Returns a datetime.date object or None.
    """
    base = os.path.basename(filename)
    # Match patterns like: Subject_type_MMDD_HHMM.ext or Subject_type_MMDD_HHMMSS.ext
    m = re.search(r'_(?:photo|video|audio|PRIORITY_audio|LectureNotes)_(\d{4})_', base)
    if m:
        date_tag = m.group(1)
        try:
            month = int(date_tag[:2])
            day = int(date_tag[2:])
            # Assume current year
            year = datetime.datetime.now().year
            return datetime.date(year, month, day)
        except (ValueError, OverflowError):
            pass
    return None


def _file_matches_subject(filename, subject):
    """Check if a file belongs to the given subject (case-insensitive prefix match)."""
    base = os.path.basename(filename).lower()
    return base.startswith(subject.lower() + "_")


def _search_local_files(subject, target_date, file_type="all"):
    """
    Search local storage for files matching subject and date.
    file_type: 'all', 'pdf', 'video', 'audio', 'photo'
    Returns dict: {pdfs: [...], videos: [...], audios: [...], photos: [...]}
    """
    results = {"pdfs": [], "videos": [], "audios": [], "photos": []}

    if file_type in ("all", "pdf"):
        for f in glob.glob(os.path.join(NOTES_DIR, "*.pdf")):
            if _file_matches_subject(f, subject):
                fdate = _parse_file_date(f)
                if fdate and fdate == target_date:
                    results["pdfs"].append(f)

    if file_type in ("all", "photo"):
        for f in glob.glob(os.path.join(PHOTOS_DIR, "*.jpg")) + glob.glob(os.path.join(PHOTOS_DIR, "*.jpeg")) + glob.glob(os.path.join(PHOTOS_DIR, "*.png")):
            if _file_matches_subject(f, subject):
                fdate = _parse_file_date(f)
                if fdate and fdate == target_date:
                    results["photos"].append(f)

    if file_type in ("all", "video"):
        for f in glob.glob(os.path.join(VIDEOS_DIR, "*.mp4")):
            if _file_matches_subject(f, subject):
                fdate = _parse_file_date(f)
                if fdate and fdate == target_date:
                    results["videos"].append(f)

    if file_type in ("all", "audio"):
        for f in glob.glob(os.path.join(VIDEOS_DIR, "*.m4a")):
            if _file_matches_subject(f, subject):
                fdate = _parse_file_date(f)
                if fdate and fdate == target_date:
                    results["audios"].append(f)

    return results


def _search_drive_files(subject, target_date, file_type="all"):
    """Search Google Drive for matching files. Returns Drive links."""
    drive_results = {"pdfs": [], "videos": [], "audios": []}
    date_tag = target_date.strftime("%m%d")  # e.g. '1122'

    try:
        from drive_upload import get_drive_service
        service = get_drive_service()
        q = f"name contains '{subject}' and name contains '{date_tag}' and trashed=false"
        items = service.files().list(q=q, fields="files(id, name, webViewLink, mimeType)").execute().get("files", [])
        for item in items:
            name = item.get("name", "")
            link = item.get("webViewLink", "")
            if file_type in ("all", "pdf") and name.lower().endswith(".pdf"):
                drive_results["pdfs"].append((name, link))
            elif file_type in ("all", "video") and name.lower().endswith(".mp4"):
                drive_results["videos"].append((name, link))
            elif file_type in ("all", "audio") and name.lower().endswith(".m4a"):
                drive_results["audios"].append((name, link))
    except Exception as e:
        print(f"ℹ️ Drive search notice: {e}")

    return drive_results


def _parse_date_input(text):
    """
    Parse a date string in DD/MM/YY or DD/MM/YYYY or DD-MM-YY format.
    Returns datetime.date or None.
    """
    text = text.strip()
    for fmt in ("%d/%m/%y", "%d/%m/%Y", "%d-%m-%y", "%d-%m-%Y", "%d.%m.%y", "%d.%m.%Y"):
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_date_range_input(text):
    """
    Parse a date range: 'DD/MM/YY to DD/MM/YY' or 'DD/MM/YY - DD/MM/YY'.
    Returns (start_date, end_date) or (None, None).
    """
    text = text.strip()
    # Split by 'to', '-', or '→'
    parts = re.split(r'\s+(?:to|->|→|-)\s+', text, flags=re.IGNORECASE)
    if len(parts) != 2:
        # Try splitting by just spaces if there are exactly 2 date-like tokens
        parts = text.split()
        if len(parts) == 2:
            pass
        else:
            return None, None

    d1 = _parse_date_input(parts[0])
    d2 = _parse_date_input(parts[1])
    return d1, d2


# ==============================================================================
# CONVERSATION STATE TRACKER (Per-user pending input state)
# ==============================================================================
# Tracks what each user/chat is currently waiting for input on.
# Format: { chat_id_str: {"action": "search_date", "subject": "Physics", "mode": "search"} }
_user_state = {}


def _set_user_state(chat_id, action, subject, mode=None):
    _user_state[str(chat_id)] = {"action": action, "subject": subject, "mode": mode}


def _get_user_state(chat_id):
    return _user_state.get(str(chat_id))


def _clear_user_state(chat_id):
    _user_state.pop(str(chat_id), None)


# ==============================================================================
# CALLBACK QUERY HANDLER (Inline Keyboard Button Presses)
# ==============================================================================

def _handle_callback_query(callback_query):
    """Process an inline keyboard button press from any user."""
    cb_id = callback_query.get("id")
    cb_data = callback_query.get("data", "")
    message = callback_query.get("message", {})
    chat_id = str(message.get("chat", {}).get("id", CHAT_ID))

    # Acknowledge immediately to remove loading spinner
    answer_callback_query(cb_id)

    # ── Main Menu ──
    if cb_data == "main_menu":
        _clear_user_state(chat_id)
        send_telegram(
            "🏫 *Project Veronica — Student Portal*\n\n"
            "Welcome! Select your classroom below to access lecture notes, videos, and audio recordings.",
            chat_id=chat_id,
            reply_markup=_build_classroom_keyboard(),
            parse_mode="Markdown"
        )
        return

    # ── Class X → Show Subjects ──
    if cb_data == "class_x":
        _clear_user_state(chat_id)
        send_telegram(
            "📚 *Class X — Select Subject*\n\n"
            "Choose a subject to browse lecture materials:",
            chat_id=chat_id,
            reply_markup=_build_subject_keyboard(),
            parse_mode="Markdown"
        )
        return

    # ── Subject Selected → Show Mode Buttons ──
    if cb_data.startswith("subj_"):
        subject = cb_data[5:]
        _clear_user_state(chat_id)
        emoji = {"English": "📖", "Computer Science": "💻", "Physics": "⚡", "Chemistry": "🧪", "Math": "📐"}.get(subject, "📚")
        send_telegram(
            f"{emoji} *{subject}*\n\n"
            f"How would you like to browse {subject} materials?",
            chat_id=chat_id,
            reply_markup=_build_mode_keyboard(subject),
            parse_mode="Markdown"
        )
        return

    # ── Mode: Search by Date ──
    if cb_data.startswith("mode_search_"):
        subject = cb_data[12:]
        _set_user_state(chat_id, "await_search_date", subject, "search")
        send_telegram(
            f"🔍 *Search {subject} Materials*\n\n"
            f"Send the date in this format:\n"
            f"`DD/MM/YY`\n\n"
            f"Example: `27/11/26`\n\n"
            f"I'll find all PDFs, videos, photos, and audio for {subject} on that day.",
            chat_id=chat_id,
            parse_mode="Markdown"
        )
        return

    # ── Mode: All PDFs for Subject ──
    if cb_data.startswith("mode_pdf_"):
        subject = cb_data[9:]
        _set_user_state(chat_id, "await_pdf_date", subject, "pdf")
        send_telegram(
            f"📄 *{subject} — PDF Notes*\n\n"
            f"Send the date to get compiled lecture PDFs:\n"
            f"`DD/MM/YY`\n\n"
            f"Example: `22/11/26`",
            chat_id=chat_id,
            parse_mode="Markdown"
        )
        return

    # ── Mode: All Videos for Subject ──
    if cb_data.startswith("mode_video_"):
        subject = cb_data[11:]
        _set_user_state(chat_id, "await_video_date", subject, "video")
        send_telegram(
            f"🎥 *{subject} — Class Videos*\n\n"
            f"Send the date to get class video recordings:\n"
            f"`DD/MM/YY`\n\n"
            f"Example: `22/11/26`",
            chat_id=chat_id,
            parse_mode="Markdown"
        )
        return

    # ── Mode: All Audio for Subject ──
    if cb_data.startswith("mode_audio_"):
        subject = cb_data[11:]
        _set_user_state(chat_id, "await_audio_date", subject, "audio")
        send_telegram(
            f"🎙️ *{subject} — Audio Recordings*\n\n"
            f"Send the date to get audio recordings:\n"
            f"`DD/MM/YY`\n\n"
            f"Example: `22/11/26`",
            chat_id=chat_id,
            parse_mode="Markdown"
        )
        return

    # ── Mode: Date Range ──
    if cb_data.startswith("mode_range_"):
        subject = cb_data[11:]
        _set_user_state(chat_id, "await_date_range", subject, "range")
        send_telegram(
            f"📅 *{subject} — Date Range Search*\n\n"
            f"Send start and end dates (max 7 days apart):\n"
            f"`DD/MM/YY to DD/MM/YY`\n\n"
            f"Example: `20/11/26 to 26/11/26`\n\n"
            f"I'll send you all materials for each day in the range.",
            chat_id=chat_id,
            parse_mode="Markdown"
        )
        return


# ==============================================================================
# DATE INPUT HANDLER (Process user's text reply after a mode button)
# ==============================================================================

def _handle_user_date_input(text, chat_id):
    """
    Handle a text message from a user who is in a pending input state
    (waiting for a date or date range after pressing an inline button).
    Returns True if handled, False if not in a pending state.
    """
    us = _get_user_state(chat_id)
    if not us:
        return False

    action = us["action"]
    subject = us["subject"]
    mode = us.get("mode")

    # ── Date Range Mode ──
    if action == "await_date_range":
        d1, d2 = _parse_date_range_input(text)
        if not d1 or not d2:
            send_telegram(
                "⚠️ Invalid date range format.\n"
                "Please use: `DD/MM/YY to DD/MM/YY`\n"
                "Example: `20/11/26 to 26/11/26`",
                chat_id=chat_id,
                parse_mode="Markdown"
            )
            return True

        # Ensure d1 <= d2
        if d1 > d2:
            d1, d2 = d2, d1

        # Cap at 7 days
        delta = (d2 - d1).days
        if delta > 7:
            send_telegram(
                f"⚠️ Date range too large ({delta} days). Maximum allowed is *7 days* to prevent Telegram flooding.\n"
                f"Please narrow your range.",
                chat_id=chat_id,
                parse_mode="Markdown"
            )
            return True

        _clear_user_state(chat_id)
        send_telegram(
            f"🔍 Searching *{subject}* materials from {d1.strftime('%d/%m/%Y')} to {d2.strftime('%d/%m/%Y')}…",
            chat_id=chat_id,
            parse_mode="Markdown"
        )

        found_anything = False
        current = d1
        while current <= d2:
            day_results = _search_local_files(subject, current, "all")
            drive_results = _search_drive_files(subject, current, "all")

            has_local = any(day_results[k] for k in day_results)
            has_drive = any(drive_results[k] for k in drive_results)

            if has_local or has_drive:
                found_anything = True
                day_str = current.strftime("%d/%m/%Y (%A)")
                header = f"📅 *{day_str}*\n━━━━━━━━━━━━━━━━━━━━━━\n"
                lines = [header]

                # Send local PDFs as documents
                for pdf_path in day_results["pdfs"]:
                    send_telegram_document(pdf_path, caption=f"📄 {subject} Notes — {day_str}", chat_id=chat_id)
                    lines.append(f"📄 `{os.path.basename(pdf_path)}` — Sent above ⬆️")

                # Send local audio files directly
                for audio_path in day_results["audios"]:
                    send_telegram_audio(audio_path, caption=f"🎙️ {subject} Audio — {day_str}", chat_id=chat_id)
                    lines.append(f"🎙️ `{os.path.basename(audio_path)}` — Sent above ⬆️")

                # Videos: too large for Telegram, show Drive links or local note
                for vid_path in day_results["videos"]:
                    size_mb = os.path.getsize(vid_path) / (1024 * 1024)
                    if size_mb <= 49:
                        send_telegram_document(vid_path, caption=f"🎥 {subject} Video — {day_str}", chat_id=chat_id)
                        lines.append(f"🎥 `{os.path.basename(vid_path)}` — Sent above ⬆️")
                    else:
                        lines.append(f"🎥 `{os.path.basename(vid_path)}` ({size_mb:.0f}MB) — Available on Google Drive")

                # Photos
                for photo_path in day_results["photos"]:
                    lines.append(f"📸 `{os.path.basename(photo_path)}`")

                # Drive-only results
                for name, link in drive_results.get("pdfs", []):
                    lines.append(f"📄 `{name}` — 🔗 {link}")
                for name, link in drive_results.get("videos", []):
                    lines.append(f"🎥 `{name}` — 🔗 {link}")
                for name, link in drive_results.get("audios", []):
                    lines.append(f"🎙️ `{name}` — 🔗 {link}")

                send_telegram("\n".join(lines), chat_id=chat_id, parse_mode="Markdown")

            current += datetime.timedelta(days=1)

        if not found_anything:
            send_telegram(
                f"ℹ️ No materials found for *{subject}* in the range {d1.strftime('%d/%m/%Y')} to {d2.strftime('%d/%m/%Y')}.",
                chat_id=chat_id,
                parse_mode="Markdown"
            )

        # Show subject menu again
        send_telegram(
            "What else would you like to look up?",
            chat_id=chat_id,
            reply_markup=_build_mode_keyboard(subject)
        )
        return True

    # ── Single Date Modes (search, pdf, video, audio) ──
    target_date = _parse_date_input(text)
    if not target_date:
        send_telegram(
            "⚠️ Invalid date format.\n"
            "Please use: `DD/MM/YY`\n"
            "Example: `22/11/26`",
            chat_id=chat_id,
            parse_mode="Markdown"
        )
        return True

    _clear_user_state(chat_id)
    day_str = target_date.strftime("%d/%m/%Y (%A)")

    # Determine which file types to search
    if mode == "pdf":
        file_type = "pdf"
    elif mode == "video":
        file_type = "video"
    elif mode == "audio":
        file_type = "audio"
    else:
        file_type = "all"

    send_telegram(
        f"🔍 Searching *{subject}* for {day_str}…",
        chat_id=chat_id,
        parse_mode="Markdown"
    )

    local_results = _search_local_files(subject, target_date, file_type)
    drive_results = _search_drive_files(subject, target_date, file_type)

    has_local = any(local_results[k] for k in local_results)
    has_drive = any(drive_results[k] for k in drive_results)

    if not has_local and not has_drive:
        type_label = {"pdf": "PDF notes", "video": "videos", "audio": "audio recordings"}.get(mode, "materials")
        send_telegram(
            f"ℹ️ No {type_label} found for *{subject}* on {day_str}.\n\n"
            f"💡 Make sure the date and subject are correct.",
            chat_id=chat_id,
            reply_markup=_build_mode_keyboard(subject),
            parse_mode="Markdown"
        )
        return True

    lines = [
        f"📚 *{subject} — {day_str}*",
        "━━━━━━━━━━━━━━━━━━━━━━"
    ]

    # Send local PDFs directly
    for pdf_path in local_results["pdfs"]:
        send_telegram_document(pdf_path, caption=f"📄 {subject} Notes — {day_str}", chat_id=chat_id)
        lines.append(f"📄 `{os.path.basename(pdf_path)}` — Sent above ⬆️")

    # Send local audio files directly
    for audio_path in local_results["audios"]:
        send_telegram_audio(audio_path, caption=f"🎙️ {subject} Audio — {day_str}", chat_id=chat_id)
        lines.append(f"🎙️ `{os.path.basename(audio_path)}` — Sent above ⬆️")

    # Videos
    for vid_path in local_results["videos"]:
        size_mb = os.path.getsize(vid_path) / (1024 * 1024)
        if size_mb <= 49:
            send_telegram_document(vid_path, caption=f"🎥 {subject} Video — {day_str}", chat_id=chat_id)
            lines.append(f"🎥 `{os.path.basename(vid_path)}` — Sent above ⬆️")
        else:
            lines.append(f"🎥 `{os.path.basename(vid_path)}` ({size_mb:.0f}MB) — Available on Google Drive")

    # Photos
    for photo_path in local_results["photos"]:
        lines.append(f"📸 `{os.path.basename(photo_path)}`")

    # Drive-only results
    for name, link in drive_results.get("pdfs", []):
        lines.append(f"📄 `{name}` — 🔗 {link}")
    for name, link in drive_results.get("videos", []):
        lines.append(f"🎥 `{name}` — 🔗 {link}")
    for name, link in drive_results.get("audios", []):
        lines.append(f"🎙️ `{name}` — 🔗 {link}")

    send_telegram("\n".join(lines), chat_id=chat_id, parse_mode="Markdown")

    # Show subject menu again
    send_telegram(
        "What else would you like to look up?",
        chat_id=chat_id,
        reply_markup=_build_mode_keyboard(subject)
    )
    return True


# ==============================================================================
# LEGACY /sr SEARCH COMMAND (Backwards Compatible)
# ==============================================================================

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

    # 2. Check local storage if Drive returned nothing
    if not results["pdfs"] and not results["videos"]:
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
    cleaned = re.sub(r"^/(?:sr|search)[.\s]*", "", text.strip(), flags=re.IGNORECASE).strip()
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

    m = re.match(r"^([a-zA-Z\s]+)[/\s,]+(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})$", cleaned)
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


# ==============================================================================
# /start AND ADMIN COMMAND HANDLER
# ==============================================================================

def _handle_start_command(chat_id):
    """Send the main interactive menu when user types /start."""
    send_telegram(
        "🏫 *Project Veronica — Student Portal*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Welcome to the Class X Digital Lecture Archive!\n\n"
        "📄 Browse compiled *PDF Notes*\n"
        "🎥 Watch *Classroom Video Recordings*\n"
        "🎙️ Listen to *Audio Recordings*\n"
        "🔍 *Search* by date or date range\n\n"
        "Select your classroom below to get started:",
        chat_id=chat_id,
        reply_markup=_build_classroom_keyboard(),
        parse_mode="Markdown"
    )


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


# ==============================================================================
# UPDATE ID PERSISTENCE
# ==============================================================================

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


# ==============================================================================
# MAIN LISTENER (Long-Polling Event Loop)
# ==============================================================================

_listener_running = False


def telegram_listener():
    global _listener_running
    if _listener_running:
        print("⚠️ Telegram listener is already active in this process.")
        return
    _listener_running = True

    print("📡 Telegram listener daemon online (Interactive Student Menu Enabled)")
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
            params = {"timeout": 30, "allowed_updates": ["message", "callback_query"]}
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

                # ── Handle Inline Keyboard Button Presses ──
                if "callback_query" in update:
                    _handle_callback_query(update["callback_query"])
                    continue

                # ── Handle Text Messages ──
                msg_obj = update.get("message", {})
                text = (msg_obj.get("text") or "").strip()
                sender_id = str(msg_obj.get("from", {}).get("id", ""))
                chat_id = str(msg_obj.get("chat", {}).get("id", CHAT_ID))
                if not text:
                    continue
                print(f"📩 [{sender_id} @ {chat_id}] {text}")

                # ── /start is public for all students ──
                if text.lower().startswith("/start"):
                    _handle_start_command(chat_id)
                    continue

                # ── /sr or /search is accessible to all students ──
                if text.lower().startswith("/sr") or text.lower().startswith("/search"):
                    _handle_sr_search_command(text, chat_id=chat_id)
                    continue

                # ── Check if user is in a pending input state (date entry after button press) ──
                if _handle_user_date_input(text, chat_id):
                    continue

                # ── Admin commands require authorization ──
                if text.startswith("/"):
                    if sender_id not in ALLOWED_USERS:
                        send_telegram("🚫 Unauthorized sender.", chat_id=chat_id)
                        continue
                    _handle_telegram_command(text, chat_id=chat_id)
                    continue

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
