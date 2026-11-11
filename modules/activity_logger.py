"""
Activity Log — Principal's Record System for Project Veronica FINAL.
Tracks per-subject usage for inspection/authority reports.
Persists to activity_log.json across reboots.
"""
import os
import json
import datetime
import state
from config import BASE_DIR

ACTIVITY_LOG_PATH = os.path.join(BASE_DIR, "activity_log.json")


def load_log():
    try:
        with open(ACTIVITY_LOG_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_log(data):
    try:
        with open(ACTIVITY_LOG_PATH, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"⚠️  Activity log save error: {e}")


def log_activity(action_type):
    """
    Call this every time a subject-tagged action happens.
    action_type: 'photo' | 'video_start' | 'audio_start' | 'subject_change'
    """
    subj = state.current_subject or "Unassigned"
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    now = datetime.datetime.now().strftime("%H:%M")

    data = load_log()

    # Ensure structure exists
    if subj not in data:
        data[subj] = {
            "total_photos": 0,
            "total_videos": 0,
            "total_audios": 0,
            "subject_changes": 0,
            "daily": {}
        }
    if today not in data[subj]["daily"]:
        data[subj]["daily"][today] = {
            "photos": 0,
            "videos": 0,
            "audios": 0,
            "sessions": [],
            "subject_changes": 0
        }

    s = data[subj]
    d = s["daily"][today]

    if action_type == "photo":
        s["total_photos"] += 1
        d["photos"] += 1
        d["sessions"].append({"type": "photo", "time": now})
    elif action_type == "video_start":
        s["total_videos"] += 1
        d["videos"] += 1
        d["sessions"].append({"type": "video_start", "time": now})
    elif action_type == "audio_start":
        s["total_audios"] += 1
        d["audios"] += 1
        d["sessions"].append({"type": "audio_start", "time": now})
    elif action_type == "subject_change":
        s["subject_changes"] += 1
        d["subject_changes"] += 1
        d["sessions"].append({"type": "subject_set", "time": now})

    save_log(data)

