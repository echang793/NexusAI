"""Portfolio persistence, valuation, and concentration analysis."""

import io
import json
import os

import pandas as pd

import config
from data import get_fundamentals, latest_price

COLUMNS = ["ticker", "shares", "avg_cost"]


# --- Persistence -----------------------------------------------------------
def load_portfolio(path=None):
    """Load holdings from portfolio.json. Returns a list of dicts (possibly empty)."""
    path = path or config.PORTFOLIO_FILE
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except Exception:
        return []
    return _coerce(data.get("holdings", data) if isinstance(data, dict) else data)


def save_portfolio(holdings, path=None):
    """Persist holdings to portfolio.json."""
    path = path or config.PORTFOLIO_FILE
    clean = _coerce(holdings)
    with open(path, "w") as f:
        json.dump({"holdings": clean}, f, indent=2)
    return clean


def _coerce(rows):
    """Normalize arbitrary row input into clean holding dicts."""
    out = []
    for r in rows or []:
        ticker = str(r.get("ticker", "")).strip().upper()
        if not ticker:
            continue
        try:
            raw_shares = r.get("shares", 0)
            raw_cost = r.get("avg_cost", 0)
            # Guard against NaN values from pandas CSV parsing
            shares = float(raw_shares) if raw_shares not in (None, "") else 0.0
            avg_cost = float(raw_cost) if raw_cost not in (None, "") else 0.0
            # NaN check: NaN != NaN
            if shares != shares or avg_cost != avg_cost:
                continue
        except (TypeError, ValueError):
            continue
        if shares <= 0:
            continue
        out.append({"ticker": ticker, "shares": shares, "avg_cost": avg_cost})
    return out


# --- CSV import/export -----------------------------------------------------
def to_csv(holdings):
    df = pd.DataFrame(_coerce(holdings), columns=COLUMNS)
    return df.to_csv(index=False)


def from_csv(file_or_bytes):
    """Parse uploaded CSV (path, bytes, or file-like) into holdings.

    Returns (holdings: list, dropped: int) where dropped is the count of
    skipped rows due to invalid ticker/shares.
    """
    if isinstance(file_or_bytes, (bytes, bytearray)):
        df = pd.read_csv(io.BytesIO(file_or_bytes))
    else:
        df = pd.read_csv(file_or_bytes)
    df.columns = [str(c).strip().lower() for c in df.columns]
    rows = df.to_dict("records")
    raw_count = len(rows)
    holdings = _coerce(rows)
    dropped = raw_count - len(holdings)
    return holdings, dropped


# --- Valuation -------------------------------------------------------------
def value_portfolio(holdings, price_fn=latest_price, fundamentals_fn=get_fundamentals):
    """Compute per-position valuation + totals + sector concentration.

    Returns dict:
        positions: list of dicts (ticker, shares, avg_cost, price, value,
                   cost_basis, unrealized, unrealized_pct, weight, sector)
        total_value, total_cost, total_unrealized, total_unrealized_pct
        concentration_flags: list of strings
        sector_weights: dict sector -> weight
    """
    holdings = _coerce(holdings)
    positions = []
    total_value = 0.0
    total_cost = 0.0

    for h in holdings:
        price = price_fn(h["ticker"])
        sector = None
        try:
            sector = fundamentals_fn(h["ticker"]).get("sector")
        except Exception:
            sector = None

        cost_basis = h["shares"] * h["avg_cost"]
        if price is None:
            positions.append(
                {
                    **h,
                    "price": None,
                    "value": None,
                    "cost_basis": cost_basis,
                    "unrealized": None,
                    "unrealized_pct": None,
                    "weight": None,
                    "sector": sector,
                }
            )
            total_cost += cost_basis
            continue

        value = h["shares"] * price
        unrealized = value - cost_basis
        unrealized_pct = (unrealized / cost_basis * 100.0) if cost_basis else None
        positions.append(
            {
                **h,
                "price": price,
                "value": value,
                "cost_basis": cost_basis,
                "unrealized": unrealized,
                "unrealized_pct": unrealized_pct,
                "weight": None,  # filled after totals
                "sector": sector,
            }
        )
        total_value += value
        total_cost += cost_basis

    # Fill weights + sector aggregation.
    sector_weights = {}
    for p in positions:
        if p["value"] and total_value > 0:
            p["weight"] = p["value"] / total_value
            sec = p["sector"] or "Unknown"
            sector_weights[sec] = sector_weights.get(sec, 0.0) + p["weight"]

    total_unrealized = total_value - total_cost
    total_unrealized_pct = (total_unrealized / total_cost * 100.0) if total_cost else None

    flags = _concentration_flags(positions, sector_weights)

    return {
        "positions": positions,
        "total_value": total_value,
        "total_cost": total_cost,
        "total_unrealized": total_unrealized,
        "total_unrealized_pct": total_unrealized_pct,
        "concentration_flags": flags,
        "sector_weights": sector_weights,
    }


def _concentration_flags(positions, sector_weights, threshold=None):
    threshold = threshold if threshold is not None else config.CONCENTRATION_THRESHOLD
    flags = []
    for p in positions:
        if p["weight"] and p["weight"] > threshold:
            flags.append(
                f"{p['ticker']} is {p['weight'] * 100:.0f}% of the portfolio "
                f"(> {threshold * 100:.0f}% concentration threshold)."
            )
        # Tax-loss harvesting alert
        upct = p.get("unrealized_pct")
        if upct is not None and upct < -10:
            flags.append(
                f"TAX-LOSS: {p['ticker']} is down {upct:.1f}% — "
                f"consider harvesting loss before year-end."
            )
    for sec, w in sector_weights.items():
        if w > max(0.4, threshold + 0.15):
            flags.append(f"Sector '{sec}' is {w * 100:.0f}% of the portfolio.")
    return flags


def _fallback_rebalancing(valuation):
    """Rule-based rebalancing suggestions from valuation data."""
    suggestions = []
    threshold = config.CONCENTRATION_THRESHOLD
    for p in valuation.get("positions", []):
        w = p.get("weight")
        if w and w > threshold:
            suggestions.append(
                f"Consider trimming {p['ticker']} ({w*100:.0f}% of portfolio) "
                f"to reduce below the {threshold*100:.0f}% concentration limit."
            )
    sector_weights = valuation.get("sector_weights", {})
    for sec, w in sector_weights.items():
        if w > 0.4:
            suggestions.append(
                f"Sector '{sec}' at {w*100:.0f}% — "
                f"consider diversifying into other sectors."
            )
    if not suggestions:
        suggestions.append(
            "Portfolio concentration looks reasonable. "
            "Review annually or when any position exceeds 25% of total value."
        )
    return suggestions
