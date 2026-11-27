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
import html
import json
import time
import datetime
import urllib.parse
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

def send_telegram(msg, retries=3, delay=2, pin=False, chat_id=None, reply_markup=None, parse_mode=None, disable_web_page_preview=False):
    """Send text message to Telegram chat with optional inline keyboard."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    target_chat = chat_id or CHAT_ID
    data = {"chat_id": target_chat, "text": msg}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    if parse_mode:
        data["parse_mode"] = parse_mode
    if disable_web_page_preview:
        data["disable_web_page_preview"] = "true"
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
    if not m:
        m = re.search(r'_(\d{4})_\d{4,6}\.', base)
    if m:
        date_tag = m.group(1)
        try:
            month = int(date_tag[:2])
            day = int(date_tag[2:])
            year = datetime.datetime.now().year
            return datetime.date(year, month, day)
        except (ValueError, OverflowError):
            pass
    return None


def _file_matches_subject(filename, subject):
    """Check if a file belongs to the given subject (case-insensitive prefix match)."""
    base = os.path.basename(filename).lower()
    s = subject.strip().lower()
    if base.startswith(s + "_"):
        return True
    if s in ("math", "mathematics") and (base.startswith("math_") or base.startswith("mathematics_")):
        return True
    return False


def _drive_subject_term(subject):
    s = subject.strip()
    if s.lower() == "mathematics":
        return "Math"
    return s


def _build_local_media_url(filepath, folder):
    """Returns a clickable LAN URL for files stored on the Veronica Hub when Drive link is unavailable."""
    from config import get_lan_ip, POD_SERVER_PORT
    encoded_name = urllib.parse.quote(os.path.basename(filepath))
    return f"http://{get_lan_ip()}:{POD_SERVER_PORT}/media/{folder}/{encoded_name}"


def _classify_extension(filename):
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".pdf":
        return "pdf", "notes"
    if ext in (".mp4", ".mkv", ".avi", ".mov"):
        return "video", "videos"
    if ext in (".m4a", ".mp3", ".wav", ".aac"):
        return "audio", "videos"
    return None, None


def _search_unified_links(subject, target_dates=None, file_type="all"):
    """
    Searches Google Drive (primary) and local storage (fallback) for matching materials.
    target_dates: list/set of datetime.date objects, or None for ALL dates.
    file_type: 'all', 'pdf', 'video', or 'audio'.
    Returns dict: {"pdfs": [(name, link, date_obj)], "videos": [...], "audios": [...]}.
    Never pushes files — only resolves links.
    """
    results = {"pdfs": [], "videos": [], "audios": []}
    seen_names = set()
    date_set = set(target_dates) if target_dates else None
    date_tags = {d.strftime("%m%d") for d in date_set} if date_set else None

    # 1. Search Google Drive once
    try:
        from drive_upload import get_drive_service
        service = get_drive_service()
        drive_subj = _drive_subject_term(subject).replace("'", "\\'")
        if date_tags and len(date_tags) == 1:
            only_tag = next(iter(date_tags))
            q = (
                f"name contains '{drive_subj}' and name contains '{only_tag}' "
                f"and mimeType != 'application/vnd.google-apps.folder' and trashed=false"
            )
        else:
            q = (
                f"name contains '{drive_subj}' "
                f"and mimeType != 'application/vnd.google-apps.folder' and trashed=false"
            )
        items = service.files().list(
            q=q,
            pageSize=1000,
            fields="files(id, name, webViewLink, mimeType)"
        ).execute().get("files", [])

        for item in items:
            name = item.get("name", "")
            if not _file_matches_subject(name, subject):
                continue
            category, _ = _classify_extension(name)
            if not category:
                continue
            if file_type != "all" and category != file_type:
                continue

            fdate = _parse_file_date(name)
            if date_set is not None:
                if fdate is not None:
                    if fdate not in date_set:
                        continue
                elif not any(tag in name for tag in date_tags):
                    continue

            key = name.lower()
            if key in seen_names:
                continue
            seen_names.add(key)

            link = item.get("webViewLink") or (
                f"https://drive.google.com/file/d/{item['id']}/view" if item.get("id") else ""
            )
            if not link:
                continue
            bucket = {"pdf": "pdfs", "video": "videos", "audio": "audios"}[category]
            results[bucket].append((name, link, fdate))
    except Exception as e:
        print(f"ℹ️ Drive search notice: {e}")

    # 2. Check local storage for any files not yet present in Drive results
    local_globs = []
    if file_type in ("all", "pdf"):
        local_globs.append((os.path.join(NOTES_DIR, "*.pdf"), "pdf", "notes"))
    if file_type in ("all", "video"):
        for ext in ("*.mp4", "*.mkv", "*.avi", "*.mov"):
            local_globs.append((os.path.join(VIDEOS_DIR, ext), "video", "videos"))
    if file_type in ("all", "audio"):
        for ext in ("*.m4a", "*.mp3", "*.wav", "*.aac"):
            local_globs.append((os.path.join(VIDEOS_DIR, ext), "audio", "videos"))

    for pattern, category, folder in local_globs:
        for path in glob.glob(pattern):
            name = os.path.basename(path)
            if not _file_matches_subject(name, subject):
                continue
            fdate = _parse_file_date(name)
            if date_set is not None:
                if fdate is not None:
                    if fdate not in date_set:
                        continue
                elif not any(tag in name for tag in date_tags):
                    continue

            key = name.lower()
            if key in seen_names:
                continue
            seen_names.add(key)

            link = _build_local_media_url(path, folder)
            bucket = {"pdf": "pdfs", "video": "videos", "audio": "audios"}[category]
            results[bucket].append((f"{name} (Local Hub)", link, fdate))

    for bucket in results:
        results[bucket].sort(key=lambda entry: (entry[2] or datetime.date.min, entry[0]))

    return results


def _send_chunked_html(chat_id, blocks, reply_markup=None):
    """Sends HTML blocks in one message when <= 4000 chars, or splits cleanly between items."""
    full_text = "\n".join(blocks)
    max_len = 4000
    if len(full_text) <= max_len:
        send_telegram(
            full_text,
            chat_id=chat_id,
            reply_markup=reply_markup,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return

    chunks = []
    current_blocks = []
    current_len = 0
    for block in blocks:
        add_len = len(block) + (1 if current_blocks else 0)
        if current_len + add_len > max_len and current_blocks:
            chunks.append("\n".join(current_blocks))
            current_blocks = [block.lstrip("\n")]
            current_len = len(current_blocks[0])
        else:
            current_blocks.append(block)
            current_len += add_len
    if current_blocks:
        chunks.append("\n".join(current_blocks))

    for idx, chunk in enumerate(chunks):
        kb = reply_markup if idx == len(chunks) - 1 else None
        send_telegram(
            chunk,
            chat_id=chat_id,
            reply_markup=kb,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


def _format_and_send_links_message(chat_id, title_line, results, show_date_per_item=False, reply_markup=None):
    """
    Sends ONE message containing all requested links, keeping PDFs, Videos, and Audios
    strictly separated under distinct sections. Never pushes files.
    """
    blocks = [
        f"<b>{html.escape(title_line)}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
    ]

    category_meta = [
        ("pdfs", "📄", "PDF Lecture Notes"),
        ("videos", "🎥", "Classroom Video Recordings"),
        ("audios", "🎙️", "Audio Recordings"),
    ]

    for key, icon, label in category_meta:
        items = results.get(key, [])
        if not items:
            continue
        blocks.append(f"\n{icon} <b>{label}:</b>")
        for name, link, fdate in items:
            date_prefix = f"[{fdate.strftime('%d/%m')}] " if (show_date_per_item and fdate) else ""
            safe_name = html.escape(name)
            safe_link = html.escape(link)
            blocks.append(f"• {date_prefix}<code>{safe_name}</code>\n  🔗 {safe_link}")

    _send_chunked_html(chat_id, blocks, reply_markup=reply_markup)


def _search_local_files(subject, target_date, file_type="all"):
    """Backwards-compatible single-date local storage search."""
    res = {"pdfs": [], "videos": [], "audios": [], "photos": []}
    date_tag = target_date.strftime("%m%d")
    if file_type in ("all", "pdf"):
        for f in glob.glob(os.path.join(NOTES_DIR, "*.pdf")):
            if _file_matches_subject(f, subject) and (_parse_file_date(f) == target_date or date_tag in os.path.basename(f)):
                res["pdfs"].append(f)
    if file_type in ("all", "video"):
        for f in glob.glob(os.path.join(VIDEOS_DIR, "*.mp4")):
            if _file_matches_subject(f, subject) and (_parse_file_date(f) == target_date or date_tag in os.path.basename(f)):
                res["videos"].append(f)
    if file_type in ("all", "audio"):
        for f in glob.glob(os.path.join(VIDEOS_DIR, "*.m4a")):
            if _file_matches_subject(f, subject) and (_parse_file_date(f) == target_date or date_tag in os.path.basename(f)):
                res["audios"].append(f)
    return res


def _search_drive_files(subject, target_date, file_type="all"):
    """Backwards-compatible single-date Drive search returning {(name, link)} per category."""
    unified = _search_unified_links(subject, target_dates=[target_date], file_type=file_type)
    return {
        "pdfs": [(n, l) for (n, l, _) in unified["pdfs"] if "(Local Hub)" not in n],
        "videos": [(n, l) for (n, l, _) in unified["videos"] if "(Local Hub)" not in n],
        "audios": [(n, l) for (n, l, _) in unified["audios"] if "(Local Hub)" not in n],
    }


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
            f"Send a date (`DD/MM/YY`), a date range (`DD/MM/YY to DD/MM/YY`), or type `all`:\n\n"
            f"Example: `27/11/26`\n\n"
            f"I'll send one message with separate links for PDFs, videos, and audio.",
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
            f"Send a date (`DD/MM/YY`), a date range (`DD/MM/YY to DD/MM/YY`), or type `all`:\n\n"
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
            f"Send a date (`DD/MM/YY`), a date range (`DD/MM/YY to DD/MM/YY`), or type `all`:\n\n"
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
            f"Send a date (`DD/MM/YY`), a date range (`DD/MM/YY to DD/MM/YY`), or type `all`:\n\n"
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
            f"I'll send one message containing all links separated by PDF, video, and audio.",
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
    (waiting for a date, date range, or 'all' after pressing an inline button).
    Always sends links in ONE message (separated by PDF, Video, and Audio) and never pushes files.
    Returns True if handled, False if not in a pending state.
    """
    us = _get_user_state(chat_id)
    if not us:
        return False

    subject = us["subject"]
    mode = us.get("mode", "search")
    action = us["action"]
    cleaned_text = text.strip()

    file_type = {"pdf": "pdf", "video": "video", "audio": "audio"}.get(mode, "all")
    type_label = {"pdf": "PDF notes", "video": "videos", "audio": "audio recordings"}.get(file_type, "materials")

    target_dates = None
    show_date_per_item = False
    title_line = ""

    # ── Explicit Date Range Mode ──
    if action == "await_date_range":
        d1, d2 = _parse_date_range_input(cleaned_text)
        if not d1 or not d2:
            send_telegram(
                "⚠️ Invalid date range format.\n"
                "Please use: `DD/MM/YY to DD/MM/YY`\n"
                "Example: `20/11/26 to 26/11/26`",
                chat_id=chat_id,
                parse_mode="Markdown"
            )
            return True
        if d1 > d2:
            d1, d2 = d2, d1
        delta = (d2 - d1).days
        if delta > 7:
            send_telegram(
                f"⚠️ Date range too large ({delta} days). Maximum allowed is *7 days*.\n"
                f"Please narrow your range.",
                chat_id=chat_id,
                parse_mode="Markdown"
            )
            return True
        target_dates = [d1 + datetime.timedelta(days=i) for i in range(delta + 1)]
        show_date_per_item = True
        title_line = f"📅 {subject} — {d1.strftime('%d/%m/%Y')} to {d2.strftime('%d/%m/%Y')}"

    # ── Single Date / Range / 'all' Modes (search, pdf, video, audio) ──
    elif cleaned_text.lower() == "all":
        target_dates = None
        show_date_per_item = True
        scope_title = {"pdf": "All PDF Notes", "video": "All Videos", "audio": "All Audio"}.get(file_type, "All Materials")
        title_line = f"📚 {subject} — {scope_title}"
    else:
        d1, d2 = _parse_date_range_input(cleaned_text)
        if d1 and d2:
            if d1 > d2:
                d1, d2 = d2, d1
            delta = (d2 - d1).days
            if delta > 7:
                send_telegram(
                    f"⚠️ Date range too large ({delta} days). Maximum allowed is *7 days*.\n"
                    f"Please narrow your range.",
                    chat_id=chat_id,
                    parse_mode="Markdown"
                )
                return True
            target_dates = [d1 + datetime.timedelta(days=i) for i in range(delta + 1)]
            show_date_per_item = True
            title_line = f"📅 {subject} — {d1.strftime('%d/%m/%Y')} to {d2.strftime('%d/%m/%Y')}"
        else:
            target_date = _parse_date_input(cleaned_text)
            if not target_date:
                send_telegram(
                    "⚠️ Invalid date format.\n"
                    "Send `DD/MM/YY` (e.g. `22/11/26`), `DD/MM/YY to DD/MM/YY`, or `all`.",
                    chat_id=chat_id,
                    parse_mode="Markdown"
                )
                return True
            target_dates = [target_date]
            show_date_per_item = False
            title_line = f"📚 {subject} — {target_date.strftime('%d/%m/%Y (%A)')}"

    _clear_user_state(chat_id)
    results = _search_unified_links(subject, target_dates=target_dates, file_type=file_type)
    has_results = any(results[k] for k in ("pdfs", "videos", "audios"))

    if not has_results:
        send_telegram(
            f"ℹ️ No {type_label} found for <b>{html.escape(subject)}</b>.\n\n"
            f"💡 Make sure the date and subject are correct.",
            chat_id=chat_id,
            reply_markup=_build_mode_keyboard(subject),
            parse_mode="HTML"
        )
        return True

    _format_and_send_links_message(
        chat_id,
        title_line,
        results,
        show_date_per_item=show_date_per_item,
        reply_markup=_build_mode_keyboard(subject)
    )
    return True


# ==============================================================================
# LEGACY /sr SEARCH COMMAND (Backwards Compatible)
# ==============================================================================

def search_lecture_materials(subject, dd, mm, yy):
    """
    Searches Google Drive and local storage for lecture notes (PDF),
    video recordings (MP4), and audio recordings (M4A) matching subject & date.
    Returns links only, strictly separated by category.
    """
    try:
        target_date = datetime.date(int(yy), int(mm), int(dd))
        unified = _search_unified_links(subject, target_dates=[target_date], file_type="all")
        return {
            "pdfs": [(name, link) for (name, link, _) in unified["pdfs"]],
            "videos": [(name, link) for (name, link, _) in unified["videos"]],
            "audios": [(name, link) for (name, link, _) in unified["audios"]],
        }
    except Exception as e:
        print(f"ℹ️ Search notice: {e}")
        return {"pdfs": [], "videos": [], "audios": []}


def _handle_sr_search_command(text, chat_id=None):
    """
    Handles student archive search requests:
      e.g. /sr English/23/11/26 or /sr. English/23/11/26
    Always responds with ONE links-only message (PDF, Video, and Audio separated).
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
            "You will receive one message with direct links separated by PDF, Video, and Audio!"
        )
        send_telegram(msg, chat_id=chat_id, parse_mode="Markdown")
        return

    # Support /sr Subject/all as well
    m_all = re.match(r"^([a-zA-Z\s]+)[/\s,]+all$", cleaned, flags=re.IGNORECASE)
    if m_all:
        subject = m_all.group(1).strip().title()
        results = _search_unified_links(subject, target_dates=None, file_type="all")
        if not any(results[k] for k in ("pdfs", "videos", "audios")):
            send_telegram(
                f"ℹ️ <b>No Materials Found</b>\nNo lecture notes, videos, or audio recordings were found for <b>{html.escape(subject)}</b>.",
                chat_id=chat_id,
                parse_mode="HTML"
            )
            return
        _format_and_send_links_message(chat_id, f"📚 Class X Lecture Archive — {subject} (All)", results, show_date_per_item=True)
        return

    m = re.match(r"^([a-zA-Z\s]+)[/\s,]+(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})$", cleaned)
    if not m:
        msg = (
            "⚠️ *Invalid Search Format*\n"
            "Please format your query as:\n"
            "`/sr Subject/DD/MM/YY` (or `/sr Subject/all`)\n"
            "Example: `/sr English/23/11/26`"
        )
        send_telegram(msg, chat_id=chat_id, parse_mode="Markdown")
        return

    raw_subj, dd, mm, yy = m.groups()
    dd = dd.zfill(2)
    mm = mm.zfill(2)
    yy_full = f"20{yy}" if len(yy) == 2 else yy
    subject = raw_subj.strip().title()

    try:
        target_date = datetime.date(int(yy_full), int(mm), int(dd))
    except ValueError:
        send_telegram("⚠️ Invalid calendar date. Use `/sr Subject/DD/MM/YY`.", chat_id=chat_id, parse_mode="Markdown")
        return

    results = _search_unified_links(subject, target_dates=[target_date], file_type="all")
    if not any(results[k] for k in ("pdfs", "videos", "audios")):
        send_telegram(
            f"ℹ️ <b>No Materials Found</b>\n"
            f"No lecture notes, videos, or audio recordings were found for <b>{html.escape(subject)}</b> on <b>{dd}/{mm}/{yy_full}</b>.\n\n"
            f"💡 Double-check the subject name and date.",
            chat_id=chat_id,
            parse_mode="HTML"
        )
        return

    _format_and_send_links_message(
        chat_id,
        f"📚 Class X Lecture Archive — {subject} ({dd}/{mm}/{yy_full})",
        results,
        show_date_per_item=False
    )


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
