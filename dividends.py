"""Portfolio dividend income projection from a per-ticker annual-rate cache.

The cache (ticker -> $/share/year) is populated by server.py's background
enrichment thread via data.get_dividend_info() — this module just does the
shares-weighted sum, no network calls of its own.
"""


def compute(positions: list, div_rate_cache: dict) -> dict:
    rows = []
    total = 0.0
    for p in positions:
        rate = div_rate_cache.get(p["ticker"])
        if not rate:
            continue
        income = rate * p["shares"]
        if income <= 0:
            continue
        total += income
        rows.append({
            "ticker": p["ticker"],
            "annualIncome": round(income, 2),
            "ratePerShare": round(rate, 4),
            "shares": p["shares"],
        })
    rows.sort(key=lambda r: -r["annualIncome"])
    return {
        "annualIncome": round(total, 2),
        "monthlyAvg": round(total / 12.0, 2),
        "topPayers": rows[:8],
    }
