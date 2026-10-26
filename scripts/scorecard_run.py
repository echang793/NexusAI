#!/usr/bin/env python3
"""Replay the app's BUY/SELL/HOLD rules over ~5 years of the held tickers and
write reports/scorecard.txt + reports/scorecard.json.

Network (yfinance). Fails loudly — no output files — if SPY or the price
history is missing or too thin, so a bad download can't produce a report that
looks authoritative. Usage:
    .venv/bin/python3 scripts/scorecard_run.py
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import scorecard  # noqa: E402

HORIZONS = (21, 63)       # ~1 and ~3 months of trading days
MIN_ROWS = 400            # 200-day SMA warm-up + a meaningful replay window


class ScorecardError(Exception):
    pass


def scorable_tickers(holdings: list) -> list[str]:
    """Held tickers yfinance can price. Proprietary 401(k) plan codes (NON40*)
    can't be, so they're skipped."""
    out = {str(h["ticker"]).upper() for h in holdings if h.get("ticker")}
    return sorted(t for t in out if not t.startswith("NON40"))


def build_scorecard(closes, horizons=HORIZONS):
    """closes: DataFrame of adjusted closes, one column per ticker incl. SPY.
    Returns (summary, tickers_used)."""
    import indicators
    if "SPY" not in closes.columns or closes["SPY"].dropna().empty:
        raise ScorecardError("SPY benchmark data missing — refusing to score without it")
    spy = closes["SPY"].dropna()
    per_ticker, used = {}, []
    for t in closes.columns:
        if t == "SPY":
            continue
        close = closes[t].dropna()
        if len(close) < MIN_ROWS:
            continue
        df = indicators.add_indicators(close.to_frame("Close"))
        rows = scorecard.signal_rows(df, step=5)
        if rows:
            per_ticker[t] = (rows, close)
            used.append(t)
    if not per_ticker:
        raise ScorecardError("no ticker had enough price history to score")
    return scorecard.evaluate(per_ticker, spy, horizons), used


def main() -> int:
    import yfinance as yf
    import portfolio as pf
    tickers = scorable_tickers(pf.load_portfolio())
    if not tickers:
        print("no holdings to score")
        return 1
    raw = yf.download(sorted(set(tickers + ["SPY"])), period="6y", auto_adjust=True,
                      progress=False, threads=True)
    closes = raw["Close"] if "Close" in raw else raw
    try:
        summary, used = build_scorecard(closes)
    except ScorecardError as e:
        print(f"SCORECARD FAILED, nothing written: {e}")
        return 1
    text = scorecard.render(summary, used, HORIZONS)
    out = os.path.join(ROOT, "reports")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "scorecard.txt"), "w") as f:
        f.write(text + "\n")
    with open(os.path.join(out, "scorecard.json"), "w") as f:
        json.dump({"horizons": list(HORIZONS), "tickers": used, "summary":
                   {s: {str(h): v for h, v in by.items()} for s, by in summary.items()}},
                  f, allow_nan=False)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
