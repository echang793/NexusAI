#!/usr/bin/env python3
"""Apply a manually-read snapshot (e.g. from a chat-pasted screenshot) to NexusAI.

Claude reads tickers/shares/avg-cost or account balances off a screenshot in
conversation, writes them as JSON, and this script applies that JSON to the
data store — same account-tagging buckets as scripts/import_holdings.py, and
the same net-worth snapshot tail as scripts/daily_refresh.py.

Payload shape (--file path.json or stdin):
{
  "positions": [
    {"account": "brokerage", "ticker": "AAPL", "shares": 5, "avg_cost": 200.0}
  ],
  "balances": [
    {"name": "Chase Checking", "type": "Checking", "balance": 4200.00}
  ]
}

"account" is one of "brokerage" / "roth" / "hsa" (see import_holdings.ACCOUNT_FILES).
"avg_cost" is optional for a ticker that already exists in that account's CSV
(existing avg_cost is kept, only shares update). It is required for a new
ticker — omitting it skips that ticker with a warning rather than guessing.

Usage:
    .venv/bin/python3 scripts/apply_snapshot.py --file snapshot.json
    echo '{...}' | .venv/bin/python3 scripts/apply_snapshot.py
"""

import argparse
import datetime
import json
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import accounts as ac  # noqa: E402
import server  # noqa: E402
import import_holdings  # noqa: E402


def apply_positions(positions: list[dict]) -> list[str]:
    """Merge screenshot-read positions into their account CSVs. Returns messages."""
    messages = []
    by_bucket: dict[str, list[dict]] = {}
    for p in positions:
        bucket = str(p.get("account", "brokerage")).strip().lower()
        ticker = str(p.get("ticker", "")).strip().upper()
        if not ticker:
            continue
        by_bucket.setdefault(bucket, []).append(p)

    for bucket, rows in by_bucket.items():
        dest_file = import_holdings.bucket_to_file(bucket)
        dest_path = os.path.join(ROOT, dest_file)
        # Upsert, not replace: a bucket like "brokerage" can hold tickers
        # from multiple unrelated sources (e.g. a Fidelity 401k and a Webull
        # account both land here), each updated on its own schedule. A full
        # replace using only this run's payload would silently drop every
        # ticker from a source not mentioned in this particular screenshot.
        by_ticker: dict[str, dict] = {}
        if os.path.exists(dest_path):
            df = pd.read_csv(dest_path)
            for _, r in df.iterrows():
                t = str(r["ticker"]).upper()
                by_ticker[t] = {"ticker": t, "shares": float(r["shares"]), "avg_cost": float(r["avg_cost"])}

        for p in rows:
            ticker = str(p["ticker"]).strip().upper()
            shares = float(p["shares"])
            avg_cost = p.get("avg_cost")
            if avg_cost in (None, ""):
                if ticker in by_ticker:
                    avg_cost = by_ticker[ticker]["avg_cost"]
                    messages.append(f"{ticker}: kept existing avg_cost ${avg_cost:,.2f}, updated shares to {shares}")
                else:
                    messages.append(f"SKIPPED {ticker}: new ticker with no avg_cost given — "
                                     f"tell me the cost basis and I'll re-run.")
                    continue
            else:
                avg_cost = float(avg_cost)
            by_ticker[ticker] = {"ticker": ticker, "shares": shares, "avg_cost": avg_cost}

        merged = pd.DataFrame(sorted(by_ticker.values(), key=lambda r: r["ticker"]),
                               columns=["ticker", "shares", "avg_cost"])
        merged.to_csv(dest_path, index=False)
        messages.append(f"{dest_file}: {len(merged)} tickers written")

    if by_bucket:
        combined = import_holdings.recombine(ROOT)
        server.pf.save_portfolio(combined)
        messages.append(f"portfolio.json updated: {len(combined)} tickers")

    return messages


def apply_balances(balances: list[dict]) -> list[str]:
    """Upsert account balances by name without wiping untouched accounts."""
    messages = []
    if not balances:
        return messages

    existing = ac.load_accounts()
    by_name = {a["name"].strip().lower(): a for a in existing}
    today = datetime.date.today().isoformat()

    for b in balances:
        name = str(b.get("name", "")).strip()
        if not name:
            continue
        key = name.lower()
        atype = str(b.get("type", "Other Asset")).strip()
        balance = float(b.get("balance", 0))
        if key in by_name:
            by_name[key]["balance"] = balance
            by_name[key]["updated"] = today
            messages.append(f"{name}: balance updated to ${balance:,.2f}")
        else:
            new_acct = {"name": name, "type": atype, "balance": balance,
                        "notes": "", "updated": today}
            by_name[key] = new_acct
            existing.append(new_acct)
            messages.append(f"{name}: new account added (${balance:,.2f})")

    ac.save_accounts(existing)
    return messages


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", help="Path to JSON payload (else read from stdin)")
    args = parser.parse_args()

    raw = open(args.file).read() if args.file else sys.stdin.read()
    payload = json.loads(raw)

    messages = []
    messages += apply_positions(payload.get("positions", []))
    messages += apply_balances(payload.get("balances", []))

    for m in messages:
        print(m)

    if not messages:
        print("Nothing to apply — payload had no positions or balances.")
        return 0

    # server.py only loads price_cache.json from disk in its __main__ block,
    # not on import — load it here so this short-lived process sees prices
    # already fetched by the running app/daily job instead of falling back
    # to avg_cost for everything.
    server._load_price_cache()

    # build_nexus_data's live-price refresh runs in a background thread that
    # this process would exit before finishing — fetch synchronously first
    # so the printed net worth reflects real market prices, not cost basis.
    holdings = server.pf.load_portfolio()
    tickers = [h["ticker"] for h in holdings]
    if tickers:
        server.batch_prices(tickers)

    server._data_cache_ts = 0.0
    data = server.build_nexus_data(force=True)
    print(f"Snapshot applied: net worth ${data['netWorth']:,.0f} "
          f"({len(data['netWorthHistory'])} points in history)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
