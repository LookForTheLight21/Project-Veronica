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


def get_month_folder(service, parent_id):
    month_name = datetime.datetime.now().strftime("%Y-%m")
    q = (
        f"'{parent_id}' in parents and "
        f"mimeType='application/vnd.google-apps.folder' and "
        f"name='{month_name}' and trashed=false"
    )
    items = service.files().list(q=q, fields="files(id)").execute().get("files", [])
    if items:
        return items[0]["id"]
    folder = service.files().create(
        body={
            "name": month_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id]
        },
        fields="id"
    ).execute()
    return folder["id"]


def upload_to_drive(filename, parent_folder_id=FOLDER_ID, pin_message=False):
    """
    Attempts to upload to Google Drive.
    If network is down, spools the file locally for automatic background retry.
    """
    if not os.path.exists(filename):
        print(f"⚠️ Cannot upload: file {filename} does not exist")
        return False

    try:
        service = get_drive_service()
        folder_id = get_month_folder(service, parent_folder_id)
        meta = {"name": os.path.basename(filename), "parents": [folder_id]}
        media = MediaFileUpload(filename, resumable=True)
        f = service.files().create(
            body=meta,
            media_body=media,
            fields="id,webViewLink"
        ).execute()

        link = f.get("webViewLink", "no-link")
        msg = f"✅ Uploaded to Cloud: {os.path.basename(filename)}\n🔗 {link}"
        if pin_message:
            msg = "📌 [PRIORITY NOTICE] " + msg
        send_telegram(msg, pin=pin_message)
        print(f"📤 {filename} → {link}")
        return True

    except Exception as e:
        print(f"⚠️ Drive upload failed (will queue for offline retry): {e}")
        queue_pending_upload(filename, pin_message)
        return False


# ==============================================================================
# OFFLINE SPOOLING BUFFER (Failure Mode 1 Mitigation)
# ==============================================================================

def queue_pending_upload(filename, pin_message=False):
    """Adds a file to the offline spool buffer."""
    with _spool_lock:
        spool = _load_spool()
        entry = {"filename": filename, "pin": pin_message, "queued_at": time.time()}
        if not any(item["filename"] == filename for item in spool):
            spool.append(entry)
            _save_spool(spool)
            print(f"📦 Spooled {filename} for background retry once network restores.")


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
            if not os.path.exists(fname):
                continue

            try:
                # Test basic connectivity before attempting full drive upload
                service = get_drive_service()
                folder_id = get_month_folder(service, FOLDER_ID)
                meta = {"name": os.path.basename(fname), "parents": [folder_id]}
                media = MediaFileUpload(fname, resumable=True)
                f = service.files().create(
                    body=meta,
                    media_body=media,
                    fields="id,webViewLink"
                ).execute()

                link = f.get("webViewLink", "no-link")
                msg = f"🔄 [Offline Sync Complete] {os.path.basename(fname)}\n🔗 {link}"
                send_telegram(msg, pin=pin)
                print(f"📤 Spool Synced: {fname} → {link}")
            except Exception as e:
                # Network still down or token error, keep in queue
                remaining.append(item)

        with _spool_lock:
            _save_spool(remaining)

