"""Real net-worth snapshots — one bucket per calendar month, persisted to disk.

Self-triggering: every time the app builds data, the current month's snapshot is
recorded if it doesn't exist yet (first reading of the month wins). Stocks auto-price via yfinance, so each monthly snapshot
captures real growth with zero manual input. Cash/HYSA balances carry forward
from accounts.json until the user changes them.
"""

import json
import os
import datetime

SNAPSHOT_FILE = os.getenv("NW_HISTORY_FILE",
                          os.path.join(os.path.dirname(__file__), "nw_history.json"))


def _load_raw() -> dict:
    if not os.path.exists(SNAPSHOT_FILE):
        return {}
    try:
        with open(SNAPSHOT_FILE, "r") as f:
            data = json.load(f)
        return data.get("snapshots", {}) if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_raw(snapshots: dict) -> None:
    try:
        tmp = SNAPSHOT_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"snapshots": snapshots}, f, indent=2)
        os.replace(tmp, SNAPSHOT_FILE)
    except Exception:
        pass


# True makes record_snapshot overwrite an existing month. Set by
# scripts/monthly_snapshot.py --force: the write happens deep inside
# server.build_nexus_data, where a parameter can't be passed through.
OVERWRITE_EXISTING = False


def record_snapshot(net_worth: float, investments: float = 0.0,
                    other_assets: float = 0.0, liabilities: float = 0.0,
                    force: bool | None = None, details: dict | None = None) -> None:
    """Record the current calendar month's snapshot — first reading wins.

    Net worth is tracked as one comparable reading per month (the first taken
    that month, normally the 1st-of-month job). Later runs the same month are
    ignored so the daily refresh and dashboard can't drift the value toward
    month-end. Pass force=True (or run monthly_snapshot.py --force) to
    deliberately re-record, e.g. after manually updating holdings.

    `details` (optional) is stored alongside the totals — per-account balances
    and CoastFIRE numbers — so scripts/monthly_report.py can compare months.
    """
    if net_worth is None:
        return
    if force is None:
        force = OVERWRITE_EXISTING
    today = datetime.date.today()
    key = f"{today.year:04d}-{today.month:02d}"
    snapshots = _load_raw()
    if key in snapshots and not force:
        return
    snapshots[key] = {
        "date": f"{key}-01",
        "value": round(float(net_worth)),
        "investments": round(float(investments)),
        "otherAssets": round(float(other_assets)),
        "liabilities": round(float(liabilities)),
        "recordedAt": today.isoformat(),
    }
    if details:
        snapshots[key]["details"] = details
    _save_raw(snapshots)


def load_history() -> list:
    """Return sorted list of {date, value, ...} — the shape the chart expects."""
    snapshots = _load_raw()
    out = [snapshots[k] for k in sorted(snapshots.keys())]
    return out


def has_real_history(min_points: int = 2) -> bool:
    return len(_load_raw()) >= min_points
