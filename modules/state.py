"""
Global mutable state for Project Veronica FINAL.
All shared flags, processes, session photo queues, and link statuses live here.
"""
from threading import Lock

# Recording states & processes
recording         = False
ffmpeg_proc       = None
raw_filename      = None

audio_recording   = False
audio_proc        = None
audio_filename    = None
audio_is_priority = False

# Active subject context & session note accumulator
current_subject   = None
session_photos    = []       # Accumulates chalkboard snapshots taken during current class
last_photo_time   = 0.0      # Timestamp of last captured board note
session_start_ts  = 0.0
state_lock        = Lock()

# Latest assets for classroom projector display & back-bench view
latest_photo_path = None
latest_pdf_path   = None

# Tier 1 ESP32 Pod telemetry
pod_connected     = False
pod_last_seen     = 0.0
pod_ip            = "None"

# Security passcode state machine (tamper prevention)
secure_target_action = None
secure_current_step  = 0
secure_timer         = 0.0

