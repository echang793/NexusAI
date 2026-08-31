#!/bin/bash
# Restart-safe launcher for server.py (Flask).
#
# Why this exists: running `python3 server.py &` by hand doesn't kill any
# previous instance first. A stale process can sit on the port for weeks —
# code/data edits never reach it, but curl/browser traffic still succeeds,
# so nothing *looks* broken. (This is exactly what happened Aug 31 2026: a
# 401k account fix sat unpicked-up by a 2-week-old zombie server through
# several "restarts.") This script kills whatever's already on the port
# before starting a fresh process, so a restart is actually a restart.
#
# Usage: scripts/run_server.sh [port]   (default 5001 — port 5000 is
# usually taken by macOS ControlCenter/AirPlay Receiver on this machine)
set -e
cd "$(dirname "$0")/.."

PORT="${1:-5001}"
PIDFILE=".server.pid"
LOGFILE="server.log"

if [ ! -x .venv/bin/python3 ]; then
    echo "Error: .venv/bin/python3 not found. Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
fi

# Kill whatever's actually listening on the port (covers zombies started
# outside this script too, not just ones we tracked via PIDFILE).
EXISTING_PID=$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null || true)
if [ -n "$EXISTING_PID" ]; then
    echo "Killing existing process on port $PORT (PID $EXISTING_PID)..."
    kill $EXISTING_PID
    sleep 1
    # Force-kill if it's still alive after a second.
    if kill -0 $EXISTING_PID 2>/dev/null; then
        kill -9 $EXISTING_PID
    fi
fi

PORT="$PORT" nohup .venv/bin/python3 server.py > "$LOGFILE" 2>&1 &
NEW_PID=$!
echo $NEW_PID > "$PIDFILE"
sleep 2

if ! kill -0 $NEW_PID 2>/dev/null; then
    echo "Server failed to start — check $LOGFILE"
    tail -20 "$LOGFILE"
    exit 1
fi

echo "NexusAI running: PID $NEW_PID, http://localhost:$PORT (log: $LOGFILE, pidfile: $PIDFILE)"
