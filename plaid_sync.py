"""Optional Plaid balance sync — OFF by default, opt-in via environment.

Plaid aggregates real bank/brokerage balances. This module is a no-op until you
supply credentials. You connect your own bank logins through Plaid Link — see
scripts/plaid_link.py for the one-time setup that gets you an access token —
this code never sees your banking password.

PRICING / CAVEAT: confirm current pricing/plan limits at plaid.com/pricing
before relying on this — as of writing, Plaid's Trial plan covers up to 10
real production Items (institution logins) at no cost, which comfortably
covers a personal multi-account setup, but this can change.

Two independent syncs:
  - pull_balances(): account-level balances (checking/savings/401k-total/
    brokerage-total/etc). Existing manual accounts (anything without a
    plaid_account_id) are left untouched; only previously-synced Plaid rows
    get updated in place, matched by account_id. Skips _SKIP_SUBTYPES (see
    below) to avoid double-counting against ticker-tracked accounts.
  - pull_investment_holdings(): ticker-level positions (shares/cost-basis)
    for accounts in _HOLDINGS_SUBTYPE_FILES, via Plaid's Investments Holdings
    endpoint. Overwrites the matching *_holdings.csv wholesale (same
    full-snapshot convention as scripts/import_holdings.py) and updates the
    account's cash sleeve in accounts.json.

Setup:
    pip install plaid-python
    export PLAID_CLIENT_ID=...      PLAID_SECRET=...
    export PLAID_ACCESS_TOKENS=...  PLAID_ENV=production   # comma-separated,
                                     # one token per linked institution
Then POST /api/sync-balances (or call pull_balances()) to refresh accounts.json.
"""

import os
import sys
import datetime

import accounts as ac

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))

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


# Plaid account subtype -> local holdings CSV, for pull_investment_holdings().
# Add an entry here (and to _SKIP_SUBTYPES above) for any other account you'd
# rather have ticker-level-synced than lump-balance-synced.
_HOLDINGS_SUBTYPE_FILES = {"hsa": "hsa_holdings.csv"}


def pull_investment_holdings() -> dict:
    """Fetch ticker-level positions (+ cash sleeve) for accounts listed in
    _HOLDINGS_SUBTYPE_FILES and write them into the matching *_holdings.csv
    (full overwrite, same convention scripts/import_holdings.py uses) plus
    accounts.json's cash-sleeve row for that account.

    Returns {"ok": bool, ...}. No-op (ok=False) when Plaid isn't configured.
    """
    if not HAS_PLAID:
        return {"ok": False, "reason": "Plaid not configured"}

    try:
        from plaid.api import plaid_api
        from plaid import Configuration, ApiClient
        from plaid.model.investments_holdings_get_request import InvestmentsHoldingsGetRequest
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
        by_bucket = {}   # csv filename -> list of {ticker, shares, avg_cost}
        cash_rows = []   # accounts.json rows for the cash sleeve of each matched account
        errors = []
        matched_any = False

        for token in PLAID_ACCESS_TOKENS:
            try:
                resp = client.investments_holdings_get(InvestmentsHoldingsGetRequest(access_token=token))
            except Exception as e:
                errors.append(f"{type(e).__name__}: {e}")
                continue

            accounts_by_id = {a["account_id"]: a for a in resp["accounts"]}
            securities_by_id = {s["security_id"]: s for s in resp["securities"]}

            target_accounts = {
                aid: a for aid, a in accounts_by_id.items()
                if str(a.get("subtype", "")).lower() in _HOLDINGS_SUBTYPE_FILES
            }
            if not target_accounts:
                continue
            matched_any = True

            positions = {aid: [] for aid in target_accounts}
            cash_total = {aid: 0.0 for aid in target_accounts}

            for h in resp["holdings"]:
                aid = h.get("account_id")
                if aid not in target_accounts:
                    continue
                sec = securities_by_id.get(h.get("security_id"), {})
                quantity = float(h.get("quantity") or 0)
                if sec.get("is_cash_equivalent") or sec.get("type") == "cash":
                    cash_total[aid] += float(h.get("institution_value") or 0)
                    continue
                ticker = sec.get("ticker_symbol")
                if not ticker or quantity <= 0:
                    continue  # skip unpriceable/proprietary securities (no ticker) — same
                              # reasoning as the manual 401k entry: can't be held as a CSV
                              # position, would need its own manual-balance account instead
                cost_basis_total = float(h.get("cost_basis") or 0)
                avg_cost = (cost_basis_total / quantity) if quantity else 0.0
                positions[aid].append({"ticker": ticker.upper(), "shares": quantity, "avg_cost": avg_cost})

            for aid, acct in target_accounts.items():
                subtype = str(acct.get("subtype", "")).lower()
                csv_name = _HOLDINGS_SUBTYPE_FILES[subtype]
                by_bucket.setdefault(csv_name, []).extend(positions[aid])
                cash_rows.append({
                    "name": (acct.get("name") or acct.get("official_name") or "Account") + " (Cash)",
                    "type": _map_type(subtype, str(acct.get("type"))),
                    "balance": cash_total[aid],
                    "notes": "Synced via Plaid (cash sleeve)",
                    "updated": today,
                    "source": "plaid",
                    "plaid_account_id": aid + "_cash",
                })

        if not matched_any:
            return {"ok": False, "reason": "No linked accounts match _HOLDINGS_SUBTYPE_FILES",
                     "errors": errors or None}

        root = os.path.dirname(os.path.abspath(__file__))
        for csv_name, rows in by_bucket.items():
            path = os.path.join(root, csv_name)
            with open(path, "w") as f:
                f.write("ticker,shares,avg_cost\n")
                for r in sorted(rows, key=lambda r: r["ticker"]):
                    f.write(f"{r['ticker']},{r['shares']},{r['avg_cost']}\n")

        if cash_rows:
            existing = ac.load_accounts()
            merged = _merge(existing, cash_rows)
            ac.save_accounts(merged)

        # Rebuild portfolio.json/combined_holdings.csv from the updated CSVs,
        # same step scripts/import_holdings.py runs after any manual import.
        import import_holdings as imp
        import portfolio as pf
        combined = imp.recombine(root)
        pf.save_portfolio(combined)

        result = {"ok": True, "csvs_updated": list(by_bucket.keys()),
                   "positions_synced": sum(len(v) for v in by_bucket.values()),
                   "cash_rows_updated": len(cash_rows), "synced_at": today}
        if errors:
            result["partial_errors"] = errors
        return result
    except Exception as e:
        return {"ok": False, "reason": f"Plaid error: {type(e).__name__}: {e}"}
