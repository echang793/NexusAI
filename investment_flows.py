"""Contributions, dividends and withdrawals for Plaid-linked investment accounts.

Plaid's investment transactions include cash events per account. Buys and
sells are internal (money stays in the account), so only these are kept:
  cash/contribution, cash/deposit  -> contributions
  cash/dividend                    -> dividends
  cash/withdrawal                  -> withdrawals
Plaid's sign (inflow negative) is flipped so every figure is a positive amount.

The result is monthly totals per account kind (401k / hsa / roth), stored in
investment_flows.json (gitignored: it is real financial data) and rebuilt from
scratch on each sync, so it can never drift or double count.

Caveat: a 401(k) "contribution" can include employer match, which does NOT
count toward the employee deferral limit; HSA employer money does count toward
the HSA limit. contributions.py flags this rather than guessing.
"""

import datetime
import json
import math
import os

FLOWS_FILE = os.getenv("INVESTMENT_FLOWS_FILE",
                       os.path.join(os.path.dirname(__file__), "investment_flows.json"))

# Plaid account subtype -> the key used here and by contributions.py
_KIND = {"401k": "401k", "hsa": "hsa", "roth": "roth", "ira": "roth"}
_EVENT = {"contribution": "contributions", "deposit": "contributions",
          "dividend": "dividends", "withdrawal": "withdrawals"}
MAX_PAGES = 100


class FlowsError(Exception):
    """Malformed investment transaction data; nothing was stored."""


def aggregate(txs, subtype_by_account: dict) -> dict:
    months: dict[str, dict] = {}
    for t in txs:
        kind = _KIND.get(str(subtype_by_account.get(t.get("account_id"), "")).lower())
        event = _EVENT.get(str(t.get("subtype", "")).lower()) if str(t.get("type", "")).lower() == "cash" else None
        if kind is None or event is None:
            continue
        amount = t.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount):
            raise FlowsError(f"bad amount {amount!r} in an investment transaction")
        try:
            month = datetime.date.fromisoformat(str(t.get("date"))).strftime("%Y-%m")
        except ValueError:
            raise FlowsError(f"bad date {t.get('date')!r} in an investment transaction")
        bucket = months.setdefault(month, {}).setdefault(
            kind, {"contributions": 0.0, "dividends": 0.0, "withdrawals": 0.0})
        # Plaid: inflows (contribution/deposit/dividend) are negative, outflows positive.
        bucket[event] += amount if event == "withdrawals" else -amount
    for kinds in months.values():
        for b in kinds.values():
            for k in b:
                b[k] = round(b[k], 2)
    return {"months": months, "synced_at": None}


def ytd(flows: dict, year: int) -> dict:
    out: dict[str, dict] = {}
    for month, kinds in flows["months"].items():
        if not month.startswith(f"{year:04d}-"):
            continue
        for kind, b in kinds.items():
            acc = out.setdefault(kind, {"contributions": 0.0, "dividends": 0.0, "withdrawals": 0.0})
            for k, v in b.items():
                acc[k] = round(acc[k] + v, 2)
    return out


def limit_ytd(flows: dict, year: int) -> dict:
    """YTD contributions for the accounts that have an annual limit."""
    return {k: v["contributions"] for k, v in ytd(flows, year).items() if k in ("401k", "hsa", "roth")}


def trailing_dividends(flows: dict, today: datetime.date) -> float:
    start = (today - datetime.timedelta(days=365)).strftime("%Y-%m")
    total = 0.0
    for month, kinds in flows["months"].items():
        if month >= start:
            total += sum(b["dividends"] for b in kinds.values())
    return round(total, 2)


def load() -> dict:
    try:
        with open(FLOWS_FILE) as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("months"), dict):
            return {"months": data["months"], "synced_at": data.get("synced_at")}
    except Exception:
        pass
    return {"months": {}, "synced_at": None}


def save(flows: dict) -> None:
    tmp = FLOWS_FILE + ".tmp"
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        json.dump(flows, f, separators=(",", ":"), allow_nan=False)
    os.replace(tmp, FLOWS_FILE)


def fetch_all_pages(get_page) -> list:
    """get_page(offset) -> (items, total). Collect until `total` items are in hand."""
    out: list = []
    for _ in range(MAX_PAGES):
        items, total = get_page(len(out))
        if not items and len(out) < total:
            raise FlowsError(f"investment transactions stopped at {len(out)} of {total}")
        out.extend(items)
        if len(out) >= total:
            return out
    raise FlowsError("too many pages of investment transactions")
