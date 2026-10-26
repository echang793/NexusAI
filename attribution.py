"""Explain a change in net worth: market vs new shares vs everything else.

Works on the daily records from daily_history.py. For each holding, with q =
quantity and p = price on the earlier (0) and later (1) day:

    q1*p1 - q0*p0  =  q0*(p1 - p0)   +   (q1 - q0)*p1
                      \\_ market _/       \\_ contribution _/

The identity is exact, so the pieces always add up to the real change.
Non-ticker accounts (cash, checking, Plaid balances) go in `other`: that's
money moving in/out (pay, rent, transfers) plus any growth the connected
account reports as a single number — a 401(k) on a lump balance can't be
split further.
"""


def _val(h):
    return h["q"] * h["p"]


def attribute(prev: dict, cur: dict) -> dict:
    ph, ch = prev.get("holdings", {}), cur.get("holdings", {})
    market = contributions = 0.0
    movers = []
    for key in set(ph) | set(ch):
        a, b = ph.get(key), ch.get(key)
        acct, _, ticker = key.partition("|")
        if a and b:
            m = a["q"] * (b["p"] - a["p"])
            c = (b["q"] - a["q"]) * b["p"]
        elif b:                      # newly held: all of it is new money
            m, c = 0.0, _val(b)
        else:                        # no longer held
            m, c = 0.0, -_val(a)
        market += m
        contributions += c
        if m:
            movers.append({"ticker": ticker, "account": acct, "market": m})
    movers.sort(key=lambda r: -abs(r["market"]))

    pa, ca = prev.get("accounts", {}), cur.get("accounts", {})
    by_account = {}
    for name in set(pa) | set(ca):
        d = ca.get(name, 0) - pa.get(name, 0)
        if d:
            by_account[name] = d
    other = float(sum(by_account.values()))
    return {"market": market, "contributions": contributions, "other": other,
            "other_by_account": by_account, "movers": movers,
            "total": market + contributions + other}


def attribute_range(days: dict, start: str, end: str) -> dict | None:
    """Sum day-to-day attributions between the first and last complete day
    that fall in [start, end]. Day-by-day steps keep a mid-month purchase from
    being mislabelled as market growth. None if fewer than two usable days."""
    usable = sorted(d for d, v in days.items() if start <= d <= end and v.get("complete"))
    if len(usable) < 2:
        return None
    out = {"market": 0.0, "contributions": 0.0, "other": 0.0, "total": 0.0,
           "other_by_account": {}, "start": usable[0], "end": usable[-1]}
    movers: dict[tuple, float] = {}
    for d0, d1 in zip(usable, usable[1:]):
        r = attribute(days[d0], days[d1])
        for k in ("market", "contributions", "other", "total"):
            out[k] += r[k]
        for name, d in r["other_by_account"].items():
            out["other_by_account"][name] = out["other_by_account"].get(name, 0) + d
        for m in r["movers"]:
            key = (m["ticker"], m["account"])
            movers[key] = movers.get(key, 0.0) + m["market"]
    out["movers"] = sorted(
        ({"ticker": t, "account": a, "market": v} for (t, a), v in movers.items()),
        key=lambda r: -abs(r["market"]))
    return out
