#!/bin/bash
# Launch streamlit with venv python + prevent mac sleep while running.
# caffeinate -i -w $PID: blocks idle sleep, auto-exits when streamlit PID dies.
set -e
cd "$(dirname "$0")"

if [ ! -x .venv/bin/streamlit ]; then
    echo "Error: .venv/bin/streamlit not found. Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
fi

.venv/bin/streamlit run app.py --server.port 8502 --server.headless true --browser.gatherUsageStats false &
SPID=$!
echo "Streamlit PID: $SPID — keeping Mac awake until it exits."
caffeinate -i -w $SPID &
CPID=$!

trap "kill $SPID $CPID 2>/dev/null; exit 0" INT TERM
wait $SPID
kill $CPID 2>/dev/null || true
