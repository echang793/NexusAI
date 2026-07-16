#!/usr/bin/env python3
"""Normalize native brokerage exports and fold them into portfolio.json.

Drop a raw export into imports/ and run this script (or let
scripts/daily_refresh.py call it automatically). It detects which
institution the file came from by its column headers, converts it to
ticker,shares,avg_cost, and merges it into the matching per-account CSV
(brokerage_holdings.csv, roth_ira_holdings.csv, or hsa_holdings.csv). All
*_holdings.csv files are then concatenated (each row tagged with its source
account — NOT merged across accounts, so the same ticker held in two
different accounts stays as two separate rows) into combined_holdings.csv,
which is written to portfolio.json.

Account routing:
    Fidelity exports can bundle multiple accounts (401k, HSA, brokerage) in
    one download, distinguished by the "Account Name" column — so Fidelity
    rows are routed per-row by that column (HSA/Health Savings -> hsa,
    Roth -> roth, everything else -> brokerage; 401(k) plan tickers self-tag
    via their NON40* opaque codes in server.py regardless of which file they
    land in, so they don't need their own bucket here).

    Webull and already-normalized CSVs have no per-row account column, so
    they're routed by filename instead:
        *roth*                      -> roth_ira_holdings.csv
        *hsa*                       -> hsa_holdings.csv
        anything else               -> brokerage_holdings.csv

Supported source formats (detected by header, not filename):
    Fidelity export  (Symbol, Quantity, + either "Cost Basis Per Share" or
                       "Average Cost Basis" — Fidelity's template varies by
                       account type)
    Webull order-history export  (Symbol, Side, Qty, Average Fill Price, ...)
    Already-normalized           (ticker, shares, avg_cost)

Webull only exports order history (not a positions/cost-basis snapshot), so
its shares/avg_cost are derived by replaying buy/sell orders in the file.
If you've held a position longer than the export window (Webull caps
history at 90 days), the derived avg_cost will be wrong for that ticker —
this script prints a warning so you can catch it rather than silently
trusting a bad number.

Usage:
    .venv/bin/python3 scripts/import_holdings.py
"""

import glob
import os
import shutil
import sys
from datetime import datetime

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import portfolio as pf  # noqa: E402

IMPORTS_DIR = os.path.join(ROOT, "imports")
PROCESSED_DIR = os.path.join(IMPORTS_DIR, "processed")

ACCOUNT_FILES = {
    "roth": "roth_ira_holdings.csv",
    "hsa": "hsa_holdings.csv",
}
DEFAULT_ACCOUNT_FILE = "brokerage_holdings.csv"

ALL_ACCOUNT_FILES = [DEFAULT_ACCOUNT_FILE, *ACCOUNT_FILES.values()]
COMBINED_FILE = "combined_holdings.csv"


def _norm_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df


def _bucket_for_account_name(name: str) -> str:
    n = (name or "").lower()
    if "hsa" in n or "health savings" in n:
        return "hsa"
    if "roth" in n:
        return "roth"
    return "brokerage"  # covers taxable brokerage + 401(k)/retirement plans


def parse_fidelity(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Fidelity 'Positions' export: Symbol, Quantity, Cost Basis Per Share, ...

    May bundle multiple accounts in one file — split per-row by the
    'Account Name' column when present, since a single download can mix
    e.g. a 401(k)/retirement plan with an HSA (as Fidelity's export does).
    """
    by_bucket: dict[str, list[dict]] = {}
    has_account_col = "account name" in df.columns
    # Fidelity's export template varies by account type: brokerage "Positions"
    # exports use "Cost Basis Per Share"; retirement/HSA exports have seen
    # "Average Cost Basis" instead. Accept either.
    cost_col = "cost basis per share" if "cost basis per share" in df.columns else "average cost basis"
    for _, r in df.iterrows():
        ticker = str(r.get("symbol", "")).strip().upper()
        if not ticker or ticker in ("CASH", "PENDING ACTIVITY", "NAN"):
            continue
        try:
            shares = float(r.get("quantity"))
            avg_cost = float(r.get(cost_col))
        except (TypeError, ValueError):
            continue
        if shares != shares or avg_cost != avg_cost or shares <= 0:  # NaN guard
            continue
        bucket = _bucket_for_account_name(r.get("account name", "")) if has_account_col else "brokerage"
        by_bucket.setdefault(bucket, []).append(
            {"ticker": ticker, "shares": shares, "avg_cost": avg_cost}
        )
    return {
        b: pd.DataFrame(rows, columns=["ticker", "shares", "avg_cost"])
        for b, rows in by_bucket.items()
    }


def parse_webull_orders(df: pd.DataFrame) -> pd.DataFrame:
    """Webull order-history export: replay Filled Buy/Sell rows into net positions."""
    positions: dict[str, dict] = {}
    status_col = "status" if "status" in df.columns else None
    for _, r in df.iterrows():
        if status_col and str(r.get(status_col, "")).strip().lower() not in ("filled", ""):
            continue
        ticker = str(r.get("symbol", "")).strip().upper()
        side = str(r.get("side", "")).strip().lower()
        try:
            qty = float(r.get("qty"))
            price = float(r.get("average fill price") or r.get("avg fill price"))
        except (TypeError, ValueError):
            continue
        if not ticker or qty != qty or price != price or qty <= 0:
            continue

        pos = positions.setdefault(ticker, {"shares": 0.0, "avg_cost": 0.0})
        if side.startswith("buy"):
            total_cost = pos["shares"] * pos["avg_cost"] + qty * price
            pos["shares"] += qty
            pos["avg_cost"] = total_cost / pos["shares"] if pos["shares"] else 0.0
        elif side.startswith("sell"):
            pos["shares"] = max(0.0, pos["shares"] - qty)  # avg_cost unchanged on sells

    rows = [
        {"ticker": t, "shares": p["shares"], "avg_cost": p["avg_cost"]}
        for t, p in positions.items() if p["shares"] > 0
    ]
    if rows:
        print("  WARNING: Webull position derived from order history only. "
              "If you've held this longer than the export window (Webull caps "
              "history at 90 days), avg_cost may be understated — verify "
              "against the Webull app before trusting it.")
    return pd.DataFrame(rows, columns=["ticker", "shares", "avg_cost"])


def parse_normalized(df: pd.DataFrame) -> pd.DataFrame:
    return df[["ticker", "shares", "avg_cost"]].copy()


def account_bucket_for_filename(filename: str) -> str:
    lower = filename.lower()
    for key in ACCOUNT_FILES:
        if key in lower:
            return key
    return "brokerage"


def detect_and_parse(path: str, filename: str) -> dict[str, pd.DataFrame] | None:
    """Returns {bucket_key: DataFrame} where bucket_key is 'brokerage'/'roth'/'hsa'."""
    raw = pd.read_csv(path)
    df = _norm_cols(raw)
    cols = set(df.columns)

    if {"ticker", "shares", "avg_cost"}.issubset(cols):
        return {account_bucket_for_filename(filename): parse_normalized(df)}
    if {"symbol", "quantity"}.issubset(cols) and (
        "cost basis per share" in cols or "average cost basis" in cols
    ):
        return parse_fidelity(df)
    if {"symbol", "side", "qty"}.issubset(cols) and (
        "average fill price" in cols or "avg fill price" in cols
    ):
        return {account_bucket_for_filename(filename): parse_webull_orders(df)}
    return None


def bucket_to_file(bucket: str) -> str:
    return ACCOUNT_FILES.get(bucket, DEFAULT_ACCOUNT_FILE)


def merge_by_ticker(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Sum shares and weight-average cost across multiple parsed sources."""
    totals: dict[str, dict] = {}
    for df in frames:
        for _, r in df.iterrows():
            ticker = str(r["ticker"]).strip().upper()
            shares = float(r["shares"])
            avg_cost = float(r["avg_cost"])
            pos = totals.setdefault(ticker, {"shares": 0.0, "cost": 0.0})
            pos["shares"] += shares
            pos["cost"] += shares * avg_cost
    rows = [
        {"ticker": t, "shares": p["shares"], "avg_cost": p["cost"] / p["shares"]}
        for t, p in totals.items() if p["shares"] > 0
    ]
    rows.sort(key=lambda r: r["ticker"])
    return pd.DataFrame(rows, columns=["ticker", "shares", "avg_cost"])


_BUCKET_BY_FILE = {**{v: k for k, v in ACCOUNT_FILES.items()}, DEFAULT_ACCOUNT_FILE: "brokerage"}


def recombine(root: str) -> list[dict]:
    """Concatenate every *_holdings.csv into portfolio.json, tagging each row
    with its source account.

    Deliberately does NOT merge across files: two different real accounts
    can legitimately hold the same ticker (e.g. MU in both Roth and
    Brokerage), and collapsing those into one blended row would misattribute
    the combined value to whichever account happened to match first. Only
    duplicate tickers WITHIN the same file are merged (e.g. multiple lots).
    """
    combined: list[dict] = []
    for fname in ALL_ACCOUNT_FILES:
        path = os.path.join(root, fname)
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path)
        if df.empty:
            continue
        account = _BUCKET_BY_FILE[fname]
        within_file = merge_by_ticker([df])
        for _, r in within_file.iterrows():
            combined.append({
                "ticker": str(r["ticker"]).upper(),
                "shares": float(r["shares"]),
                "avg_cost": float(r["avg_cost"]),
                "account": account,
            })

    combined.sort(key=lambda r: (r["account"], r["ticker"]))

    out_path = os.path.join(root, COMBINED_FILE)
    pd.DataFrame(combined, columns=["ticker", "shares", "avg_cost", "account"]).to_csv(
        out_path, index=False
    )
    return combined


def main() -> int:
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    files = sorted(glob.glob(os.path.join(IMPORTS_DIR, "*.csv")))
    if not files:
        print("No files in imports/ — nothing to do.")
        return 0

    # Group parsed sources by destination account file so that, e.g., a
    # Webull export and a Fidelity brokerage export dropped in the same run
    # both land in brokerage_holdings.csv without one clobbering the other.
    by_dest: dict[str, list[pd.DataFrame]] = {}
    to_archive: list[str] = []

    for path in files:
        fname = os.path.basename(path)
        print(f"Processing {fname} ...")
        by_bucket = detect_and_parse(path, fname)
        if not by_bucket or all(df.empty for df in by_bucket.values()):
            print(f"  Could not recognize format of {fname} — skipping (left in place).")
            continue

        for bucket, parsed in by_bucket.items():
            if parsed.empty:
                continue
            dest_file = bucket_to_file(bucket)
            by_dest.setdefault(dest_file, []).append(parsed)
            print(f"  -> {len(parsed)} tickers parsed for {dest_file} ({bucket})")
        to_archive.append(path)

    touched = False
    for dest_file, frames in by_dest.items():
        merged = merge_by_ticker(frames)
        dest_path = os.path.join(ROOT, dest_file)
        merged.to_csv(dest_path, index=False)
        print(f"{dest_file} replaced with {len(merged)} tickers from this run's exports")
        touched = True

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for path in to_archive:
        fname = os.path.basename(path)
        shutil.move(path, os.path.join(PROCESSED_DIR, f"{stamp}_{fname}"))

    if not touched:
        return 0

    combined = recombine(ROOT)
    clean = pf.save_portfolio(combined)
    print(f"portfolio.json updated: {len(clean)} tickers "
          f"({COMBINED_FILE} regenerated from all account CSVs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
