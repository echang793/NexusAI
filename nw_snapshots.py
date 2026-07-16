"""Real net-worth snapshots — one bucket per calendar month, persisted to disk.

Self-triggering: every time the app builds data, the current month's snapshot is
recorded (or updated). Stocks auto-price via yfinance, so each monthly snapshot
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


def record_snapshot(net_worth: float, investments: float = 0.0,
                    other_assets: float = 0.0, liabilities: float = 0.0) -> None:
    """Record/update the current calendar month's snapshot (idempotent per month)."""
    if net_worth is None:
        return
    today = datetime.date.today()
    key = f"{today.year:04d}-{today.month:02d}"
    snapshots = _load_raw()
    snapshots[key] = {
        "date": f"{key}-01",
        "value": round(float(net_worth)),
        "investments": round(float(investments)),
        "otherAssets": round(float(other_assets)),
        "liabilities": round(float(liabilities)),
        "recordedAt": today.isoformat(),
    }
    _save_raw(snapshots)


def load_history() -> list:
    """Return sorted list of {date, value, ...} — the shape the chart expects."""
    snapshots = _load_raw()
    out = [snapshots[k] for k in sorted(snapshots.keys())]
    return out


def has_real_history(min_points: int = 2) -> bool:
    return len(_load_raw()) >= min_points
