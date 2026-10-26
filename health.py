"""Run record for the daily refresh + detection of anything that looks broken.

scripts/daily_refresh.py runs its steps through Runner, which keeps going when
one step fails (a Plaid outage shouldn't stop prices and the snapshot) and
writes health.json. scripts/watchdog.py, a separate scheduled job, evaluates
that file — so a job that silently stops running, or runs but half-fails, gets
noticed. (The daily job once failed for a week with nothing flagging it.)
"""

import datetime
import json
import os

HEALTH_FILE = os.path.join(os.path.dirname(__file__), "health.json")
MAX_RUN_AGE_HOURS = 30   # daily job: 24h + slack for a late wake from sleep
PLAID_STALE_DAYS = 3


def write(path: str, record: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(record, f, indent=2)
    os.replace(tmp, path)


def read(path: str) -> dict | None:
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


class Runner:
    """Run steps in order, recording each outcome; a failure never aborts the rest."""

    def __init__(self):
        self.steps: dict = {}
        self.started = datetime.datetime.now().isoformat(timespec="seconds")
        self.extra: dict = {}

    def step(self, name: str, fn):
        try:
            result = fn()
        except Exception as e:  # noqa: BLE001 — the point is to survive and record anything
            self.steps[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            return None
        self.steps[name] = {"ok": True}
        return result

    def finish(self) -> dict:
        rec = {"started": self.started,
               "finished": datetime.datetime.now().isoformat(timespec="seconds"),
               "ok": all(s["ok"] for s in self.steps.values()),
               "steps": self.steps, "unpriced": []}
        rec.update(self.extra)
        return rec


def evaluate(record: dict | None, accounts: list, now: datetime.datetime) -> list[dict]:
    """Return a list of {code, message} problems; empty means all good."""
    if not record:
        return [{"code": "never_ran", "message": "Daily refresh has never recorded a run (health.json missing)."}]
    problems = []
    try:
        finished = datetime.datetime.fromisoformat(record["finished"])
        age_h = (now - finished).total_seconds() / 3600
        if age_h > MAX_RUN_AGE_HOURS:
            problems.append({"code": "stale_run", "message":
                             f"Daily refresh last finished {finished:%b %-d %H:%M} — "
                             f"the 07:30 job isn't running."})
    except (KeyError, ValueError):
        problems.append({"code": "stale_run", "message": "Daily refresh record has no valid finish time."})

    for name, s in (record.get("steps") or {}).items():
        if not s.get("ok"):
            problems.append({"code": "step_failed", "message":
                             f"Daily refresh step '{name}' failed: {s.get('error', 'unknown error')}"})
    if record.get("unpriced"):
        problems.append({"code": "unpriced", "message":
                         "No price for " + ", ".join(record["unpriced"]) +
                         " — valued at cost, net worth understated, month snapshot frozen."})

    today = now.date()
    stale = []
    for a in accounts:
        if a.get("source") != "plaid":
            continue
        try:
            age = (today - datetime.date.fromisoformat(a.get("updated"))).days
        except (TypeError, ValueError):
            continue
        if age > PLAID_STALE_DAYS:
            stale.append(f"{a['name']} ({age}d)")
    if stale:
        problems.append({"code": "plaid_stale", "message":
                         "Plaid balances not updating: " + ", ".join(stale) +
                         " — a bank login may need re-linking."})
    return problems
