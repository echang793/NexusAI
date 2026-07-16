"""Optional Plaid balance sync — OFF by default, opt-in via environment.

Plaid aggregates real bank/brokerage balances. This module is a no-op until you
supply credentials. You connect your own bank logins through Plaid Link and
provide the resulting access token — this code never sees your banking password.

PRICING / CAVEAT: Plaid's free tier is development-only and limited. Production
access (real, ongoing balance pulls) is a PAID plan. Confirm current pricing at
plaid.com/pricing before relying on this. You supply your own keys.

Setup:
    pip install plaid-python                         # optional dependency
    export PLAID_CLIENT_ID=...      PLAID_SECRET=...
    export PLAID_ACCESS_TOKEN=...   PLAID_ENV=production   # or development/sandbox
Then POST /api/sync-balances (or call pull_balances()) to refresh accounts.json.
"""

import os
import datetime

import accounts as ac

PLAID_CLIENT_ID = os.getenv("PLAID_CLIENT_ID", "").strip()
PLAID_SECRET = os.getenv("PLAID_SECRET", "").strip()
PLAID_ACCESS_TOKEN = os.getenv("PLAID_ACCESS_TOKEN", "").strip()
PLAID_ENV = os.getenv("PLAID_ENV", "production").strip()

HAS_PLAID = bool(PLAID_CLIENT_ID and PLAID_SECRET and PLAID_ACCESS_TOKEN)

# Map Plaid account subtypes → NexusAI account types (accounts.ALL_TYPES)
_SUBTYPE_MAP = {
    "checking": "Checking", "savings": "Savings", "hsa": "HSA",
    "money market": "Money Market", "cd": "CD", "cash management": "Cash",
    "401k": "401k Cash", "ira": "IRA Cash", "roth": "IRA Cash",
    "brokerage": "Other Asset", "crypto": "Crypto",
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
    return "Other Asset"


def pull_balances() -> dict:
    """Fetch live balances from Plaid and write them into accounts.json.

    Returns {"ok": bool, ...}. No-op (ok=False) when Plaid isn't configured.
    """
    if not HAS_PLAID:
        return {"ok": False, "reason": "Plaid not configured",
                "hint": "Set PLAID_CLIENT_ID, PLAID_SECRET, PLAID_ACCESS_TOKEN to enable."}

    try:
        from plaid.api import plaid_api
        from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest
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
        resp = client.accounts_balance_get(
            AccountsBalanceGetRequest(access_token=PLAID_ACCESS_TOKEN)
        )

        today = datetime.date.today().isoformat()
        rows = []
        for a in resp["accounts"]:
            bal = a["balances"]
            amount = bal.get("current") or bal.get("available") or 0
            rows.append({
                "name": a.get("name") or a.get("official_name") or "Account",
                "type": _map_type(str(a.get("subtype")), str(a.get("type"))),
                "balance": abs(float(amount)),
                "notes": "Synced via Plaid",
                "updated": today,
            })

        if not rows:
            return {"ok": False, "reason": "Plaid returned no accounts"}

        ac.save_accounts(rows)
        return {"ok": True, "count": len(rows), "synced_at": today}
    except Exception as e:
        return {"ok": False, "reason": f"Plaid error: {type(e).__name__}: {e}"}
