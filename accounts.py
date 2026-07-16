"""Other money accounts (HYSA, HSA, cash, debt, etc.) for net-worth tracking."""

import json
import os


ACCOUNTS_FILE = os.getenv("ACCOUNTS_FILE", "accounts.json")

COLUMNS = ["name", "type", "balance", "notes", "updated"]

ASSET_TYPES = [
    "Cash",
    "Checking",
    "Savings",
    "HYSA",
    "HSA",
    "FSA",
    "CD",
    "Money Market",
    "401k Cash",
    "IRA Cash",
    "Crypto",
    "Real Estate",
    "Vehicle",
    "Other Asset",
]

LIABILITY_TYPES = [
    "Credit Card",
    "Student Loan",
    "Mortgage",
    "Auto Loan",
    "Personal Loan",
    "Other Liability",
]

ALL_TYPES = ASSET_TYPES + LIABILITY_TYPES


def is_liability(account_type):
    return account_type in LIABILITY_TYPES


def load_accounts(path=None):
    """Load accounts from JSON. Returns list of dicts."""
    path = path or ACCOUNTS_FILE
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except Exception:
        return []
    rows = data.get("accounts", data) if isinstance(data, dict) else data
    return _coerce(rows)


def save_accounts(accounts, path=None):
    path = path or ACCOUNTS_FILE
    clean = _coerce(accounts)
    with open(path, "w") as f:
        json.dump({"accounts": clean}, f, indent=2)
    return clean


def _coerce(rows):
    out = []
    for r in rows or []:
        name = str(r.get("name", "") or "").strip()
        atype = str(r.get("type", "") or "").strip()
        if atype not in ALL_TYPES:
            # best-effort title-case match
            match = next((t for t in ALL_TYPES if t.lower() == atype.lower()), None)
            atype = match or "Other Asset"
        try:
            raw_bal = r.get("balance", 0)
            balance = float(raw_bal) if raw_bal not in (None, "") else 0.0
            if balance != balance:  # NaN
                continue
        except (TypeError, ValueError):
            continue
        if not name and balance == 0:
            continue
        notes = str(r.get("notes", "") or "").strip()
        updated = str(r.get("updated", "") or "").strip()
        if not updated:
            import datetime
            updated = datetime.date.today().isoformat()
        out.append({
            "name": name or atype,
            "type": atype,
            "balance": balance,
            "notes": notes,
            "updated": updated,
        })
    return out


def summarize(accounts):
    """Return totals broken out by asset vs liability + by-type breakdown."""
    accounts = _coerce(accounts)
    total_assets = 0.0
    total_liabilities = 0.0
    by_type = {}
    for a in accounts:
        bal = a["balance"]
        by_type.setdefault(a["type"], 0.0)
        by_type[a["type"]] += bal
        if is_liability(a["type"]):
            total_liabilities += abs(bal)
        else:
            total_assets += bal
    return {
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "net": total_assets - total_liabilities,
        "by_type": by_type,
        "accounts": accounts,
    }


def net_worth(portfolio_value, accounts_summary):
    """Combine brokerage value + other accounts into net worth breakdown."""
    pv = float(portfolio_value or 0)
    assets = pv + accounts_summary["total_assets"]
    liabilities = accounts_summary["total_liabilities"]
    return {
        "investments": pv,
        "other_assets": accounts_summary["total_assets"],
        "total_assets": assets,
        "total_liabilities": liabilities,
        "net_worth": assets - liabilities,
    }
