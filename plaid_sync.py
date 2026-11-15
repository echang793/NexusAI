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


_LIABILITY_TYPES = {"Credit Card", "Mortgage", "Auto Loan", "Student Loan", "Other Liability"}


def _balance_amount(bal: dict, ui_type: str) -> float:
    """The balance to record. `current` is the amount held (assets) or OWED
    (credit/loans); `available` is spendable cash for a bank account and the
    UNUSED CREDIT for a card. `current or available` used to turn a $0.00 card
    into a ~$20,000 phantom debt, so: current whenever Plaid sent one (zero
    included); available only for non-liability accounts with no current; a
    liability never falls back and never goes negative (an overpaid card is a
    credit in your favour, not a debt)."""
    current = bal.get("current")
    if ui_type in _LIABILITY_TYPES:
        return max(0.0, float(current)) if current is not None else 0.0
    if current is not None:
        return abs(float(current))
    return abs(float(bal.get("available") or 0))


def _distinct_names(rows: list, masks: list) -> None:
    """Several cards can all be called "CREDIT CARD"; name collisions would make
    them overwrite each other wherever balances are keyed by name. Duplicates get
    their last four digits (or a position if Plaid sent none) appended."""
    counts: dict = {}
    for r in rows:
        counts[r["name"]] = counts.get(r["name"], 0) + 1
    for i, (r, mask) in enumerate(zip(rows, masks)):
        if counts[r["name"]] > 1:
            r["name"] = f"{r['name']} ••{mask}" if mask else f"{r['name']} #{i + 1}"


def _fetch_one(client, access_token: str, today: str) -> list:
    from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest
    resp = client.accounts_balance_get(AccountsBalanceGetRequest(access_token=access_token))
    rows, masks = [], []
    for a in resp["accounts"]:
        if str(a.get("subtype", "")).lower() in _SKIP_SUBTYPES:
            continue
        ui_type = _map_type(str(a.get("subtype")), str(a.get("type")))
        rows.append({
            "name": a.get("name") or a.get("official_name") or "Account",
            "type": ui_type,
            "balance": _balance_amount(a["balances"], ui_type),
            "notes": "Synced via Plaid",
            "updated": today,
            "source": "plaid",
            "plaid_account_id": a.get("account_id"),
        })
        masks.append(a.get("mask"))
    _distinct_names(rows, masks)
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


# Plaid errors meaning "this Item has no transactions product / consent (yet)".
# Expected for Items linked with only `investments`, so they are skipped, not failures.
_TX_SKIP_CODES = ("ADDITIONAL_CONSENT_REQUIRED", "INVALID_PRODUCT", "PRODUCTS_NOT_SUPPORTED",
                  "PRODUCT_NOT_READY")


def _make_client():
    from plaid.api import plaid_api
    from plaid import Configuration, ApiClient
    hosts = {
        "sandbox": "https://sandbox.plaid.com",
        "development": "https://development.plaid.com",
        "production": "https://production.plaid.com",
    }
    cfg = Configuration(host=hosts.get(PLAID_ENV, hosts["production"]),
                        api_key={"clientId": PLAID_CLIENT_ID, "secret": PLAID_SECRET})
    return plaid_api.PlaidApi(ApiClient(cfg))


def _error_code(e: Exception) -> str:
    """Plaid error_code if the exception carries one, else the exception type.
    Deliberately drops the rest of the message (request bodies/headers)."""
    import re
    m = re.search(r'"?error_code"?\s*[:=]\s*"?([A-Z_]{4,})', str(e))
    return m.group(1) if m else type(e).__name__


def pull_transactions() -> dict:
    """Incrementally sync transactions for every linked Item into transactions.json.

    Items without transactions consent are skipped (listed under `skipped`).
    A real error on one Item (login required, malformed data) is reported under
    `errors` and makes ok False, but the other Items still sync. Nothing is
    stored for a failing Item and its cursor does not advance, so the next run
    simply retries. Returns {"ok", "items_synced", "added", "skipped", "errors"}.
    """
    import transactions as tx
    if not HAS_PLAID:
        return {"ok": False, "reason": "Plaid not configured"}
    try:
        from plaid.model.transactions_sync_request import TransactionsSyncRequest
        client = _make_client()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"Plaid unavailable: {_error_code(e)}"}

    synced = added_total = 0
    skipped, errors = [], []
    for token in PLAID_ACCESS_TOKENS:
        key = tx.item_key(token)

        def sync(cursor, token=token):
            kwargs = {"access_token": token, "count": 500}
            if cursor:
                kwargs["cursor"] = cursor
            return tx.to_plain(client.transactions_sync(TransactionsSyncRequest(**kwargs)))

        try:
            added, modified, removed, cursor = tx.fetch_all(sync, tx.get_cursor(key))
            tx.apply_sync(key, added, modified, removed, cursor)
            synced += 1
            added_total += len(added)
        except tx.NotReady:
            skipped.append(f"item {key}: not ready yet (Plaid is still preparing history)")
        except tx.TransactionsError as e:
            errors.append(f"item {key}: {e}")
        except Exception as e:  # noqa: BLE001
            code = _error_code(e)
            if code in _TX_SKIP_CODES:
                skipped.append(f"item {key}: {code}")
            else:
                errors.append(f"item {key}: {code}")
    result = {"ok": not errors, "items_synced": synced, "added": added_total,
              "skipped": skipped, "errors": errors}
    if errors:
        result["reason"] = f"{len(errors)} item(s) failed: " + "; ".join(errors)
    return result


_LINKABLE_PRODUCTS = {"transactions", "investments", "liabilities"}


def link_request_kwargs(update_index: int | None = None, products=("investments",),
                        tokens: list | None = None) -> dict:
    """Arguments for Plaid's link_token_create, as plain strings (scripts/plaid_link.py
    wraps them in Plaid's model classes). New link: `products`. Update mode
    (update_index given): reopen an EXISTING Item so the user can grant extra
    consent, e.g. `transactions` on an Item first linked for investments only;
    the access token does not change."""
    products = list(products or [])
    if not products or any(p not in _LINKABLE_PRODUCTS for p in products):
        raise ValueError(f"products must be a non-empty subset of {sorted(_LINKABLE_PRODUCTS)}")
    if update_index is None:
        return {"products": products}
    tokens = tokens or []
    if not 0 <= update_index < len(tokens):
        raise ValueError(f"no linked Item at index {update_index} ({len(tokens)} configured)")
    return {"access_token": tokens[update_index], "additional_consented_products": products}


def pull_investment_activity() -> dict:
    """Rebuild investment_flows.json (contributions / dividends / withdrawals per
    401k / HSA / IRA) from Plaid investment transactions, last 24 months.

    Rebuilt from scratch each time, so it is only written when every
    investment-capable Item succeeded: a half-failed pull must not replace a
    complete picture. Items without the investments product are skipped."""
    import investment_flows as fl
    import transactions as tx
    if not HAS_PLAID:
        return {"ok": False, "reason": "Plaid not configured"}
    try:
        from plaid.model.accounts_get_request import AccountsGetRequest
        from plaid.model.investments_transactions_get_request import InvestmentsTransactionsGetRequest
        from plaid.model.investments_transactions_get_request_options import \
            InvestmentsTransactionsGetRequestOptions
        client = _make_client()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"Plaid unavailable: {_error_code(e)}"}

    end = datetime.date.today()
    start = end - datetime.timedelta(days=730)
    all_txs: list = []
    subtypes: dict = {}
    synced = 0
    skipped, errors = [], []
    for token in PLAID_ACCESS_TOKENS:
        key = tx.item_key(token)
        try:
            accts = client.accounts_get(AccountsGetRequest(access_token=token))["accounts"]
            subtypes.update({a["account_id"]: str(a.get("subtype") or "") for a in accts})

            def page(offset, token=token):
                resp = client.investments_transactions_get(InvestmentsTransactionsGetRequest(
                    access_token=token, start_date=start, end_date=end,
                    options=InvestmentsTransactionsGetRequestOptions(count=500, offset=offset)))
                return (tx.to_plain(resp["investment_transactions"]),
                        int(resp["total_investment_transactions"]))

            all_txs.extend(fl.fetch_all_pages(page))
            synced += 1
        except fl.FlowsError as e:
            errors.append(f"item {key}: {e}")
        except Exception as e:  # noqa: BLE001
            code = _error_code(e)
            if code in _TX_SKIP_CODES:
                skipped.append(f"item {key}: {code}")
            else:
                errors.append(f"item {key}: {code}")

    result = {"ok": not errors, "items_synced": synced, "skipped": skipped, "errors": errors,
              "transactions": len(all_txs)}
    if errors:
        result["reason"] = f"{len(errors)} item(s) failed: " + "; ".join(errors)
        return result
    if synced:
        try:
            flows = fl.aggregate(all_txs, subtypes)
        except fl.FlowsError as e:
            return {**result, "ok": False, "reason": str(e), "errors": [str(e)]}
        flows["synced_at"] = end.isoformat()
        fl.save(flows)
    return result
