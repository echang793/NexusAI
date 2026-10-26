"""Daily record of every account balance and holding (quantity + price).

nw_snapshots.py keeps one coarse reading per month. This keeps one per day so
a change in net worth can be explained afterwards (attribution.py): which part
was the market, which was new shares, which was cash moving in or out.

One entry per calendar day, last COMPLETE reading wins. A reading taken while
some held ticker had no price (so it was valued at cost basis) is stored only
if nothing better exists for that day, and is flagged `complete: false` so
attribution skips it.
"""

import datetime
import json
import math
import os

HISTORY_FILE = os.getenv("DAILY_HISTORY_FILE",
                         os.path.join(os.path.dirname(__file__), "daily_history.json"))
KEEP_DAYS = 800  # ~2 years; the file stays well under 1 MB


def _clean(x):
    """Native, finite float or None — NaN/Inf must never reach the JSON."""
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def load_days() -> dict:
    if not os.path.exists(HISTORY_FILE):
        return {}
    try:
        with open(HISTORY_FILE) as f:
            data = json.load(f)
        days = data.get("days", {}) if isinstance(data, dict) else {}
        return days if isinstance(days, dict) else {}
    except Exception:
        return {}


def _save(days: dict) -> None:
    tmp = HISTORY_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"days": days}, f, separators=(",", ":"), allow_nan=False)
    os.replace(tmp, HISTORY_FILE)


def record_day(day: str, net_worth: float, accounts: dict, positions: list,
               complete: bool = True, analytics: dict | None = None) -> None:
    """Store `day` (YYYY-MM-DD).

    accounts: {name: balance} for the non-ticker accounts (cash, Plaid
    balances, manual accounts). positions: dicts with ticker, account, shares,
    price (+ optional sector)."""
    days = load_days()
    existing = days.get(day)
    if existing and existing.get("complete") and not complete:
        return

    accts = {}
    for name, bal in (accounts or {}).items():
        v = _clean(bal)
        if v is not None:
            accts[name] = round(v)

    holdings = {}
    for p in positions or []:
        q, px = _clean(p.get("shares")), _clean(p.get("price"))
        if q is None or px is None:
            continue
        key = f"{p.get('account', 'Brokerage')}|{p['ticker']}"
        prev = holdings.get(key)
        if prev:  # same ticker twice in one account: merge shares
            prev["q"] = round(prev["q"] + q, 6)
        else:
            holdings[key] = {"q": round(q, 6), "p": round(px, 4), "s": p.get("sector") or "—"}

    nw = _clean(net_worth)
    days[day] = {"netWorth": None if nw is None else round(nw), "accounts": accts,
                 "holdings": holdings, "complete": bool(complete)}
    if analytics:
        days[day]["analytics"] = analytics

    if len(days) > KEEP_DAYS:
        for old in sorted(days)[:len(days) - KEEP_DAYS]:
            del days[old]
    _save(days)


def record_today(net_worth, accounts, positions, complete=True, analytics=None) -> None:
    record_day(datetime.date.today().isoformat(), net_worth, accounts, positions, complete,
               analytics)
