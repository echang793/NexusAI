#!/usr/bin/env python3
"""Check the daily refresh's health record and raise a macOS notification when
something is wrong. Scheduled by launchd (scripts/com.nexusai.watchdog.plist),
separately from the job it watches so a dead job can't hide itself.

Every problem is appended to reports/alerts.log. The notification is
de-duplicated: the same set of problems notifies once, then again after 24h if
still unfixed; a new problem notifies immediately; recovery clears the state.

Exit code: 0 = healthy, 1 = problems found.
"""

import datetime
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import health  # noqa: E402

RENOTIFY_HOURS = 24


def _key(problems):
    return "|".join(sorted(p["code"] + ":" + p["message"] for p in problems))


def new_state(problems, now):
    return {"key": _key(problems), "at": now.isoformat(timespec="seconds")}


def should_notify(problems, state, now) -> bool:
    if not problems:
        return False
    if not state or state.get("key") != _key(problems):
        return True
    try:
        last = datetime.datetime.fromisoformat(state["at"])
    except (KeyError, ValueError):
        return True
    return (now - last).total_seconds() >= RENOTIFY_HOURS * 3600


def notify(title: str, message: str) -> None:
    """macOS notification. Quote-escaped; failure to notify must not crash the check."""
    esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')  # noqa: E731
    try:
        subprocess.run(["osascript", "-e",
                        f'display notification "{esc(message)}" with title "{esc(title)}"'],
                       timeout=15, check=False)
    except Exception:
        pass


def run(now: datetime.datetime | None = None) -> int:
    now = now or datetime.datetime.now()
    import accounts as ac
    record = health.read(os.path.join(ROOT, "health.json"))
    problems = health.evaluate(record, ac.load_accounts(os.path.join(ROOT, "accounts.json")), now)

    state_path = os.path.join(ROOT, "alert_state.json")
    try:
        with open(state_path) as f:
            state = json.load(f)
    except Exception:
        state = {}

    if not problems:
        if os.path.exists(state_path):
            os.remove(state_path)
        return 0

    os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
    with open(os.path.join(ROOT, "reports", "alerts.log"), "a") as f:
        for p in problems:
            f.write(f"{now:%Y-%m-%d %H:%M} [{p['code']}] {p['message']}\n")
    if should_notify(problems, state, now):
        first = problems[0]["message"]
        extra = f" (+{len(problems) - 1} more)" if len(problems) > 1 else ""
        notify("NexusAI needs attention", first + extra)
        with open(state_path, "w") as f:
            json.dump(new_state(problems, now), f)
    return 1


if __name__ == "__main__":
    code = run()
    print("watchdog: " + ("problems found, see reports/alerts.log" if code else "all healthy"))
    raise SystemExit(code)
