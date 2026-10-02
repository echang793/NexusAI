#!/usr/bin/env python3
"""Load Webull account data (pulled through the Claude Webull connector) into
NexusAI's holdings files.

Webull has no Plaid support, so its accounts (taxable brokerage + Roth IRA)
are refreshed from a JSON payload that a Claude session builds from the
connector's get_account_list / get_account_balance / get_account_positions
calls. This script is the deterministic, tested half: validate, back up,
write.

Payload (JSON file):
    {"accounts": [
        {"account_class": "INDIVIDUAL_CASH" | "ROTH_IRA",
         "balance":   <get_account_balance result, verbatim>,
         "positions": <get_account_positions result, verbatim>}, ...]}

Safety: nothing is written unless BOTH an INDIVIDUAL_CASH and a ROTH_IRA
account are present and each account's position values add up to Webull's own
reported total market value (within 0.5%). Accounts holding nothing are
ignored (a stray empty account must never blank a CSV). The files about to be
overwritten are copied to backups/<timestamp>/ first (gitignored).

Usage:
    .venv/bin/python3 scripts/webull_import.py payload.json
Exit code 0 = imported, 1 = aborted (nothing written).
"""

import csv
import datetime
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import accounts as ac  # noqa: E402

# Webull account_class -> (holdings CSV, bucket name used by import_holdings)
ACCOUNT_FILES = {
    "INDIVIDUAL_CASH": ("brokerage_holdings.csv", "brokerage"),
    "ROTH_IRA": ("roth_ira_holdings.csv", "roth"),
}
# Webull drops the dash that Yahoo Finance (and so this app) uses.
SYMBOL_FIXES = {"BRKB": "BRK-B", "BRKA": "BRK-A", "BFB": "BF-B", "BFA": "BF-A"}
# Webull cash is tracked as this manual account in accounts.json.
CASH_ACCOUNT_NAME = "Webull Cash"
MAX_TOTAL_MISMATCH = 0.005  # position values vs Webull's reported total
MAX_POSITION_MISMATCH = 0.005  # quantity x last_price vs that position's market_value
KEEP_BACKUPS = 12


class ImportAbort(Exception):
    """Raised when the payload fails validation; nothing has been written."""


def _num(value, what):
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ImportAbort(f"{what}: {value!r} is not a number")


def _parse_positions(raw_positions, label):
    rows, value_sum = [], 0.0
    for p in raw_positions or []:
        symbol = str(p.get("symbol", "")).strip().upper()
        if not symbol:
            raise ImportAbort(f"{label}: position with no symbol")
        qty = _num(p.get("quantity"), f"{label} {symbol} quantity")
        cost = _num(p.get("cost_price"), f"{label} {symbol} cost_price")
        value = _num(p.get("market_value"), f"{label} {symbol} market_value")
        value_sum += value
        if qty <= 0 or cost < 0:
            raise ImportAbort(f"{label} {symbol}: quantity {qty} / cost {cost} is invalid")
        # Catch a single mistyped share count (the account total can still look
        # plausible): quantity x last_price must agree with the position's own value.
        if p.get("last_price") is not None and value > 0:
            implied = qty * _num(p.get("last_price"), f"{label} {symbol} last_price")
            if abs(implied - value) / value > MAX_POSITION_MISMATCH:
                raise ImportAbort(f"{label} {symbol}: quantity {qty} x price {p['last_price']} = "
                                  f"{implied:,.2f} but its market value is {value:,.2f}")
        rows.append((SYMBOL_FIXES.get(symbol, symbol), qty, cost))
    return rows, value_sum


def _read_old(path):
    if not os.path.exists(path):
        return {}
    with open(path, newline="") as f:
        return {r["ticker"]: float(r["shares"]) for r in csv.DictReader(f)}


def _diff(old, rows):
    new = {s: q for s, q, _ in rows}
    return {
        "added": sorted(set(new) - set(old)),
        "removed": sorted(set(old) - set(new)),
        "resized": sorted((t, old[t], new[t]) for t in new
                          if t in old and abs(new[t] - old[t]) > 1e-9),
    }


def _backup(root, paths):
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    dest = os.path.join(root, "backups", stamp)
    os.makedirs(dest, exist_ok=True)
    for p in paths:
        if os.path.exists(p):
            shutil.copy2(p, dest)
    keep = sorted(os.listdir(os.path.join(root, "backups")))
    for old in keep[:-KEEP_BACKUPS]:
        shutil.rmtree(os.path.join(root, "backups", old), ignore_errors=True)
    return dest


def import_webull(payload, root, accounts_path=None, portfolio_path=None):
    """Validate `payload`, then write the CSVs, Webull cash, combined file and
    portfolio.json. Returns a summary dict; raises ImportAbort (writing
    nothing) if validation fails."""
    # ---- validate everything first; nothing is written until this passes ----
    parsed = {}  # account_class -> (rows, cash)
    for acct in payload.get("accounts", []):
        cls = acct.get("account_class")
        if cls not in ACCOUNT_FILES:
            continue
        label = cls
        rows, value_sum = _parse_positions(acct.get("positions"), label)
        if not rows:
            continue  # empty account: never blank a CSV because of it
        reported = _num((acct.get("balance") or {}).get("total_market_value"),
                        f"{label} total_market_value")
        if reported <= 0 or abs(value_sum - reported) / reported > MAX_TOTAL_MISMATCH:
            raise ImportAbort(
                f"{label}: positions add up to {value_sum:,.2f} but Webull reports "
                f"{reported:,.2f} — refusing to write a partial/garbled pull")
        cash = (acct.get("balance") or {}).get("total_cash_balance")
        parsed[cls] = (rows, None if cash is None else _num(cash, f"{label} cash"))
    missing = sorted(set(ACCOUNT_FILES) - set(parsed))
    if missing:
        raise ImportAbort(f"payload has no positions for {missing}; refusing a half update")

    # ---- back up, then write ----
    accounts_path = accounts_path or ac.ACCOUNTS_FILE
    if portfolio_path is None:
        import config
        portfolio_path = config.PORTFOLIO_FILE
    csv_paths = [os.path.join(root, ACCOUNT_FILES[c][0]) for c in ACCOUNT_FILES]
    backup_dir = _backup(root, csv_paths + [os.path.join(root, "combined_holdings.csv"),
                                            accounts_path, portfolio_path])

    changes, counts = {}, {}
    for cls, (rows, _cash) in parsed.items():
        fname, bucket = ACCOUNT_FILES[cls]
        path = os.path.join(root, fname)
        changes[bucket] = _diff(_read_old(path), rows)
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["ticker", "shares", "avg_cost"])
            for symbol, qty, cost in sorted(rows):
                w.writerow([symbol, qty, cost])
        counts[bucket] = len(rows)

    cash = parsed["INDIVIDUAL_CASH"][1]
    if cash is not None:
        accts = ac.load_accounts(accounts_path)
        for a in accts:
            if a["name"] == CASH_ACCOUNT_NAME:
                a["balance"] = cash
                a["updated"] = datetime.date.today().isoformat()
        ac.save_accounts(accts, accounts_path)

    import import_holdings
    import portfolio as pf
    combined = import_holdings.recombine(root)
    pf.save_portfolio(combined, portfolio_path)
    return {"ok": True, "positions": counts, "changes": changes,
            "webull_cash": cash, "backup": backup_dir}


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 1
    with open(argv[1]) as f:
        payload = json.load(f)
    try:
        result = import_webull(payload, ROOT)
    except ImportAbort as e:
        print(f"ABORTED, nothing written: {e}")
        return 1
    print(f"Imported Webull: {result['positions']} positions; Webull cash {result['webull_cash']}")
    for bucket, ch in result["changes"].items():
        print(f"  {bucket}: added {ch['added']} removed {ch['removed']} resized {len(ch['resized'])}")
    print(f"  backup: {result['backup']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
