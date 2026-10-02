#!/usr/bin/env python3
"""Month-over-month net worth report, as plain text (it gets emailed).

Built ONLY from stored files — the monthly snapshots in nw_history.json,
accounts.json freshness dates, and holdings-file ages. It never recomputes net
worth or fetches prices (a fresh process has an empty price cache and would
silently value everything at cost basis).

Compares the latest snapshot to the previous month's, leads with CoastFIRE
progress (the reason this is tracked), and ends with data-freshness warnings:
a stale manual account or a failing Plaid sync is the main way this report
could quietly mislead.

Usage:
    .venv/bin/python3 scripts/monthly_report.py      # prints; also writes reports/YYYY-MM.txt
"""

import datetime
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

STALE_MANUAL_DAYS = 35   # manual accounts are refreshed monthly
STALE_PLAID_DAYS = 3     # Plaid syncs daily; older means the sync is failing
STALE_FILE_DAYS = 35


def money(n, signed=False):
    n = round(n)
    if signed:
        return f"{'+' if n >= 0 else '-'}${abs(n):,}"
    return f"{'-' if n < 0 else ''}${abs(n):,}"


def pct(new, old, signed=True):
    if not old:
        return "n/a"
    p = (new / old - 1) * 100
    return f"{p:+.1f}%" if signed else f"{p:.1f}%"


def month_name(snapshot, with_year=False):
    d = datetime.date.fromisoformat(snapshot["date"])
    return d.strftime("%B %Y" if with_year else "%B")


def _age_days(updated, today):
    try:
        return (today - datetime.date.fromisoformat(updated)).days
    except (TypeError, ValueError):
        return None


def build_report(snapshots, accounts, files, today):
    """snapshots: nw_history list (any order); accounts: accounts.json rows;
    files: {label: date the file was last written}."""
    snaps = sorted(snapshots, key=lambda s: s["date"])
    rep = {"today": today, "empty": not snaps}
    if not snaps:
        return rep
    cur = snaps[-1]
    prev = snaps[-2] if len(snaps) > 1 else None
    rep.update(cur=cur, prev=prev, first=snaps[0] if len(snaps) > 2 else None)

    # Per-account movement (only when both months stored a breakdown).
    ca = (cur.get("details") or {}).get("accounts")
    pa = (prev.get("details") or {}).get("accounts") if prev else None
    rep["account_changes"] = None
    if ca and pa:
        rows = []
        for name in set(ca) | set(pa):
            new, old = ca.get(name, 0), pa.get(name, 0)
            rows.append({"name": name, "new": new, "old": old, "delta": new - old,
                         "is_new": name not in pa, "gone": name not in ca})
        rep["account_changes"] = sorted(rows, key=lambda r: -abs(r["delta"]))

    # Freshness warnings.
    warnings = []
    for a in accounts:
        age = _age_days(a.get("updated"), today)
        if age is None:
            continue
        if a.get("source") == "plaid":
            if age > STALE_PLAID_DAYS:
                warnings.append(f"{a['name']} was last synced {age} days ago — the Plaid sync "
                                f"may be failing (it should update daily).")
        elif age > STALE_MANUAL_DAYS:
            warnings.append(f"{a['name']} was last updated {age} days ago (it's entered "
                            f"manually) — update it in the Webull app and tell Claude.")
    for label, written in files.items():
        age = (today - written).days
        if age > STALE_FILE_DAYS:
            warnings.append(f"{label} last updated {age} days ago — this month's figures "
                            f"use old share counts.")
    rep["warnings"] = warnings
    return rep


def render_text(rep):
    if rep["empty"]:
        return "NexusAI monthly report\n\nNo net worth history recorded yet."
    cur, prev = rep["cur"], rep["prev"]
    L = []
    L.append(f"NexusAI monthly report — {month_name(cur, True)}")
    recorded = cur.get("recordedAt")
    if recorded:
        L.append(f"(snapshot taken {datetime.date.fromisoformat(recorded).strftime('%b %-d')})")
    L.append("")

    # Headline
    L.append(f"NET WORTH: {money(cur['value'])}")
    if prev:
        d = cur["value"] - prev["value"]
        L.append(f"  {money(d, True)} ({pct(cur['value'], prev['value'])}) vs {month_name(prev)} "
                 f"({money(prev['value'])})")
        L.append(f"  Investments (brokerage, Roth, HSA funds): {money(cur['investments'])} "
                 f"({money(cur['investments'] - prev['investments'], True)})")
        L.append(f"  Everything else (401k, cash, checking, other): {money(cur['otherAssets'])} "
                 f"({money(cur['otherAssets'] - prev['otherAssets'], True)})")
    else:
        L.append("  This is the first month on record, so there's nothing to compare to yet.")
    if rep.get("first"):
        f = rep["first"]
        L.append(f"  Since {month_name(f, True)}: {money(f['value'])} -> {money(cur['value'])} "
                 f"({money(cur['value'] - f['value'], True)}, {pct(cur['value'], f['value'])})")
    L.append("")

    # CoastFIRE
    coast = (cur.get("details") or {}).get("coast")
    L.append("COASTFIRE PROGRESS")
    if coast:
        gap = coast["needed"] - coast["invested"]
        L.append(f"  Invested {money(coast['invested'])} vs the {money(coast['needed'])} you need "
                 f"today to coast to {money(coast['fireNumber'])} — {coast['pctOfCoast']:.1f}% of the way.")
        if gap > 0:
            L.append(f"  {money(gap)} to go.")
        else:
            L.append(f"  You are {money(-gap)} ahead of the coast number.")
        pc = ((prev or {}).get("details") or {}).get("coast")
        if pc:
            L.append(f"  Last month: {pc['pctOfCoast']:.1f}% ({money(pc['invested'])} invested).")
        L.append("  Note: the coast number rises each year as retirement gets closer; a steady "
                 "percentage means your balance is growing at your assumed return.")
    else:
        L.append("  Not recorded for this month.")
    L.append("")

    # Per-account
    ch = rep.get("account_changes")
    L.append("BY ACCOUNT")
    if ch:
        for r in ch:
            tag = "  (new account)" if r["is_new"] else "  (no longer tracked)" if r["gone"] else ""
            L.append(f"  {r['name']}: {money(r['new'])} ({money(r['delta'], True)}){tag}")
    else:
        L.append("  A per-account comparison needs two months of detail; it starts next month.")
    L.append("")

    # Freshness
    L.append("HEADS UP")
    if rep["warnings"]:
        for w in rep["warnings"]:
            L.append(f"  - {w}")
    else:
        L.append("  All data is fresh.")
    return "\n".join(L)


def _file_dates(root):
    out = {}
    for label, name in (("Webull taxable holdings", "brokerage_holdings.csv"),
                        ("Webull Roth holdings", "roth_ira_holdings.csv")):
        p = os.path.join(root, name)
        if os.path.exists(p):
            out[label] = datetime.date.fromtimestamp(os.path.getmtime(p))
    return out


def main():
    import accounts as ac
    import nw_snapshots
    today = datetime.date.today()
    rep = build_report(nw_snapshots.load_history(), ac.load_accounts(), _file_dates(ROOT), today)
    body = render_text(rep)
    out_dir = os.path.join(ROOT, "reports")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{today:%Y-%m}.txt")
    with open(path, "w") as f:
        f.write(body + "\n")
    print(body)
    print(f"\n[saved to {path}]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
