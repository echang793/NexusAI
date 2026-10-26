"""Portfolio analytics from the dashboard's positions: concentration, overlap
across accounts, tax-aware asset location, asset-class mix and risk.

Pure function of its inputs (no network). The server calls it once per build
and stores the result with the day's record (daily_history), so the monthly
report can read it without recomputing anything.

Heuristics, stated plainly:
  * "fund" = a known broad index fund/ETF, a 5-letter mutual-fund ticker ending
    in X, or a sector label containing ETF/fund. Those are exempt from the
    single-name limit; a lone stock above it is flagged.
  * Asset location: a holding in a TAXABLE account (Brokerage) with a dividend
    yield of at least LOCATION_YIELD_PCT, or a bond/T-bill fund, is flagged —
    that income is taxed every year, and a Roth/401(k)/HSA would shelter it.
    It is a nudge to consider, not tax advice.
"""

import math

SINGLE_NAME_LIMIT_PCT = 10.0
LOCATION_YIELD_PCT = 2.0
TAXABLE_ACCOUNTS = {"Brokerage"}
BROAD_FUNDS = {
    "VOO", "VTI", "SPY", "IVV", "SPLG", "ITOT", "SCHB", "VT", "VXUS", "IXUS", "QQQ", "QQQM",
    "SCHD", "VIG", "DGRO", "VEA", "VWO", "IEFA", "IEMG", "SCHX", "SCHG", "VUG", "VV",
}
BOND_LIKE = {"BND", "AGG", "BIL", "SGOV", "SHV", "SHY", "ICSH", "JPST", "VGSH", "BOXX",
             "USFR", "TFLO", "BSV", "TLT", "IEF", "LQD", "HYG", "VCIT", "VCSH", "TIP"}


def _finite(x):
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def is_fund(ticker: str, sector: str = "") -> bool:
    t = (ticker or "").upper()
    s = (sector or "").lower()
    return (t in BROAD_FUNDS or t in BOND_LIKE
            or (len(t) == 5 and t.endswith("X"))
            or "etf" in s or "fund" in s)


def compute(positions: list, div_rates: dict, classify, risk: dict | None = None) -> dict:
    """positions: dicts with ticker, account, value (+ shares, price, sector).
    div_rates: ticker -> annual dividend $/share. classify(ticker, sector) ->
    asset-class label. risk: the dashboard's riskMetrics dict, passed through."""
    rows = []
    for pos in positions:
        v = _finite(pos.get("value"))
        if v is None or v <= 0:
            continue
        rows.append({**pos, "value": v})
    total = sum(r["value"] for r in rows)
    out = {"total": round(total), "top": [], "top5Pct": 0.0, "effectiveN": None,
           "stocksPct": 0.0, "topStocks": [], "singleNameFlags": [], "multiAccount": [], "location": [], "allocation": {},
           "risk": None}
    if risk:
        out["risk"] = {k: (_finite(risk.get(k))) for k in
                       ("sharpe", "sortino", "maxDrawdown", "benchmarkSharpe", "coverage")}
    if total <= 0:
        return out

    by_ticker: dict[str, dict] = {}
    for r in rows:
        t = r["ticker"]
        e = by_ticker.setdefault(t, {"ticker": t, "value": 0.0, "accounts": set(),
                                     "sector": r.get("sector") or ""})
        e["value"] += r["value"]
        e["accounts"].add(r.get("account", "Brokerage"))
    ranked = sorted(by_ticker.values(), key=lambda e: -e["value"])
    pct = lambda e: e["value"] / total * 100.0  # noqa: E731

    out["top"] = [{"ticker": e["ticker"], "pct": round(pct(e), 1), "accounts": sorted(e["accounts"])}
                  for e in ranked[:5]]
    out["top5Pct"] = round(sum(pct(e) for e in ranked[:5]), 1)
    hhi = sum((e["value"] / total) ** 2 for e in ranked)
    out["effectiveN"] = round(1.0 / hhi, 1)
    stocks = [e for e in ranked if not is_fund(e["ticker"], e["sector"])]
    out["stocksPct"] = round(sum(pct(e) for e in stocks), 1)
    out["topStocks"] = [{"ticker": e["ticker"], "pct": round(pct(e), 1)} for e in stocks[:5]]
    out["singleNameFlags"] = [{"ticker": e["ticker"], "pct": round(pct(e), 1)} for e in ranked
                              if not is_fund(e["ticker"], e["sector"]) and pct(e) > SINGLE_NAME_LIMIT_PCT]
    out["multiAccount"] = [{"ticker": e["ticker"], "pct": round(pct(e), 1),
                            "accounts": sorted(e["accounts"])}
                           for e in ranked if len(e["accounts"]) > 1]

    for r in rows:
        if r.get("account") not in TAXABLE_ACCOUNTS:
            continue
        t = r["ticker"]
        price = _finite(r.get("price"))
        rate = _finite(div_rates.get(t))
        yld = (rate / price * 100.0) if (rate and price) else 0.0
        if t in BOND_LIKE:
            out["location"].append({"ticker": t, "account": r["account"], "yieldPct": round(yld, 1),
                                    "why": "bond/T-bill interest is taxed as ordinary income"})
        elif yld >= LOCATION_YIELD_PCT:
            out["location"].append({"ticker": t, "account": r["account"], "yieldPct": round(yld, 1),
                                    "why": f"{yld:.1f}% yield is taxed every year in a taxable account"})

    alloc: dict[str, float] = {}
    for r in rows:
        c = classify(r["ticker"], r.get("sector") or "")
        alloc[c] = alloc.get(c, 0.0) + r["value"]
    out["allocation"] = {k: round(v / total * 100.0, 1)
                         for k, v in sorted(alloc.items(), key=lambda kv: -kv[1])}
    return out
