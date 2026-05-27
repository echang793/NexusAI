"""Watchlist persistence: price targets and notes per ticker."""

import json
import os

WATCHLIST_FILE = os.getenv("WATCHLIST_FILE", "watchlist.json")


def load_watchlist(path=None):
    """Load watchlist from JSON. Returns list of dicts."""
    path = path or WATCHLIST_FILE
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_watchlist(items, path=None):
    """Persist watchlist to JSON. Returns cleaned list."""
    path = path or WATCHLIST_FILE
    clean = [_coerce_item(i) for i in (items or [])]
    clean = [i for i in clean if i is not None]
    with open(path, "w") as f:
        json.dump(clean, f, indent=2)
    return clean


def _coerce_item(item):
    ticker = str(item.get("ticker", "")).strip().upper()
    if not ticker:
        return None
    buy_below = item.get("buy_below")
    sell_above = item.get("sell_above")
    return {
        "ticker": ticker,
        "buy_below": float(buy_below) if buy_below not in (None, 0, 0.0, "") else None,
        "sell_above": float(sell_above) if sell_above not in (None, 0, 0.0, "") else None,
        "note": str(item.get("note", "")).strip(),
    }


def check_alerts(items, prices):
    """Check price targets against current prices.

    prices: dict of {ticker: float}
    Returns list of {ticker, type, message}.
    """
    alerts = []
    for item in (items or []):
        ticker = item.get("ticker")
        price = prices.get(ticker)
        if price is None:
            continue
        buy_below = item.get("buy_below")
        sell_above = item.get("sell_above")
        if buy_below is not None and price <= buy_below:
            alerts.append({
                "ticker": ticker,
                "type": "buy",
                "message": (
                    f"🔴 **{ticker}** at ${price:.2f} — "
                    f"at or below your buy target of ${buy_below:.2f}"
                ),
            })
        if sell_above is not None and price >= sell_above:
            alerts.append({
                "ticker": ticker,
                "type": "sell",
                "message": (
                    f"🟢 **{ticker}** at ${price:.2f} — "
                    f"at or above your sell target of ${sell_above:.2f}"
                ),
            })
    return alerts
