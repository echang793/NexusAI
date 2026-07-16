#!/usr/bin/env python3
"""Headless monthly net-worth snapshot — runs without the web server.

Pulls live prices, recomputes net worth, and records this month's snapshot to
nw_history.json. Safe to run repeatedly (one bucket per calendar month).

Usage:
    .venv/bin/python3 scripts/monthly_snapshot.py
Scheduled monthly via scripts/com.nexusai.snapshot.plist (launchd).
"""

import os
import sys

# Make the project root importable regardless of CWD
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import server  # noqa: E402


def main() -> int:
    holdings = server.pf.load_portfolio()
    tickers = [h["ticker"] for h in holdings]
    if tickers:
        server.batch_prices(tickers)
        server.compute_period_prices(tickers)
        server.compute_portfolio_risk(holdings)
    # Forcing a fresh build records this month's snapshot via _net_worth_history
    server._data_cache_ts = 0.0
    data = server.build_nexus_data(force=True)
    print(f"Snapshot recorded: net worth ${data['netWorth']:,.0f} "
          f"({len(data['netWorthHistory'])} points in history)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
