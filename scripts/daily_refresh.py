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

import health  # noqa: E402
import server  # noqa: E402
import plaid_sync  # noqa: E402
import import_holdings  # noqa: E402

HEALTH_FILE = health.HEALTH_FILE


def _warm_caches():
    holdings = server.pf.load_portfolio()
    tickers = [h["ticker"] for h in holdings]
    if tickers:
        server.batch_prices(tickers)
        server.compute_period_prices(tickers)
        server.compute_portfolio_risk(holdings)


def main() -> int:
    # Each step runs independently: a Plaid outage must not stop prices or the
    # snapshot. Outcomes go to health.json, which scripts/watchdog.py checks.
    run = health.Runner()
    run.step("import_holdings", import_holdings.main)
    run.step("prices", _warm_caches)

    if plaid_sync.HAS_PLAID:
        run.step("plaid_balances", lambda: print(f"Plaid balance sync: {plaid_sync.pull_balances()}"))
        run.step("plaid_holdings", lambda: print(f"Plaid holdings sync: {plaid_sync.pull_investment_holdings()}"))
        # pull_investment_holdings() may have rewritten hsa_holdings.csv (via
        # portfolio.json); re-warm the price/period/risk caches for the new list.
        run.step("prices_after_plaid", _warm_caches)

    def build():
        # Forcing a fresh build refines this month's snapshot via nw_snapshots
        server._data_cache_ts = 0.0
        data = server.build_nexus_data(force=True)
        run.extra["unpriced"] = list(data.get("pricesIncomplete") or [])
        run.extra["netWorth"] = data["netWorth"]
        print(f"Daily refresh complete: net worth ${data['netWorth']:,.0f} "
              f"({len(data['netWorthHistory'])} points in history)")

    run.step("build", build)
    record = run.finish()
    health.write(HEALTH_FILE, record)
    for name, st in record["steps"].items():
        if not st["ok"]:
            print(f"STEP FAILED: {name}: {st['error']}")
    return 0 if record["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
