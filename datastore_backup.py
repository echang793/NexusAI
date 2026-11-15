"""Nightly rotating copy of the app's data files into backups/daily/<date>/.

The data (balances, history, transactions) can't be rebuilt from the public
repo, and a bad write or a disk problem would lose months of history. Each
copy is size-checked against its source; the folder is owner-only. `.env`
(Plaid keys) is deliberately NOT copied — secrets belong in one place.

This is a local safety net, not an off-machine backup: Time Machine or a
copy to another disk is still advisable for the disk-failure case.
"""

import datetime
import os
import shutil

DATA_FILES = [
    "accounts.json", "profile.json", "portfolio.json", "combined_holdings.csv",
    "brokerage_holdings.csv", "roth_ira_holdings.csv", "hsa_holdings.csv",
    "nw_history.json", "daily_history.json", "transactions.json",
    "investment_flows.json", "category_rules.json",
]
KEEP_DAYS = 30


class BackupError(Exception):
    """A copied file did not match its source."""


def backup_daily(root: str, today: datetime.date, keep: int = KEEP_DAYS) -> dict:
    base = os.path.join(root, "backups", "daily")
    day = os.path.join(base, today.isoformat())
    os.makedirs(day, mode=0o700, exist_ok=True)
    os.chmod(day, 0o700)
    os.chmod(base, 0o700)
    copied = []
    for name in DATA_FILES:
        src = os.path.join(root, name)
        if not os.path.exists(src):
            continue
        dst = os.path.join(day, name)
        shutil.copy2(src, dst)
        os.chmod(dst, 0o600)
        if os.path.getsize(src) != os.path.getsize(dst):
            raise BackupError(f"{name}: backup is {os.path.getsize(dst)} bytes, source is {os.path.getsize(src)}")
        copied.append(name)
    for old in sorted(os.listdir(base))[:-keep]:
        shutil.rmtree(os.path.join(base, old), ignore_errors=True)
    return {"dir": day, "copied": copied}
