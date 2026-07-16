#!/usr/bin/env python3
"""Headless daily data refresh — runs without the web server.

Folds in any dropped brokerage exports (imports/), pulls live prices,
recomputes portfolio risk, syncs Plaid balances (if configured), and
refines this month's net-worth snapshot. Safe to run repeatedly (net worth
snapshot is one bucket per calendar month).

Usage:
    .venv/bin/python3 scripts/daily_refresh.py
Scheduled daily via scripts/com.nexusai.dailyrefresh.plist (launchd).
"""

import os
import sys

# Make the project root importable regardless of CWD
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import server  # noqa: E402
import plaid_sync  # noqa: E402
import import_holdings  # noqa: E402


def main() -> int:
    import_holdings.main()

    holdings = server.pf.load_portfolio()
    tickers = [h["ticker"] for h in holdings]
    if tickers:
        server.batch_prices(tickers)
        server.compute_period_prices(tickers)
        server.compute_portfolio_risk(holdings)

    if plaid_sync.HAS_PLAID:
        result = plaid_sync.pull_balances()
        print(f"Plaid sync: {result}")

    # Forcing a fresh build refines this month's snapshot via nw_snapshots
    server._data_cache_ts = 0.0
    data = server.build_nexus_data(force=True)
    print(f"Daily refresh complete: net worth ${data['netWorth']:,.0f} "
          f"({len(data['netWorthHistory'])} points in history)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
