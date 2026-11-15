"""Investment performance: time-weighted return from daily_history records.

Covers ticker-backed holdings only (Webull brokerage + Roth, Fidelity HSA
funds). Lump-sum balances (the 401(k)) can't be split into growth vs
contributions from a single number, so they're excluded rather than guessed.

Each day-to-day step is `market gain / value at the start of the step`, where
market gain is attribution.attribute()'s market component: shares bought or
sold are valued at the new price and never count as gains. Steps chain
multiplicatively, so a $10,000 deposit between two days leaves the return
unchanged. Days flagged incomplete (an unpriced ticker) are skipped.

Annualized return is reported only for windows of a year or more.
"""

import datetime
import math

from attribution import attribute


def _finite(x):
    return isinstance(x, (int, float)) and math.isfinite(x)


def _only(day: dict, account: str | None) -> dict:
    if account is None:
        return day
    prefix = f"{account}|"
    return {"holdings": {k: v for k, v in day.get("holdings", {}).items() if k.startswith(prefix)},
            "accounts": {}}


def _base(day: dict) -> float:
    return sum(h["q"] * h["p"] for h in day.get("holdings", {}).values()
               if _finite(h.get("q")) and _finite(h.get("p")))


def _usable(days: dict, start: str, end: str) -> list[str]:
    return sorted(d for d, v in days.items() if start <= d <= end and v.get("complete"))


def twr(days: dict, start: str, end: str, account: str | None = None) -> dict | None:
    dates = _usable(days, start, end)
    growth, gain, first_used, last_used = 1.0, 0.0, None, None
    for d0, d1 in zip(dates, dates[1:]):
        prev, cur = _only(days[d0], account), _only(days[d1], account)
        base = _base(prev)
        if base <= 0:
            continue
        m = attribute(prev, cur)["market"]
        if not _finite(m):
            continue
        growth *= 1.0 + m / base
        gain += m
        first_used = first_used or d0
        last_used = d1
    if first_used is None:
        return None
    span = (datetime.date.fromisoformat(last_used) - datetime.date.fromisoformat(first_used)).days
    ret = growth - 1.0
    annualized = None
    if span >= 365 and growth > 0:
        annualized = round((growth ** (365.0 / span) - 1.0) * 100, 2)
    return {"returnPct": round(ret * 100, 2), "marketGain": round(gain, 2), "from": first_used,
            "to": last_used, "days": span, "annualizedPct": annualized}


def per_account(days: dict, start: str, end: str) -> dict:
    names = set()
    for d in _usable(days, start, end):
        for key in days[d].get("holdings", {}):
            names.add(key.partition("|")[0])
    out = {}
    for name in sorted(names):
        r = twr(days, start, end, account=name)
        if r:
            out[name] = r
    return out


def vs_benchmark(days: dict, start: str, end: str) -> dict:
    """Portfolio TWR vs SPY over the same dates. Only days that carry a SPY
    price count, so the window may begin later than `start`."""
    with_spy = [d for d in _usable(days, start, end) if _finite(days[d].get("spy")) and days[d]["spy"] > 0]
    if len(with_spy) < 2:
        r = twr(days, start, end)
        return {"covered": False, "portfolioPct": r["returnPct"] if r else None, "spyPct": None,
                "excessPct": None, "from": None, "to": None}
    first, last = with_spy[0], with_spy[-1]
    r = twr(days, first, last)
    spy = (days[last]["spy"] / days[first]["spy"] - 1.0) * 100.0
    if not r:
        return {"covered": False, "portfolioPct": None, "spyPct": round(spy, 2),
                "excessPct": None, "from": first, "to": last}
    return {"covered": True, "portfolioPct": r["returnPct"], "spyPct": round(spy, 2),
            "excessPct": round(r["returnPct"] - spy, 2), "from": first, "to": last}
