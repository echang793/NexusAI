"""Stock-vs-safe allocation drift check.

yfinance's "sector" field is unreliable for ETFs (usually empty/"—"), so
this classifies the "safe" bucket by a known ticker list of money-market
and T-bill funds rather than by sector — everything else counts as stock
exposure. Coarse on purpose: a drift smoke-alarm, not a full asset-class
breakdown.
"""

SAFE_TICKERS = {"SGOV", "BIL", "SHV", "SHY", "ICSH", "JPST", "VGSH", "BOXX", "USFR", "TFLO", "BSV"}
DRIFT_TOLERANCE_PCT = 5.0


def compute(profile: dict, positions: list) -> dict:
    target_stock = float(profile.get("target_stock_pct", 90) or 90)
    safe_weight = sum(p["weight"] for p in positions if p["ticker"] in SAFE_TICKERS)
    actual_stock = max(0.0, 100.0 - safe_weight)
    drift = actual_stock - target_stock
    return {
        "targetStockPct": target_stock,
        "actualStockPct": round(actual_stock, 1),
        "safePct": round(safe_weight, 1),
        "drift": round(drift, 1),
        "onTarget": abs(drift) <= DRIFT_TOLERANCE_PCT,
    }
