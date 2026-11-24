"""
Google Drive integration & Non-Volatile Offline Spooling Buffer for Project Veronica.
Functions:
  - upload_to_drive: Uploads media to month-indexed Drive folder.
  - queue_pending_upload: Caches un-uploaded media if network is down.
  - spooler_worker_loop: Background daemon that auto-retries failed uploads upon network restoration.
"""
import os
import time
import json
import datetime
import threading
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from config import BASE_DIR, SCOPES, TOKEN_PATH, FOLDER_ID
from telegram_bot import send_telegram

SPOOL_FILE = os.path.join(BASE_DIR, "pending_uploads.json")
CREDENTIALS_PATH = os.path.join(BASE_DIR, "credentials.json")
_spool_lock = threading.Lock()
_folder_lock = threading.Lock()
_folder_cache = {}


def get_drive_service():
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, "w") as tok:
            tok.write(creds.to_json())
    return build("drive", "v3", credentials=creds)


def get_or_create_subfolder(service, parent_id, folder_name):
    """
    Finds or creates a subfolder by name inside parent_id on Google Drive.
    Caches folder IDs in-memory to prevent redundant API queries.
    """
    cache_key = (parent_id, folder_name)
    with _folder_lock:
        if cache_key in _folder_cache:
            return _folder_cache[cache_key]

    safe_name = folder_name.replace("'", "\\'")
    q = (
        f"'{parent_id}' in parents and "
        f"mimeType='application/vnd.google-apps.folder' and "
        f"name='{safe_name}' and trashed=false"
    )
    items = service.files().list(q=q, fields="files(id, name)").execute().get("files", [])
    if items:
        folder_id = items[0]["id"]
    else:
        folder = service.files().create(
            body={
                "name": folder_name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent_id]
            },
            fields="id"
        ).execute()
        folder_id = folder["id"]

    with _folder_lock:
        _folder_cache[cache_key] = folder_id
    return folder_id


def get_month_folder(service, parent_id):
    """Returns or creates the month folder (e.g. 2026-11) inside parent_id."""
    month_name = datetime.datetime.now().strftime("%Y-%m")
    return get_or_create_subfolder(service, parent_id, month_name)


def get_subject_folder(service, month_folder_id, subject_name):
    """
    Returns or creates a subject subfolder (e.g. Physics, Chemistry, Math)
    inside the month folder.
    """
    subj = str(subject_name).strip() if subject_name and str(subject_name).strip() != "None" else "General"
    return get_or_create_subfolder(service, month_folder_id, subj)


def extract_subject_from_filename(filename, default="General"):
    """
    Extracts the subject tag from standard file naming conventions:
      e.g. 'Physics_LectureNotes_1123_2150.pdf' -> 'Physics'
           'Chemistry_video_1122_2319.mp4'     -> 'Chemistry'
    """
    base = os.path.basename(filename)
    known_subjects = ["Physics", "Chemistry", "Computer Science", "English", "Math", "Extra"]
    for subj in known_subjects:
        if base.startswith(subj + "_") or base.startswith(subj + " "):
            return subj
    parts = base.split("_")
    if len(parts) > 1 and parts[0] and parts[0] not in ["Session", "Snapshot", "video", "audio"]:
        return parts[0]
    try:
        import state
        if state.current_subject and state.current_subject != "None":
            return state.current_subject
    except Exception:
        pass
    return default


def upload_to_drive(filename, parent_folder_id=FOLDER_ID, pin_message=False, subject=None):
    """
    Uploads media directly into Google Drive Month / Subject hierarchy:
      Veronica Root -> Month (YYYY-MM) -> Subject (e.g. Physics) -> File
    If network is down, spools the file locally with subject metadata for automatic background retry.
    """
    if not os.path.exists(filename):
        print(f"⚠️ Cannot upload: file {filename} does not exist")
        return False

    resolved_subj = subject
    if not resolved_subj or resolved_subj == "None":
        resolved_subj = extract_subject_from_filename(filename)

    try:
        service = get_drive_service()
        month_id = get_month_folder(service, parent_folder_id)
        subject_id = get_subject_folder(service, month_id, resolved_subj)

        meta = {"name": os.path.basename(filename), "parents": [subject_id]}
        media = MediaFileUpload(filename, resumable=True)
        f = service.files().create(
            body=meta,
            media_body=media,
            fields="id,webViewLink"
        ).execute()

        link = f.get("webViewLink", "no-link")
        msg = (
            f"✅ Uploaded to Cloud [{resolved_subj}]: {os.path.basename(filename)}\n"
            f"🔗 {link}"
        )
        if pin_message:
            msg = "📌 [PRIORITY NOTICE] " + msg
        send_telegram(msg, pin=pin_message)
        print(f"📤 [{resolved_subj}] {filename} → {link}")
        return True

    except Exception as e:
        print(f"⚠️ Drive upload failed (will queue for offline retry): {e}")
        queue_pending_upload(filename, pin_message, subject=resolved_subj)
        return False


# ==============================================================================
# OFFLINE SPOOLING BUFFER (Failure Mode 1 Mitigation)
# ==============================================================================

def queue_pending_upload(filename, pin_message=False, subject=None):
    """Adds a file to the offline spool buffer with subject metadata."""
    resolved_subj = subject or extract_subject_from_filename(filename)
    with _spool_lock:
        spool = _load_spool()
        entry = {
            "filename": filename,
            "pin": pin_message,
            "subject": resolved_subj,
            "queued_at": time.time()
        }
        if not any(item.get("filename") == filename for item in spool):
            spool.append(entry)
            _save_spool(spool)
            print(f"📦 Spooled [{resolved_subj}] {filename} for background retry once network restores.")


def _load_spool():
    try:
        if os.path.exists(SPOOL_FILE):
            with open(SPOOL_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return []


def _save_spool(spool):
    try:
        with open(SPOOL_FILE, "w") as f:
            json.dump(spool, f, indent=2)
    except Exception as e:
        print(f"⚠️ Spool save error: {e}")


def spooler_worker_loop():
    """
    Background daemon that periodically drains the offline spool buffer
    when school Wi-Fi or mobile hotspot connectivity is restored.
    Uploads directly into Month / Subject subfolder!
    """
    print("📦 Offline Spooling Daemon active")
    while True:
        time.sleep(30)  # Check every 30 seconds
        spool = _load_spool()
        if not spool:
            continue

        remaining = []
        for item in spool:
            fname = item.get("filename")
            pin = item.get("pin", False)
            subj = item.get("subject") or extract_subject_from_filename(fname)
            if not os.path.exists(fname):
                continue

            try:
                # Test basic connectivity before attempting full drive upload
                service = get_drive_service()
                month_id = get_month_folder(service, FOLDER_ID)
                subject_id = get_subject_folder(service, month_id, subj)

                meta = {"name": os.path.basename(fname), "parents": [subject_id]}
                media = MediaFileUpload(fname, resumable=True)
                f = service.files().create(
                    body=meta,
                    media_body=media,
                    fields="id,webViewLink"
                ).execute()

                link = f.get("webViewLink", "no-link")
                msg = (
                    f"🔄 [Offline Sync Complete] [{subj}] {os.path.basename(fname)}\n"
                    f"🔗 {link}"
                )
                send_telegram(msg, pin=pin)
                print(f"📤 Spool Synced: [{subj}] {fname} → {link}")
            except Exception as e:
                # Network still down or token error, keep in queue
                remaining.append(item)

        with _spool_lock:
            _save_spool(remaining)

