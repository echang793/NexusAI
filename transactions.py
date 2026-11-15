"""Local store for bank/credit-card transactions synced from Plaid.

Plaid's /transactions/sync is incremental: each call returns what was added,
modified and removed since a cursor. This module validates those payloads,
applies them to transactions.json, and only advances the cursor once a whole
sync has been applied — so a bad or partial response can never leave the store
half-updated (the next run simply retries from the old cursor).

Only the fields the app needs are kept (no locations or counterparties).
Amounts keep Plaid's sign: positive = money leaving the account, negative =
money coming in. cashflow.py interprets them.

The file holds real financial data: gitignored and blocked by the pre-commit
hook. Access tokens are never written here; cursors are keyed by a short hash.
"""

import datetime
import hashlib
import json
import math
import os

TX_FILE = os.getenv("TRANSACTIONS_FILE",
                    os.path.join(os.path.dirname(__file__), "transactions.json"))
KEEP_DAYS = 800
MAX_RESTARTS = 2  # restarts after TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION
_MUTATION = "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION"


class TransactionsError(Exception):
    """Malformed payload or sync failure; nothing was written."""


class NotReady(TransactionsError):
    """Plaid is still preparing this Item's history (typical right after linking).
    Not a failure: nothing is stored and the next run simply tries again."""


def item_key(access_token: str) -> str:
    """Stable, non-reversible id for a linked institution (never the token)."""
    return hashlib.sha256(access_token.encode()).hexdigest()[:12]


def to_plain(obj):
    """Plaid model object (or dict) -> plain dict with ISO date strings."""
    if hasattr(obj, "to_dict"):
        obj = obj.to_dict()
    if isinstance(obj, dict):
        return {k: to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_plain(v) for v in obj]
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    return obj


def load() -> dict:
    try:
        with open(TX_FILE) as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("txns"), dict):
            return {"cursors": data.get("cursors") or {}, "txns": data["txns"]}
    except Exception:
        pass
    return {"cursors": {}, "txns": {}}


def get_cursor(key: str):
    return load()["cursors"].get(key)


def _save(data: dict) -> None:
    tmp = TX_FILE + ".tmp"
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        json.dump(data, f, separators=(",", ":"), allow_nan=False)
    os.replace(tmp, TX_FILE)


def _clean(raw) -> dict:
    t = to_plain(raw)
    if not isinstance(t, dict):
        raise TransactionsError(f"transaction is not an object: {t!r}")
    tid = t.get("transaction_id")
    if not isinstance(tid, str) or not tid:
        raise TransactionsError("transaction without a transaction_id")
    amount = t.get("amount")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount):
        raise TransactionsError(f"{tid}: amount {amount!r} is not a finite number")
    try:
        date = datetime.date.fromisoformat(str(t.get("date")))
    except ValueError:
        raise TransactionsError(f"{tid}: bad date {t.get('date')!r}")
    cat = t.get("personal_finance_category") or {}
    return {"id": tid, "account": t.get("account_id") or "", "date": date.isoformat(),
            "amount": float(amount), "name": t.get("name") or "",
            "merchant": t.get("merchant_name") or "",
            "cat": cat.get("primary") or "", "detailed": cat.get("detailed") or "",
            "pending": bool(t.get("pending"))}


def apply_sync(key: str, added, modified, removed, cursor) -> None:
    """Validate everything first, then write once. Raises TransactionsError
    (writing nothing, cursor unchanged) if any piece is malformed."""
    for name, part in (("added", added), ("modified", modified), ("removed", removed)):
        if not isinstance(part, (list, tuple)):
            raise TransactionsError(f"sync payload '{name}' is missing or not a list")
    if not isinstance(cursor, str) or not cursor:
        raise TransactionsError("sync payload has no next_cursor")
    new_rows = [_clean(r) for r in list(added) + list(modified)]
    gone = []
    for r in removed:
        rid = to_plain(r).get("transaction_id") if r is not None else None
        if not isinstance(rid, str) or not rid:
            raise TransactionsError("removed entry without a transaction_id")
        gone.append(rid)

    data = load()
    for row in new_rows:
        data["txns"][row["id"]] = row
    for rid in gone:
        data["txns"].pop(rid, None)
    cutoff = (datetime.date.today() - datetime.timedelta(days=KEEP_DAYS)).isoformat()
    data["txns"] = {i: r for i, r in data["txns"].items() if r["date"] >= cutoff}
    data["cursors"][key] = cursor
    _save(data)


def fetch_all(sync_fn, cursor):
    """Page through sync_fn(cursor) -> {added, modified, removed, next_cursor,
    has_more}. Returns (added, modified, removed, final_cursor). If Plaid
    reports the data changed mid-pagination, restart from the original cursor
    (discarding what was collected) up to MAX_RESTARTS times."""
    start = cursor
    for attempt in range(MAX_RESTARTS + 1):
        added, modified, removed, cur = [], [], [], start
        try:
            while True:
                page = sync_fn(cur)
                for k in ("added", "modified", "removed"):
                    if not isinstance(page.get(k), list):
                        raise TransactionsError(f"sync page missing '{k}' list")
                if not isinstance(page.get("next_cursor"), str):
                    raise TransactionsError("sync page missing next_cursor")
                empty = not (page["added"] or page["modified"] or page["removed"])
                if page.get("transactions_update_status") == "NOT_READY" or (page["next_cursor"] == "" and empty):
                    raise NotReady("transactions not ready yet")
                if page["next_cursor"] == "":
                    raise TransactionsError("sync page has data but no next_cursor")
                added += page["added"]
                modified += page["modified"]
                removed += page["removed"]
                cur = page["next_cursor"]
                if not page.get("has_more"):
                    return added, modified, removed, cur
        except TransactionsError:
            raise
        except Exception as e:  # noqa: BLE001
            if _MUTATION in str(e):
                continue
            raise
    raise TransactionsError("transaction data kept changing during sync; will retry next run")
