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

import attribution  # noqa: E402

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


SCORECARD_EDGE_PTS = 5.0     # BUY hit-rate must beat the baseline by this many points
SCORECARD_MIN_CALLS = 30


def _why_it_moved(days, prev, cur):
    """Attribute the change between the two snapshots using the daily records."""
    if not days:
        return {"available": False}
    start = (prev.get("recordedAt") or prev["date"])
    end = cur.get("recordedAt") or cur["date"]
    r = attribution.attribute_range(days, start, end)
    if r is None:
        return {"available": False, "first_day": min(days)}
    d0 = days[r["start"]]
    start_value = sum(h["q"] * h["p"] for h in d0.get("holdings", {}).values())
    by_ticker = {}
    for m in r["movers"]:
        by_ticker[m["ticker"]] = by_ticker.get(m["ticker"], 0.0) + m["market"]
    movers = [m for m in sorted(by_ticker.items(), key=lambda kv: -abs(kv[1]))[:3] if abs(m[1]) >= 1]
    asked = datetime.date.fromisoformat(start)
    got = datetime.date.fromisoformat(r["start"])
    return {"available": True, "r": r, "start_value": start_value, "movers": movers,
            "partial": (got - asked).days > 3, "asked_start": start}


def build_report(snapshots, accounts, files, today, days=None, scorecard=None, problems=None):
    """snapshots: nw_history list (any order); accounts: accounts.json rows;
    files: {label: date the file was last written}; days: daily_history days
    (for 'why it moved' and the portfolio check); scorecard: parsed
    reports/scorecard.json; problems: health.evaluate() output."""
    snaps = sorted(snapshots, key=lambda s: s["date"])
    rep = {"today": today, "empty": not snaps}
    if not snaps:
        return rep
    cur = snaps[-1]
    prev = snaps[-2] if len(snaps) > 1 else None
    rep.update(cur=cur, prev=prev, first=snaps[0] if len(snaps) > 2 else None)
    rep["why"] = _why_it_moved(days, prev, cur) if prev else None
    rep["analytics"] = None
    if days:
        latest = max(days)
        rep["analytics"] = days[latest].get("analytics")
    rep["scorecard"] = scorecard
    rep["problems"] = problems or []

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
    rep["holdings_refreshed"] = min(files.values()) if files else None
    return rep


def _fmt_day(iso):
    return datetime.date.fromisoformat(iso).strftime("%b %-d")


def _render_why(why):
    if not why.get("available"):
        first = why.get("first_day")
        tail = f" Daily records began {_fmt_day(first)}." if first else ""
        return ["WHY IT MOVED",
                "  Not available yet — daily tracking just started, so there isn't a full "
                "month of records to split into market vs new money." + tail]
    r = why["r"]
    head = f"WHY IT MOVED  ({_fmt_day(r['start'])} - {_fmt_day(r['end'])})"
    L = [head]
    if why["partial"]:
        L.append(f"  Covers only {_fmt_day(r['start'])} onward: daily records start there, "
                 f"after last month's reading.")
    pct_note = ""
    if why["start_value"] > 0:
        pct_note = f" ({r['market'] / why['start_value'] * 100:+.1f}% on your investments)"
    L.append(f"  Market moves: {money(r['market'], True)}{pct_note}")
    L.append(f"  New shares bought: {money(r['contributions'], True)}")
    L.append(f"  Other accounts: {money(r['other'], True)}  (cash, checking, 401k balance changes)")
    big = sorted(r["other_by_account"].items(), key=lambda kv: -abs(kv[1]))[:3]
    for name, d in big:
        L.append(f"    {name}: {money(d, True)}")
    if why["movers"]:
        L.append("  Biggest market movers: " +
                 ", ".join(f"{t} {money(v, True)}" for t, v in why["movers"]))
    L.append(f"  Total tracked: {money(r['total'], True)}")
    return L


def _render_portfolio(a):
    L = ["PORTFOLIO CHECK"]
    if a.get("top") is not None and a.get("top5Pct") is not None:
        eff = f"; it behaves like about {a['effectiveN']} equal-sized positions" if a.get("effectiveN") else ""
        L.append(f"  Your top 5 holdings are {a['top5Pct']:.1f}% of your investments{eff}.")
    if a.get("topStocks"):
        L.append(f"  Individual stocks are {a.get('stocksPct', 0):.1f}% of your investments; the biggest are "
                 + ", ".join(f"{t['ticker']} {t['pct']:.1f}%" for t in a["topStocks"]) + ".")
    if a.get("singleNameFlags"):
        L.append("  Single stocks above 10%: " +
                 ", ".join(f"{f['ticker']} {f['pct']:.1f}%" for f in a["singleNameFlags"]) + ".")
    if a.get("multiAccount"):
        n = len(a["multiAccount"])
        L.append(f"  {n} holdings appear in more than one account (e.g. the same names in both "
                 f"Brokerage and Roth), so account-level views overstate how many separate bets you have.")
    if a.get("allocation"):
        L.append("  Mix: " + ", ".join(f"{k} {v:.1f}%" for k, v in a["allocation"].items()) + ".")
    risk = a.get("risk") or {}
    if risk.get("sharpe") is not None:
        bench = f" vs {risk['benchmarkSharpe']} for SPY" if risk.get("benchmarkSharpe") is not None else ""
        dd = f"; worst drop {abs(risk['maxDrawdown']):.1f}%" if risk.get("maxDrawdown") is not None else ""
        L.append(f"  Risk over the past year: Sharpe {risk['sharpe']}{bench}{dd}.")
    loc = a.get("location") or []
    for x in loc[:3]:
        yld = f"{x['yieldPct']:.1f}% yield; " if x.get("yieldPct") else ""
        L.append(f"  Tax placement to consider: {x['ticker']} in {x['account']} ({yld}{x['why']}).")
    if len(loc) > 3:
        L.append(f"  (+{len(loc) - 3} more like this.)")
    return L


def _render_scorecard(sc):
    horizons = sc.get("horizons") or []
    if not horizons:
        return []
    h = str(max(horizons))
    summ = sc.get("summary", {})
    buy, base = summ.get("BUY", {}).get(h), summ.get("ALL", {}).get(h)
    if not buy or not base or buy.get("hitRate") is None or base.get("hitRate") is None:
        return []
    asof = f", as of {sc['generated']:%b %-d}" if sc.get("generated") else ""
    L = [f"SIGNAL SCORECARD  (the app's BUY/SELL rules replayed on {len(sc.get('tickers', []))} of your "
         f"tickers, ~{int(h) // 21}-month look-ahead{asof})"]
    if buy["n"] < SCORECARD_MIN_CALLS:
        L.append(f"  Too few BUY calls ({buy['n']}) to judge.")
        return L
    gap = buy["hitRate"] - base["hitRate"]
    if gap >= SCORECARD_EDGE_PTS:
        verdict = f"an edge of {gap:+.1f} points"
    else:
        verdict = "no clear edge — treat BUY/SELL labels as a prompt to look, not a prediction"
    L.append(f"  BUY calls beat SPY {buy['hitRate']:.1f}% of the time vs {base['hitRate']:.1f}% for any "
             f"random day: {verdict}.")
    return L


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

    # Why it moved
    why = rep.get("why")
    if why is not None:
        L.extend(_render_why(why))
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
        if coast.get("oddsPct") is not None:
            last = f" (last month {pc['oddsPct']:.1f}%)" if pc and pc.get("oddsPct") is not None else ""
            L.append(f"  Odds of reaching {money(coast['fireNumber'])} by retirement with no more "
                     f"contributions: {coast['oddsPct']:.1f}%{last}.")
            L.append(f"  Typical outcome {money(coast['p50'])}; unlucky {money(coast['p10'])}; "
                     f"lucky {money(coast['p90'])} (random yearly returns, not a promise).")
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

    # Portfolio check
    if rep.get("analytics"):
        L.extend(_render_portfolio(rep["analytics"]))
        L.append("")

    # Signal scorecard
    if rep.get("scorecard"):
        L.extend(_render_scorecard(rep["scorecard"]))
        L.append("")

    # Freshness
    L.append("HEADS UP")
    if rep.get("holdings_refreshed"):
        L.append(f"  Webull holdings last refreshed: {rep['holdings_refreshed']:%b %-d}.")
    items = list(rep["warnings"]) + [p["message"] for p in rep.get("problems", [])]
    if items:
        for w in items:
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


def _load_scorecard(root):
    """reports/scorecard.json (written by scripts/scorecard_run.py), stamped with
    its file date so an old scorecard is never presented as current."""
    import json
    path = os.path.join(root, "reports", "scorecard.json")
    try:
        with open(path) as f:
            sc = json.load(f)
        sc["generated"] = datetime.date.fromtimestamp(os.path.getmtime(path))
        return sc
    except Exception:
        return None


def main():
    import accounts as ac
    import daily_history
    import health
    import nw_snapshots
    today = datetime.date.today()
    accts = ac.load_accounts()
    problems = health.evaluate(health.read(os.path.join(ROOT, "health.json")), accts,
                               datetime.datetime.now())
    rep = build_report(nw_snapshots.load_history(), accts, _file_dates(ROOT), today,
                       days=daily_history.load_days(), scorecard=_load_scorecard(ROOT),
                       problems=problems)
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
