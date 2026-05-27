"""Deterministic technical advisory: signal + numeric score."""

import config

RSI_BUY_BELOW = config.RSI_BUY_BELOW
RSI_SELL_ABOVE = config.RSI_SELL_ABOVE


def _is_nan(x):
    return x is None or x != x


def get_advice(df):
    """Generate advice from the latest row of an indicator-enriched DataFrame.

    Rules:
        BUY:  SMA50 > SMA200 (Golden Cross) AND RSI < 45 (oversold).
        SELL: SMA50 < SMA200 (Death Cross)  OR  RSI > 70 (overbought).
        HOLD: neither condition met.

    Returns (signal, reason) with signal in BUY | SELL | HOLD | UNKNOWN.
    """
    latest = df.iloc[-1]
    sma50 = latest.get("SMA50")
    sma200 = latest.get("SMA200")
    rsi_val = latest.get("RSI")

    if _is_nan(sma50) or _is_nan(sma200) or _is_nan(rsi_val):
        return (
            "UNKNOWN",
            "Not enough history to compute indicators "
            "(need 200+ trading days for the 200-day SMA).",
        )

    golden_cross = sma50 > sma200
    death_cross = sma50 < sma200
    oversold = rsi_val < RSI_BUY_BELOW
    overbought = rsi_val > RSI_SELL_ABOVE

    if golden_cross and oversold:
        return (
            "BUY",
            f"Golden Cross (SMA50 {sma50:.2f} > SMA200 {sma200:.2f}) and "
            f"RSI {rsi_val:.1f} is oversold (< {RSI_BUY_BELOW:.0f}).",
        )

    if death_cross or overbought:
        parts = []
        if death_cross:
            parts.append(f"Death Cross (SMA50 {sma50:.2f} < SMA200 {sma200:.2f})")
        if overbought:
            parts.append(f"RSI {rsi_val:.1f} is overbought (> {RSI_SELL_ABOVE:.0f})")
        return "SELL", " and ".join(parts) + "."

    return (
        "HOLD",
        f"No clear signal: SMA50 {sma50:.2f} vs SMA200 {sma200:.2f}, "
        f"RSI {rsi_val:.1f}.",
    )


def technical_score(df):
    """Numeric momentum/health score in [-1, 1] for the LLM/engine to consume.

    Combines trend (SMA cross), RSI positioning, and MACD histogram sign.
    Positive = bullish, negative = bearish. Returns 0.0 when indicators missing.
    """
    latest = df.iloc[-1]
    score = 0.0
    n = 0

    sma50 = latest.get("SMA50")
    sma200 = latest.get("SMA200")
    if not (_is_nan(sma50) or _is_nan(sma200)):
        # Trend: relative gap between fast and slow SMA, capped.
        gap = (sma50 - sma200) / sma200 if sma200 else 0.0
        score += max(-1.0, min(1.0, gap * 10.0))
        n += 1

    rsi_val = latest.get("RSI")
    if not _is_nan(rsi_val):
        # Map RSI 30->+1 (oversold = opportunity), 70->-1 (overbought = risk).
        rsi_component = (50.0 - rsi_val) / 20.0
        score += max(-1.0, min(1.0, rsi_component))
        n += 1

    hist = latest.get("MACD_hist")
    if not _is_nan(hist):
        score += 1.0 if hist > 0 else -1.0
        n += 1

    if n == 0:
        return 0.0
    return round(score / n, 3)
