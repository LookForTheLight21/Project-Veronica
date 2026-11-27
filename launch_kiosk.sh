#!/bin/bash
# ════════════════════════════════════════════════════════════════
#  PROJECT VERONICA — Pi 5 Kiosk Launch Script
#  Works on both Wayland (labwc/wayfire) and X11, and keeps
#  the foreground process alive for systemd Type=simple.
# ════════════════════════════════════════════════════════════════

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
DASHBOARD_PORT=5000
DASHBOARD_URL="http://localhost:${DASHBOARD_PORT}/pi"
USER_ID="$(id -u)"

echo "════════════════════════════════════════════════════════"
echo "🚀 Project Veronica — Kiosk Boot Sequence"
echo "   Dashboard URL : $DASHBOARD_URL"
echo "   Project Dir   : $PROJECT_DIR"
echo "════════════════════════════════════════════════════════"

# 1. Environment for both Wayland (Pi 5 default) and X11
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/${USER_ID}}"
export DISPLAY="${DISPLAY:-:0}"

if [ -S "${XDG_RUNTIME_DIR}/wayland-0" ]; then
    export WAYLAND_DISPLAY="wayland-0"
elif [ -S "${XDG_RUNTIME_DIR}/wayland-1" ]; then
    export WAYLAND_DISPLAY="wayland-1"
fi

if [ -f "${HOME}/.Xauthority" ]; then
    export XAUTHORITY="${HOME}/.Xauthority"
fi

# Disable X11 screen blanking if X11/XWayland is active
xset s off     2>/dev/null || true
xset -dpms     2>/dev/null || true
xset s noblank 2>/dev/null || true

# 2. Start the Python backend if not already running
if ! pgrep -f "python.*main.py" > /dev/null; then
    echo "▶  Starting Veronica Core backend…"
    cd "$PROJECT_DIR" || exit 1
    python3 main.py &
    BACKEND_PID=$!
    echo "   Backend PID: $BACKEND_PID"
    sleep 3
else
    echo "✅ Backend already running."
fi

# 3. Wait for Flask dashboard to respond
echo "⏳ Waiting for dashboard to be ready…"
for i in $(seq 1 20); do
    if curl -s --max-time 1 "$DASHBOARD_URL" > /dev/null 2>&1; then
        echo "✅ Dashboard ready!"
        break
    fi
    sleep 1
done

# 4. Find Chromium binary (Bookworm uses 'chromium', older OS uses 'chromium-browser')
CHROMIUM_BIN="$(command -v chromium-browser || command -v chromium || command -v google-chrome || true)"
if [ -z "$CHROMIUM_BIN" ]; then
    echo "❌ Error: Chromium is not installed! Run: sudo apt install -y chromium"
    exit 1
fi

# 5. Clean any stale Chromium kiosk instances
pkill -f "chromium.*${DASHBOARD_PORT}" 2>/dev/null || true
sleep 1

# 6. Launch Chromium in foreground (no '&' so systemd does not kill the cgroup!)
echo "🌐 Launching $CHROMIUM_BIN kiosk → $DASHBOARD_URL"
exec "$CHROMIUM_BIN" \
    --kiosk \
    --ozone-platform-hint=auto \
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
    "$DASHBOARD_URL"
