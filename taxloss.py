"""Tax-loss harvesting candidate scan — pure function over current positions.

Limitation: no purchase-date or transaction/sale history is tracked (only
current shares + avg_cost per ticker), so this can only flag current
UNREALIZED losses. It cannot split short- vs long-term, and cannot warn
about wash sales against a past sale — there's no sale history to check
against. Treat this as a starting list to verify in your broker, not a
final answer.
"""


def scan(positions: list, threshold_pct: float = -10.0) -> list:
    out = []
    for p in positions:
        pl_pct = p.get("plPct", 0) or 0
        if pl_pct <= threshold_pct:
            out.append({
                "ticker": p["ticker"],
                "account": p.get("account", ""),
                "shares": p["shares"],
                "avgCost": p["avg_cost"],
                "price": p["price"],
                "unrealizedLoss": round(p["pl"], 2),
                "plPct": round(pl_pct, 1),
            })
    return sorted(out, key=lambda x: x["plPct"])
