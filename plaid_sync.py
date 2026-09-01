"""Optional Plaid balance sync — OFF by default, opt-in via environment.

Plaid aggregates real bank/brokerage balances. This module is a no-op until you
supply credentials. You connect your own bank logins through Plaid Link — see
scripts/plaid_link.py for the one-time setup that gets you an access token —
this code never sees your banking password.

PRICING / CAVEAT: confirm current pricing/plan limits at plaid.com/pricing
before relying on this — as of writing, Plaid's Trial plan covers up to 10
real production Items (institution logins) at no cost, which comfortably
covers a personal multi-account setup, but this can change.

Only pulls ACCOUNT BALANCES (checking/savings/401k-total/brokerage-total/
etc.), not ticker-level holdings — Plaid's Investments product would be a
separate integration for that. Existing manual accounts (anything without a
plaid_account_id) are left untouched on every sync; only previously-synced
Plaid rows get updated in place, matched by account_id.

Setup:
    pip install plaid-python
    export PLAID_CLIENT_ID=...      PLAID_SECRET=...
    export PLAID_ACCESS_TOKENS=...  PLAID_ENV=production   # comma-separated,
                                     # one token per linked institution
Then POST /api/sync-balances (or call pull_balances()) to refresh accounts.json.
"""

import os
import datetime

import accounts as ac

PLAID_CLIENT_ID = os.getenv("PLAID_CLIENT_ID", "").strip()
PLAID_SECRET = os.getenv("PLAID_SECRET", "").strip()
# PLAID_ACCESS_TOKENS is the current name (comma-separated — one token per
# linked institution, since each Plaid Link session covers one institution).
# PLAID_ACCESS_TOKEN (singular) still works for a single-institution setup.
_TOKENS_RAW = os.getenv("PLAID_ACCESS_TOKENS", "") or os.getenv("PLAID_ACCESS_TOKEN", "")
PLAID_ACCESS_TOKENS = [t.strip() for t in _TOKENS_RAW.split(",") if t.strip()]
PLAID_ENV = os.getenv("PLAID_ENV", "production").strip()

HAS_PLAID = bool(PLAID_CLIENT_ID and PLAID_SECRET and PLAID_ACCESS_TOKENS)

# Map Plaid account subtypes -> NexusAI account types (accounts.ALL_TYPES).
#
# "401k Cash"/"IRA Cash" are for the idle cash SLEEVE inside a retirement
# account, not the account's whole invested balance — using them here would
# repeat the exact bug fixed in accounts.py/server.py on 2026-08-31 (a manual
# 401k entry silently excluded from CoastFIRE's invested total because its
# type wasn't in _INVESTED_MANUAL_TYPES). Plaid's balance for a 401k/IRA/
# brokerage subtype IS the whole account, so it maps to "Retirement"/
# "Taxable" — the types _investable_total() actually looks for.
_SUBTYPE_MAP = {
    "checking": "Checking", "savings": "Savings", "hsa": "HSA",
    "money market": "Money Market", "cd": "CD", "cash management": "Cash",
    "401k": "Retirement", "403b": "Retirement", "ira": "Retirement",
    "roth": "Retirement", "roth 401k": "Retirement", "sep ira": "Retirement",
    "simple ira": "Retirement", "pension": "Retirement",
    "brokerage": "Taxable", "crypto": "Crypto",
    "credit card": "Credit Card", "credit": "Credit Card",
    "mortgage": "Mortgage", "auto": "Auto Loan", "student": "Student Loan",
}


def _map_type(subtype: str, atype: str) -> str:
    s = (subtype or "").lower()
    if s in _SUBTYPE_MAP:
        return _SUBTYPE_MAP[s]
    if (atype or "").lower() == "credit":
        return "Credit Card"
    if (atype or "").lower() == "loan":
        return "Other Liability"
    if (atype or "").lower() == "investment":
        return "Taxable"
    return "Other Asset"


# Account subtypes deliberately NOT synced from Plaid, because NexusAI
# already tracks them precisely via ticker-level holdings CSVs
# (hsa_holdings.csv etc, see scripts/import_holdings.py) — Plaid's balance
# for these is a lump sum covering cash+holdings together, which would
# double-count against the ticker positions already priced individually.
# Discovered 2026-08-31 when a first HSA sync duplicated ~$3.2k this way.
_SKIP_SUBTYPES = {"hsa"}


def _fetch_one(client, access_token: str, today: str) -> list:
    from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest
    resp = client.accounts_balance_get(AccountsBalanceGetRequest(access_token=access_token))
    rows = []
    for a in resp["accounts"]:
        if str(a.get("subtype", "")).lower() in _SKIP_SUBTYPES:
            continue
        bal = a["balances"]
        amount = bal.get("current") or bal.get("available") or 0
        rows.append({
            "name": a.get("name") or a.get("official_name") or "Account",
            "type": _map_type(str(a.get("subtype")), str(a.get("type"))),
            "balance": abs(float(amount)),
            "notes": "Synced via Plaid",
            "updated": today,
            "source": "plaid",
            "plaid_account_id": a.get("account_id"),
        })
    return rows


def _merge(existing: list, synced: list) -> list:
    """Update previously-synced Plaid rows in place (matched by
    plaid_account_id), append newly-seen ones, and leave every manually-
    entered account (no plaid_account_id) completely untouched."""
    by_id = {r["plaid_account_id"]: r for r in synced}
    merged = []
    seen_ids = set()
    for row in existing:
        pid = row.get("plaid_account_id")
        if pid and pid in by_id:
            merged.append(by_id[pid])
            seen_ids.add(pid)
        else:
            merged.append(row)
    for pid, row in by_id.items():
        if pid not in seen_ids:
            merged.append(row)
    return merged


def pull_balances() -> dict:
    """Fetch live balances from Plaid and merge them into accounts.json.

    Returns {"ok": bool, ...}. No-op (ok=False) when Plaid isn't configured.
    """
    if not HAS_PLAID:
        return {"ok": False, "reason": "Plaid not configured",
                "hint": "Set PLAID_CLIENT_ID, PLAID_SECRET, PLAID_ACCESS_TOKENS to enable."}

    try:
        from plaid.api import plaid_api
        from plaid import Configuration, ApiClient
    except Exception:
        return {"ok": False, "reason": "plaid-python not installed",
                "hint": "pip install plaid-python"}

    try:
        hosts = {
            "sandbox": "https://sandbox.plaid.com",
            "development": "https://development.plaid.com",
            "production": "https://production.plaid.com",
        }
        cfg = Configuration(
            host=hosts.get(PLAID_ENV, hosts["production"]),
            api_key={"clientId": PLAID_CLIENT_ID, "secret": PLAID_SECRET},
        )
        client = plaid_api.PlaidApi(ApiClient(cfg))

        today = datetime.date.today().isoformat()
        synced = []
        errors = []
        for token in PLAID_ACCESS_TOKENS:
            try:
                synced.extend(_fetch_one(client, token, today))
            except Exception as e:
                errors.append(f"{type(e).__name__}: {e}")

        if not synced:
            return {"ok": False, "reason": "Plaid returned no accounts",
                     "errors": errors or None}

        existing = ac.load_accounts()
        merged = _merge(existing, synced)
        ac.save_accounts(merged)
        result = {"ok": True, "count": len(synced), "synced_at": today}
        if errors:
            result["partial_errors"] = errors
        return result
    except Exception as e:
        return {"ok": False, "reason": f"Plaid error: {type(e).__name__}: {e}"}
