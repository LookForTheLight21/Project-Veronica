#!/bin/bash
# ════════════════════════════════════════════════════════════════
#  PROJECT VERONICA — Pi 5 Kiosk Launch Script
#  Run this on the Raspberry Pi 5 to start the full-screen UI
#  on the MPI3501 3.5" display plugged into the GPIO header.
#
#  Usage:  bash launch_kiosk.sh
#  Auto-start: add to /etc/rc.local or systemd service
# ════════════════════════════════════════════════════════════════

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
DASHBOARD_PORT=5000
DASHBOARD_URL="http://localhost:${DASHBOARD_PORT}/pi"

echo "════════════════════════════════════════════════════════"
echo "🚀 Project Veronica — Kiosk Boot Sequence"
echo "   Dashboard URL : $DASHBOARD_URL"
echo "   Project Dir   : $PROJECT_DIR"
echo "════════════════════════════════════════════════════════"

# 1. Disable screen blanking & power management on HDMI/DSI
export DISPLAY=:0
xset s off         2>/dev/null || true
xset -dpms         2>/dev/null || true
xset s noblank     2>/dev/null || true

# 2. Start the Python backend in background (if not already running)
if ! pgrep -f "main.py" > /dev/null; then
    echo "▶  Starting Veronica Core backend…"
    cd "$PROJECT_DIR"
    python3 main.py &
    BACKEND_PID=$!
    echo "   Backend PID: $BACKEND_PID"
    # Wait for Flask to be ready
    sleep 4
else
    echo "✅ Backend already running."
fi

# 3. Wait for Flask to respond
echo "⏳ Waiting for dashboard to be ready…"
for i in $(seq 1 15); do
    if curl -s --max-time 1 "$DASHBOARD_URL" > /dev/null 2>&1; then
        echo "✅ Dashboard ready!"
        break
    fi
    sleep 1
done

# 4. Kill any existing Chromium (clean launch)
pkill -f chromium-browser 2>/dev/null || true
pkill -f chromium         2>/dev/null || true
sleep 1

# 5. Launch Chromium in kiosk mode
echo "🌐 Launching Chromium kiosk → $DASHBOARD_URL"
chromium-browser \
    --kiosk \
    --noerrdialogs \
    --disable-infobars \
    --disable-translate \
    --no-first-run \
    --fast \
    --fast-start \
    --disable-features=TranslateUI \
    --disable-pinch \
    --overscroll-history-navigation=0 \
    --disable-restore-session-state \
    --disable-session-crashed-bubble \
    --disable-background-networking \
    --disable-sync \
    --metrics-recording-only \
    --safebrowsing-disable-auto-update \
    --window-size=800,480 \
    --window-position=0,0 \
    --app="$DASHBOARD_URL" \
    "$DASHBOARD_URL" &

echo "✅ Kiosk launched. Full-screen dashboard active."
echo ""
echo "   To stop:  pkill -f chromium-browser"
echo "   To admin: open http://$(hostname -I | awk '{print $1}'):${DASHBOARD_PORT}/login from any device"

