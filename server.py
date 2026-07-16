"""NexusAI web server — Flask backend serving the design UI with real data."""

import datetime
import json
import math
import os
import sys
import time
import threading

from flask import Flask, Response, jsonify, request, send_from_directory

sys.path.insert(0, os.path.dirname(__file__))

import accounts as ac
import nw_snapshots
import portfolio as pf
import profile as pr
import watchlist as wl
import config
from analyst import analyze_ticker, chat_with_advisor, stream_chat_reply  # noqa: F401
from data import (
    DataError, fetch_data, get_dividend_info, get_fundamentals,
    get_next_earnings,
)
from indicators import add_indicators, latest_snapshot
from news import company_news

DESIGN_DIR = os.path.join(os.path.dirname(__file__), "design_handoff_nexusai", "design")

import logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "WARNING"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("nexusai")

app = Flask(__name__, static_folder=DESIGN_DIR)
app.logger.setLevel("WARNING")

# ---------------------------------------------------------------------------
# Sector cache (fetched lazily, stored in memory)
# ---------------------------------------------------------------------------
_sector_cache: dict[str, str] = {}
_sector_lock = threading.Lock()


def _get_sector(ticker: str) -> str:
    with _sector_lock:
        if ticker in _sector_cache:
            return _sector_cache[ticker]
    try:
        fund = get_fundamentals(ticker)
        sector = fund.get("sector") or "—"
    except Exception:
        sector = "—"
    with _sector_lock:
        _sector_cache[ticker] = sector
    return sector


def _prefetch_sectors(tickers: list[str]) -> None:
    """Background thread: fetch sectors for all tickers."""
    def _run():
        for t in tickers:
            _get_sector(t)
    threading.Thread(target=_run, daemon=True).start()


# ---------------------------------------------------------------------------
# Price cache (TTL 15 min, batch via yfinance)
# ---------------------------------------------------------------------------
_pcache: dict[str, float | None] = {}
_pcache_ts: dict[str, float] = {}
_pcache_lock = threading.Lock()

PRICE_CACHE_FILE = os.path.join(os.path.dirname(__file__), "price_cache.json")

# Benchmarks always kept in cache regardless of holdings
_KEEP_TICKERS = {"SPY"}


def _known_tickers() -> set[str]:
    """Current portfolio tickers + always-kept benchmarks. Empty set on failure
    means 'prune nothing' (safe default)."""
    try:
        holdings = pf.load_portfolio()
        return {h["ticker"] for h in holdings} | _KEEP_TICKERS
    except Exception:
        return set()


def _load_price_cache() -> None:
    """Load persisted prices on startup so the fast path serves real data."""
    global _pcache, _pcache_ts
    try:
        with open(PRICE_CACHE_FILE, "r") as f:
            data = json.load(f)
        with _pcache_lock:
            _pcache = {k: (float(v) if v is not None else None) for k, v in data.get("prices", {}).items()}
            _pcache_ts = {k: float(v) for k, v in data.get("ts", {}).items()}
    except Exception:
        pass


def _save_price_cache() -> None:
    try:
        keep = _known_tickers()
        with _pcache_lock:
            if keep:  # prune stale tickers in place (skip if lookup failed)
                for t in [k for k in _pcache if k not in keep]:
                    _pcache.pop(t, None)
                    _pcache_ts.pop(t, None)
            payload = {"prices": dict(_pcache), "ts": dict(_pcache_ts)}
        tmp = PRICE_CACHE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(payload, f)
        os.replace(tmp, PRICE_CACHE_FILE)
    except Exception:
        pass


def batch_prices(tickers: list[str]) -> dict[str, float | None]:
    import yfinance as yf
    now = time.time()
    ttl = config.CACHE_TTL_SECONDS

    with _pcache_lock:
        need = [t for t in tickers if now - _pcache_ts.get(t, 0) >= ttl]

    if need:
        try:
            raw = yf.download(need, period="2d", auto_adjust=True, progress=False, threads=True)
            close = raw["Close"] if "Close" in raw else raw
            with _pcache_lock:
                for t in need:
                    try:
                        col = close[t] if len(need) > 1 else close
                        _pcache[t] = float(col.dropna().iloc[-1])
                    except Exception:
                        _pcache[t] = None
                    _pcache_ts[t] = now
            _save_price_cache()
        except Exception:
            with _pcache_lock:
                for t in need:
                    if t not in _pcache:
                        _pcache[t] = None
                    _pcache_ts[t] = now

    with _pcache_lock:
        return {t: _pcache.get(t) for t in tickers}


def single_price(ticker: str) -> float | None:
    return batch_prices([ticker]).get(ticker)


# ---------------------------------------------------------------------------
# Period-return cache — price N trading days ago, for P/L horizon toggle
# ---------------------------------------------------------------------------
# Maps ticker -> {"1M": price, "3M": price, "6M": price, "1Y": price}
_period_cache: dict[str, dict] = {}
_period_ts: float = 0.0
_period_lock = threading.Lock()
PERIOD_CACHE_FILE = os.path.join(os.path.dirname(__file__), "period_cache.json")
# Approx trading-day offsets per horizon
_HORIZON_OFFSETS = {"1M": 21, "3M": 63, "6M": 126, "1Y": 251}


def _load_period_cache() -> None:
    global _period_cache, _period_ts
    try:
        with open(PERIOD_CACHE_FILE, "r") as f:
            data = json.load(f)
        with _period_lock:
            _period_cache = data.get("periods", {})
            _period_ts = float(data.get("ts", 0))
    except Exception:
        pass


def _save_period_cache() -> None:
    try:
        keep = _known_tickers()
        with _period_lock:
            if keep:
                for t in [k for k in _period_cache if k not in keep]:
                    _period_cache.pop(t, None)
            payload = {"periods": dict(_period_cache), "ts": _period_ts}
        tmp = PERIOD_CACHE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(payload, f)
        os.replace(tmp, PERIOD_CACHE_FILE)
    except Exception:
        pass


def compute_period_prices(tickers: list[str]) -> None:
    """Batch-download 1y history; store price N trading days ago per horizon."""
    global _period_ts
    import yfinance as yf
    if not tickers:
        return
    try:
        raw = yf.download(tickers, period="1y", auto_adjust=True, progress=False, threads=True)
        close = raw["Close"] if "Close" in raw else raw
    except Exception as e:
        log.debug("compute_period_prices download failed: %s", e)
        return

    out: dict[str, dict] = {}
    for t in tickers:
        try:
            series = close[t] if len(tickers) > 1 else close
            series = series.dropna()
            if len(series) < 2:
                continue
            horizons = {}
            n = len(series)
            for label, offset in _HORIZON_OFFSETS.items():
                idx = n - 1 - offset
                if idx < 0:
                    idx = 0  # not enough history → use earliest available
                horizons[label] = float(series.iloc[idx])
            # Downsample last ~6mo to ~24 points for a REAL sparkline
            recent = series.iloc[-126:] if n > 126 else series
            step = max(1, len(recent) // 24)
            spark = [round(float(v), 2) for v in recent.iloc[::step].tolist()][-24:]
            out[t] = {"h": horizons, "spark": spark}
        except Exception:
            continue

    with _period_lock:
        _period_cache.update(out)
        _period_ts = time.time()
    _save_period_cache()


def _period_entry(ticker: str):
    """Return (horizons_dict, spark_list) handling old + new cache shapes."""
    with _period_lock:
        e = _period_cache.get(ticker)
    if not e:
        return None, None
    if "h" in e:  # new shape
        return e.get("h"), e.get("spark")
    return e, None  # legacy: flat horizons dict


def _position_periods(ticker: str, shares: float, price: float, avg_cost: float,
                      pl: float, pl_pct: float) -> dict:
    """Build the per-horizon P/L map for one position."""
    periods = {"ALL": {"pl": round(pl, 2), "pct": round(pl_pct, 2)}}
    hz, _ = _period_entry(ticker)
    if hz and price:
        for label, then in hz.items():
            if then and then > 0:
                period_pl = (price - then) * shares
                period_pct = (price / then - 1) * 100
                periods[label] = {"pl": round(period_pl, 2), "pct": round(period_pct, 2)}
    return periods


def _position_spark(ticker: str):
    """Real downsampled price series for the trend sparkline (or None)."""
    _, spark = _period_entry(ticker)
    return spark if spark and len(spark) >= 2 else None


# ---------------------------------------------------------------------------
# Portfolio risk metrics — real Sharpe / Sortino / Max Drawdown
# ---------------------------------------------------------------------------
_risk_cache: dict = {}
_risk_lock = threading.Lock()
RISK_CACHE_FILE = os.path.join(os.path.dirname(__file__), "risk_cache.json")


def _load_risk_cache() -> None:
    global _risk_cache
    try:
        with open(RISK_CACHE_FILE, "r") as f:
            _risk_cache = json.load(f)
    except Exception:
        pass


def _save_risk_cache() -> None:
    try:
        tmp = RISK_CACHE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(_risk_cache, f)
        os.replace(tmp, RISK_CACHE_FILE)
    except Exception:
        pass


def compute_portfolio_risk(holdings) -> None:
    """Compute real weighted-portfolio Sharpe / Sortino / MaxDD + SPY benchmark."""
    global _risk_cache
    import yfinance as yf
    from indicators import sharpe_ratio, sortino_ratio, max_drawdown

    holdings = pf._coerce(holdings)
    if not holdings:
        return
    tickers = [h["ticker"] for h in holdings]

    try:
        raw = yf.download(list(set(tickers + ["SPY"])), period="1y",
                          auto_adjust=True, progress=False, threads=True)
        close = raw["Close"] if "Close" in raw else raw
    except Exception:
        return

    try:
        # Weight each holding by current market value
        prices = batch_prices(tickers)
        weights = {}
        total = 0.0
        for h in holdings:
            px = prices.get(h["ticker"]) or h["avg_cost"]
            val = h["shares"] * px
            weights[h["ticker"]] = weights.get(h["ticker"], 0.0) + val
            total += val
        if total <= 0:
            return

        # Build weighted daily portfolio return series from priceable tickers
        port_ret = None
        used_w = 0.0
        for t, val in weights.items():
            try:
                s = close[t] if t in getattr(close, "columns", []) else None
                if s is None:
                    continue
                s = s.dropna()
                if len(s) < 30:
                    continue
                ret = s.pct_change().dropna()
                w = val / total
                contrib = ret * w
                port_ret = contrib if port_ret is None else port_ret.add(contrib, fill_value=0)
                used_w += w
            except Exception:
                continue

        result = {"sharpe": None, "sortino": None, "maxDrawdown": None,
                  "benchmarkSharpe": None, "coverage": round(used_w * 100, 0)}

        if port_ret is not None and len(port_ret) >= 30:
            # Rescale so partial coverage still reflects per-dollar risk
            if used_w > 0:
                port_ret = port_ret / used_w
            cum = (1 + port_ret).cumprod()
            result["sharpe"] = sharpe_ratio(port_ret)
            result["sortino"] = sortino_ratio(port_ret)
            md = max_drawdown(cum)
            result["maxDrawdown"] = round(md * 100, 1) if md is not None else None

        # SPY benchmark Sharpe
        try:
            spy = (close["SPY"] if "SPY" in getattr(close, "columns", []) else close).dropna()
            spy_ret = spy.pct_change().dropna()
            result["benchmarkSharpe"] = sharpe_ratio(spy_ret)
        except Exception:
            pass

        # Round
        for k in ("sharpe", "sortino", "benchmarkSharpe"):
            if result[k] is not None:
                result[k] = round(result[k], 2)

        with _risk_lock:
            _risk_cache = result
        _save_risk_cache()
    except Exception as e:
        log.debug("compute_portfolio_risk failed: %s", e)
        return


def _risk_metrics() -> dict:
    with _risk_lock:
        return dict(_risk_cache) if _risk_cache else {
            "sharpe": None, "sortino": None, "maxDrawdown": None,
            "benchmarkSharpe": None, "coverage": 0,
        }


# ---------------------------------------------------------------------------
# Account type mapping between UI and accounts.py
# ---------------------------------------------------------------------------
_UI_TO_AC: dict[str, str] = {
    "Taxable": "Other Asset", "Retirement": "IRA Cash", "Cash": "HYSA",
    "Crypto": "Crypto", "Real Estate": "Real Estate", "Debt": "Credit Card",
}
_AC_TO_UI: dict[str, str] = {
    "HYSA": "Cash", "HSA": "Cash", "FSA": "Cash", "Checking": "Cash",
    "Savings": "Cash", "CD": "Cash", "Money Market": "Cash",
    "401k Cash": "Retirement", "IRA Cash": "Retirement",
    "Crypto": "Crypto", "Real Estate": "Real Estate",
    "Vehicle": "Other Asset", "Other Asset": "Other Asset",
    "Credit Card": "Debt", "Student Loan": "Debt", "Mortgage": "Debt",
    "Auto Loan": "Debt", "Personal Loan": "Debt", "Other Liability": "Debt",
}
ACCT_COLORS = {
    "Taxable": "#0066ff", "Retirement": "#00a96e", "Cash": "#ff9f0a",
    "Crypto": "#8b5cf6", "Real Estate": "#e84a4a", "Debt": "#ff453a",
    "Other Asset": "#8e8e93",
}


# Ticker-position "account" tag (from _infer_account) → display card.
_HOLDINGS_CARDS = {
    "401(k)": ("holdings_401k", "Fidelity 401(k)", "Fidelity"),
    "HSA": ("holdings_hsa", "Fidelity HSA", "Fidelity"),
    "Roth IRA": ("holdings_roth", "Webull Roth IRA", "Webull"),
    "Brokerage": ("holdings_brokerage", "Webull Brokerage", "Webull"),
}


def _build_account_list(positions: list, extra_accounts: list) -> list:
    """One synthetic card per ticker-position bucket (401k/HSA/Roth/Brokerage),
    instead of a single lumped total — each bucket may come from a different
    institution and gets updated on its own schedule."""
    today = datetime.date.today().isoformat()
    by_bucket: dict[str, float] = {}
    for p in positions:
        by_bucket[p.get("account", "Brokerage")] = by_bucket.get(p.get("account", "Brokerage"), 0.0) + p["value"]

    accts = []
    for bucket, total in by_bucket.items():
        acct_id, name, institution = _HOLDINGS_CARDS.get(
            bucket, (f"holdings_{bucket.lower()}", bucket, "Mixed")
        )
        accts.append({
            "id": acct_id,
            "name": name,
            "type": "Taxable",
            "balance": total,
            "institution": institution,
            "updated": today,  # auto-priced daily
            "_computed": True,
        })

    for i, a in enumerate(extra_accounts):
        ui_type = _AC_TO_UI.get(a["type"], "Other Asset")
        if ac.is_liability(a["type"]):
            ui_type = "Debt"
        notes = a.get("notes", "")
        institution = notes.split("·")[0].strip() if notes else a["type"]
        accts.append({
            "id": f"extra_{i}",
            "name": a["name"],
            "type": ui_type,
            "balance": a["balance"] if not ac.is_liability(a["type"]) else -abs(a["balance"]),
            "institution": institution,
            "updated": a.get("updated", ""),
        })
    return accts


# ---------------------------------------------------------------------------
# Holdings → account source mapping (from CSV filenames)
# ---------------------------------------------------------------------------
_BUCKET_LABELS = {"hsa": "HSA", "roth": "Roth IRA", "brokerage": "Brokerage"}


def _infer_account(ticker: str, bucket: str, roth_tickers: set, hsa_tickers: set, brokerage_tickers: set) -> str:
    t = (ticker or "").upper()
    # Opaque NON40* plan codes are only ever 401(k) plan-specific fund
    # identifiers — check this before everything else, since 401(k) tickers
    # share brokerage_holdings.csv with real brokerage tickers (no dedicated
    # 401k file) and would otherwise be labeled "Brokerage".
    if t.startswith("NON40"):
        return "401(k)"
    # Each holding row is tagged with its source account by
    # import_holdings.recombine()/apply_snapshot.py — trust that directly
    # rather than re-deriving it, since the same ticker can legitimately
    # exist in two different accounts (e.g. MU in both Roth and Brokerage).
    if bucket in _BUCKET_LABELS:
        return _BUCKET_LABELS[bucket]
    # Fallback ticker-set guessing for rows with no "account" tag — e.g. a
    # CSV uploaded manually through the web UI, which predates this field.
    if t in hsa_tickers:
        return "HSA"
    if t in roth_tickers:
        return "Roth IRA"
    if t in brokerage_tickers:
        return "Brokerage"
    return "Brokerage"


def _load_csv_tickers(path: str) -> set[str]:
    import pandas as pd
    try:
        df = pd.read_csv(path)
        return set(df["ticker"].str.upper().tolist())
    except Exception:
        return set()


# ---------------------------------------------------------------------------
# Core data builder — two-phase: fast (instant) + enriched (background)
# ---------------------------------------------------------------------------
_data_cache: dict = {}
_data_cache_ts: float = 0.0
_DATA_TTL = 300.0  # 5 min
_bg_running = False
_bg_lock = threading.Lock()


def _build_positions_fast(holdings, roth_tickers, hsa_tickers, brokerage_tickers):
    """Build positions using avg_cost as price — instant, no network."""
    positions = []
    total_value = 0.0
    total_cost = 0.0
    for h in holdings:
        # Use cached price if available, else fall back to avg_cost
        price = _pcache.get(h["ticker"]) or h["avg_cost"]
        cost = h["shares"] * h["avg_cost"]
        value = h["shares"] * price
        pl = value - cost
        pl_pct = (pl / cost * 100) if cost else 0.0
        account = _infer_account(h["ticker"], h.get("account", ""), roth_tickers, hsa_tickers, brokerage_tickers)
        positions.append({
            "ticker": h["ticker"],
            "shares": h["shares"],
            "avg_cost": h["avg_cost"],
            "price": price,
            "sector": _sector_cache.get(h["ticker"], "—"),
            "account": account,
            "value": value,
            "cost": cost,
            "pl": pl,
            "plPct": pl_pct,
            "weight": 0.0,
            "periods": _position_periods(h["ticker"], h["shares"], price, h["avg_cost"], pl, pl_pct),
            "spark": _position_spark(h["ticker"]),
        })
        total_value += value
        total_cost += cost
    for p in positions:
        p["weight"] = (p["value"] / total_value * 100) if total_value else 0.0
    positions.sort(key=lambda x: -x["value"])
    return positions, total_value, total_cost


def _placeholder_featured(ticker: str, price: float) -> dict:
    return {
        "ticker": ticker, "name": ticker, "price": round(price, 2),
        "change": 0.0, "changePct": 0.0, "sector": "—", "industry": "—",
        "marketCap": "—", "pe": "—", "peFwd": "—", "beta": "—",
        "high52": "—", "low52": "—", "divYield": 0.0, "annualDiv": 0.0,
        "target": 0.0, "upside": 0.0, "rating": "—", "nextEarnings": "—",
        "signal": "HOLD", "action": "HOLD", "confidence": "low",
        "thesis": "Loading analysis… refresh in a moment.",
        "technical": "", "fundamental": "", "newsSummary": "",
        "risks": [], "catalysts": [],
        "bull_case": "", "bear_case": "", "recommendation": "",
        "news": [],
    }


def build_nexus_data(force: bool = False) -> dict:
    global _data_cache, _data_cache_ts
    now = time.time()
    if not force and _data_cache and now - _data_cache_ts < _DATA_TTL:
        with _bg_lock:  # avoid reading a dict mid-update by the bg thread
            return dict(_data_cache)

    holdings = pf.load_portfolio()
    raw_profile = pr.load_profile()
    extra_accounts = ac.load_accounts()
    wl_items = wl.load_watchlist()

    roth_tickers = _load_csv_tickers(os.path.join(os.path.dirname(__file__), "roth_ira_holdings.csv"))
    hsa_tickers = _load_csv_tickers(os.path.join(os.path.dirname(__file__), "hsa_holdings.csv"))
    brokerage_tickers = _load_csv_tickers(os.path.join(os.path.dirname(__file__), "brokerage_holdings.csv"))

    # Fast positions — no network call
    positions, total_value, total_cost = _build_positions_fast(holdings, roth_tickers, hsa_tickers, brokerage_tickers)

    total_pl = total_value - total_cost
    total_pl_pct = (total_pl / total_cost * 100) if total_cost else 0.0

    acct_list = _build_account_list(positions, extra_accounts)
    net_worth = sum(a["balance"] for a in acct_list if a.get("type") != "Debt")
    nw_history = _net_worth_history(net_worth, total_value, acct_list)

    sector_map: dict[str, float] = {}
    for p in positions:
        s = p["sector"] or "—"
        sector_map[s] = sector_map.get(s, 0.0) + p["weight"]
    sector_weights = [
        {"sector": k, "weight": round(v, 2)}
        for k, v in sorted(sector_map.items(), key=lambda x: -x[1])
    ]

    raw_name = raw_profile.get("name", "")
    name = raw_name or "Alex Chen"
    initials = "".join(w[0].upper() for w in name.split()[:2])
    profile_out = {
        "name": name, "initials": initials,
        "age": raw_profile.get("age", 35),
        "risk": raw_profile.get("risk_tolerance", "moderate").title(),
        "horizon": raw_profile.get("horizon_years", 10),
        "goals": [g.replace("_", " ").title() for g in raw_profile.get("goals", [])],
        "income_stability": raw_profile.get("income_stability", "stable").title(),
        "emergency_fund": raw_profile.get("emergency_fund", True),
        "notes": raw_profile.get("notes", ""),
    }

    wl_out = [
        {
            "ticker": w.get("ticker", ""),
            "price": _pcache.get(w.get("ticker", "")) or 0.0,
            "buyBelow": w.get("buy_below"),
            "sellAbove": w.get("sell_above"),
            "note": w.get("note", ""),
            "change": 0.0,
        }
        for w in wl_items
    ]

    featured_ticker = positions[0]["ticker"] if positions else "AAPL"
    featured_price = positions[0]["price"] if positions else 0.0

    result = {
        "profile": profile_out,
        "positions": positions,
        "accounts": acct_list,
        "portfolioValue": round(total_value, 2),
        "totalCost": round(total_cost, 2),
        "totalPL": round(total_pl, 2),
        "totalPLPct": round(total_pl_pct, 4),
        "netWorth": round(net_worth, 2),
        "netWorthHistory": nw_history,
        "watchlist": wl_out,
        "news": [],
        "featured": _placeholder_featured(featured_ticker, featured_price),
        "featuredHistory": [],
        "sectorWeights": sector_weights,
        "advisorPlan": _advisor_plan(positions, raw_profile),
        "riskMetrics": _risk_metrics(),
        "chatSeed": [],
    }

    _data_cache = result
    _data_cache_ts = now

    # Kick off background enrichment (prices + featured analysis)
    _start_bg_enrichment(holdings, featured_ticker, raw_profile, roth_tickers, hsa_tickers, brokerage_tickers)

    return result


def _start_bg_enrichment(holdings, featured_ticker, raw_profile, roth_tickers, hsa_tickers, brokerage_tickers):
    """Background thread: fetch live prices + featured analysis, then update cache."""
    global _bg_running
    with _bg_lock:
        if _bg_running:
            return
        _bg_running = True

    def _run():
        global _bg_running, _data_cache, _data_cache_ts
        try:
            # 1. Batch prices + period-return history + portfolio risk
            tickers = [h["ticker"] for h in holdings]
            batch_prices(tickers)
            compute_period_prices(tickers)
            compute_portfolio_risk(holdings)

            # 2. Rebuild positions with live prices
            positions, total_value, total_cost = _build_positions_fast(
                holdings, roth_tickers, hsa_tickers, brokerage_tickers
            )
            total_pl = total_value - total_cost
            total_pl_pct = (total_pl / total_cost * 100) if total_cost else 0.0

            extra_accounts = ac.load_accounts()
            acct_list = _build_account_list(positions, extra_accounts)
            net_worth = sum(a["balance"] for a in acct_list if a.get("type") != "Debt")
            nw_history = _net_worth_history(net_worth, total_value, acct_list)

            # 3. Featured ticker — fundamentals + chart history (skip LLM for speed)
            featured_ticker_use = positions[0]["ticker"] if positions else featured_ticker
            try:
                from data import get_fundamentals, get_dividend_info, get_next_earnings
                fund = get_fundamentals(featured_ticker_use)
                price = _pcache.get(featured_ticker_use) or positions[0]["price"] if positions else 0.0
                div = get_dividend_info(featured_ticker_use) or {}
                earnings = get_next_earnings(featured_ticker_use) or {}
                target = fund.get("target_mean_price") or price
                upside = ((target - price) / price * 100) if price else 0.0
                featured = {
                    "ticker": featured_ticker_use,
                    "name": fund.get("name", featured_ticker_use),
                    "price": round(float(price), 2),
                    "change": 0.0, "changePct": 0.0,
                    "sector": fund.get("sector", "—"),
                    "industry": fund.get("industry", "—"),
                    "marketCap": fund.get("market_cap", "—"),
                    "pe": fund.get("pe_trailing") or "—",
                    "peFwd": fund.get("pe_forward") or "—",
                    "beta": fund.get("beta") or "—",
                    "high52": fund.get("fifty_two_week_high") or "—",
                    "low52": fund.get("fifty_two_week_low") or "—",
                    "divYield": round((div.get("div_yield") or 0.0) * 100, 2),
                    "annualDiv": div.get("annual_div") or 0.0,
                    "target": round(float(target), 2),
                    "upside": round(upside, 1),
                    "rating": (fund.get("recommendation") or "Hold").title(),
                    "nextEarnings": earnings.get("next_earnings_date", "N/A"),
                    "signal": "HOLD", "action": "HOLD", "confidence": "medium",
                    "thesis": "Tap 'Analyze' on the Analyze tab for full AI analysis.",
                    "technical": "", "fundamental": "", "newsSummary": "",
                    "risks": [], "catalysts": [],
                    "bull_case": "", "bear_case": "", "recommendation": "",
                    "news": [],
                }
                featured_history = _featured_history(featured_ticker_use)
            except Exception:
                featured = _placeholder_featured(featured_ticker_use, positions[0]["price"] if positions else 0.0)
                featured_history = []

            # 4. Sector weights (with cached sectors)
            _prefetch_sectors(tickers)
            sector_map: dict[str, float] = {}
            for p in positions:
                s = _sector_cache.get(p["ticker"], "—")
                p["sector"] = s
                sector_map[s] = sector_map.get(s, 0.0) + p["weight"]
            sector_weights = [
                {"sector": k, "weight": round(v, 2)}
                for k, v in sorted(sector_map.items(), key=lambda x: -x[1])
            ]

            # Update cache in place
            with _bg_lock:
                if _data_cache:
                    _data_cache.update({
                        "positions": positions,
                        "accounts": acct_list,
                        "portfolioValue": round(total_value, 2),
                        "totalCost": round(total_cost, 2),
                        "totalPL": round(total_pl, 2),
                        "totalPLPct": round(total_pl_pct, 4),
                        "netWorth": round(net_worth, 2),
                        "netWorthHistory": nw_history,
                        "featured": featured,
                        "featuredHistory": featured_history,
                        "sectorWeights": sector_weights,
                        "advisorPlan": _advisor_plan(positions, raw_profile),
                        "riskMetrics": _risk_metrics(),
                    })
                    _data_cache_ts = time.time()
        except Exception as e:
            app.logger.error(f"BG enrichment failed: {e}", exc_info=True)
        finally:
            with _bg_lock:
                _bg_running = False

    threading.Thread(target=_run, daemon=True).start()


# ---------------------------------------------------------------------------
# Featured ticker helpers
# ---------------------------------------------------------------------------

def _build_featured(ticker: str) -> dict:
    try:
        fund = get_fundamentals(ticker)
        price = single_price(ticker) or 0.0
        div = get_dividend_info(ticker) or {}
        earnings = get_next_earnings(ticker) or {}
        df = fetch_data(ticker, period="1y")
        df = add_indicators(df)
        snap = latest_snapshot(df)
        verdict = analyze_ticker(ticker, snap, fund, {}, [], [])
        target = fund.get("target_mean_price") or price
        upside = ((target - price) / price * 100) if price else 0.0

        # Fetch news for this ticker
        try:
            raw_news = company_news(ticker) or []
        except Exception:
            raw_news = []
        news_out = [
            {
                "headline": n.get("headline", ""),
                "source": n.get("source", ""),
                "time": str(n.get("datetime", ""))[:10] or "recent",
                "ticker": ticker,
            }
            for n in raw_news[:6]
        ]

        return {
            "ticker": ticker,
            "name": fund.get("name", ticker),
            "price": round(price, 2),
            "change": 0.0,
            "changePct": 0.0,
            "sector": fund.get("sector", "—"),
            "industry": fund.get("industry", "—"),
            "marketCap": fund.get("market_cap", "—"),
            "pe": fund.get("pe_trailing") or "—",
            "peFwd": fund.get("pe_forward") or "—",
            "beta": fund.get("beta") or "—",
            "high52": fund.get("fifty_two_week_high") or "—",
            "low52": fund.get("fifty_two_week_low") or "—",
            "divYield": round((div.get("div_yield") or 0.0) * 100, 2),
            "annualDiv": div.get("annual_div") or 0.0,
            "target": round(target, 2),
            "upside": round(upside, 1),
            "rating": (fund.get("recommendation") or "Hold").title(),
            "nextEarnings": earnings.get("next_earnings_date", "N/A"),
            "signal": verdict.get("signal", "HOLD"),
            "action": verdict.get("action", "HOLD").upper(),
            "confidence": verdict.get("confidence", "medium"),
            "thesis": verdict.get("thesis", ""),
            "technical": verdict.get("technical_summary", ""),
            "fundamental": verdict.get("fundamental_summary", ""),
            "newsSummary": verdict.get("news_summary", ""),
            "risks": verdict.get("risks", []),
            "catalysts": verdict.get("catalysts", []),
            "bull_case": verdict.get("bull_case", ""),
            "bear_case": verdict.get("bear_case", ""),
            "recommendation": verdict.get("recommendation", ""),
            "news": news_out,
        }
    except Exception as e:
        return {
            "ticker": ticker, "name": ticker, "price": 0.0,
            "change": 0.0, "changePct": 0.0, "sector": "—",
            "industry": "—", "marketCap": "—", "pe": "—", "peFwd": "—",
            "beta": "—", "high52": "—", "low52": "—",
            "divYield": 0.0, "annualDiv": 0.0, "target": 0.0, "upside": 0.0,
            "rating": "—", "nextEarnings": "—",
            "signal": "HOLD", "action": "HOLD", "confidence": "low",
            "thesis": f"Analysis unavailable: {e}",
            "technical": "", "fundamental": "", "newsSummary": "",
            "risks": [], "catalysts": [],
            "bull_case": "", "bear_case": "", "recommendation": "",
            "news": [],
        }


def _featured_history(ticker: str) -> list:
    try:
        df = fetch_data(ticker, period="1y")
        df = add_indicators(df)
        out = []
        for ts, row in df.iterrows():
            sma50 = row.get("SMA50")
            sma200 = row.get("SMA200")
            out.append({
                "date": ts.strftime("%Y-%m-%dT%H:%M:%S"),
                "close": round(float(row["Close"]), 2),
                "sma50": round(float(sma50), 2) if sma50 == sma50 else None,
                "sma200": round(float(sma200), 2) if sma200 == sma200 else None,
            })
        return out
    except Exception:
        return []


def _synthetic_nw_history(current: float, months: int = 24) -> list:
    import datetime
    start = current * 0.42
    out = []
    base = datetime.date(2024, 6, 1)
    for i in range(months):
        t = i / max(months - 1, 1)
        trend = start + (current - start) * (t * t * (3 - 2 * t))
        noise = (math.sin(i * 1.3) + math.sin(i * 0.7)) * 0.018 * trend
        drawdown = (-0.06 if i == 6 else -0.04 if i == 14 else 0.0) * trend
        v = trend + noise + drawdown
        total_months = (base.month - 1 + i)
        d = base.replace(year=base.year + total_months // 12, month=(total_months % 12) + 1)
        out.append({"date": d.isoformat(), "value": round(v)})
    if out:
        out[-1]["value"] = round(current)
    return out


def _net_worth_history(net_worth: float, total_value: float, acct_list: list) -> list:
    """Record this month's snapshot, then return REAL history.

    Falls back to a synthetic seed curve (anchored to today's real net worth)
    only until at least 2 real monthly snapshots have accrued.
    """
    liabilities = sum(abs(a["balance"]) for a in acct_list if a.get("type") == "Debt")
    investments = total_value
    other_assets = net_worth - investments
    try:
        nw_snapshots.record_snapshot(net_worth, investments, other_assets, liabilities)
    except Exception:
        pass

    if nw_snapshots.has_real_history(2):
        return nw_snapshots.load_history()

    # Seed: synthetic ramp behind the single real "now" point so the chart
    # isn't empty on day one. The final point is the real current net worth.
    return _synthetic_nw_history(net_worth, 12)


def _fetch_news(tickers: list[str]) -> list:
    news_out = []
    try:
        for ticker in tickers[:3]:
            for item in (company_news(ticker) or [])[:2]:
                news_out.append({
                    "headline": item.get("headline", ""),
                    "source": item.get("source", ""),
                    "time": item.get("datetime", ""),
                    "ticker": ticker,
                })
    except Exception:
        pass
    return news_out


# Asset-class taxonomy ---------------------------------------------------------
ASSET_CLASSES = ["US Equity", "International", "Bonds", "Real Assets & Crypto", "Cash"]

# Ticker → class overrides (beat the sector-string heuristic)
_CLASS_OVERRIDE = {
    "VXUS": "International", "VEU": "International", "EFA": "International",
    "VWO": "International", "IEFA": "International", "EEM": "International",
    "BND": "Bonds", "AGG": "Bonds", "BNDX": "Bonds", "TLT": "Bonds",
    "SGOV": "Cash", "BIL": "Cash", "SHV": "Cash", "VMFXX": "Cash",
    "GLD": "Real Assets & Crypto", "SLV": "Real Assets & Crypto",
    "FBTC": "Real Assets & Crypto", "IBIT": "Real Assets & Crypto",
    "VNQ": "Real Assets & Crypto", "SCHH": "Real Assets & Crypto",
}

# Representative buy candidates per under-target class
_CLASS_PICK = {
    "International": ("VXUS", "Total ex-US — broadest international exposure at the lowest fee."),
    "Bonds": ("BND", "Total US bond market — your core stability sleeve."),
    "Real Assets & Crypto": ("VNQ", "REIT exposure to round out the real-assets sleeve."),
    "Cash": ("SGOV", "0-3mo T-bills — yield on cash with near-zero duration risk."),
    "US Equity": ("VTI", "Total US market — low-cost broad equity beta."),
}

# Target allocation by risk tolerance (long horizon). Tilted toward cash/bonds
# as horizon shortens (applied below).
_TARGETS = {
    "conservative": {"US Equity": 35, "International": 12, "Bonds": 40, "Real Assets & Crypto": 5, "Cash": 8},
    "moderate":     {"US Equity": 50, "International": 18, "Bonds": 22, "Real Assets & Crypto": 6, "Cash": 4},
    "aggressive":   {"US Equity": 60, "International": 20, "Bonds": 8,  "Real Assets & Crypto": 9, "Cash": 3},
}

_LEVERAGED = {"TQQQ", "UPRO", "SOXL", "TECL", "UDOW", "SPXL", "TNA", "FNGU", "QLD", "SSO"}


def _classify_asset_class(ticker: str, sector: str) -> str:
    t = (ticker or "").upper()
    if t in _CLASS_OVERRIDE:
        return _CLASS_OVERRIDE[t]
    s = (sector or "").lower()
    if any(k in s for k in ("international", "ex-us", "emerging", "developed mkt")):
        return "International"
    if any(k in s for k in ("bond", "fixed income", "treasur", "t-bill", "t-bills")):
        return "Bonds"
    if "cash" in s:
        return "Cash"
    if any(k in s for k in ("crypto", "commodit", "real estate", "reit", "gold", "metals")):
        return "Real Assets & Crypto"
    # Everything else (incl. US ETFs, single US stocks, mutual funds) → US Equity
    return "US Equity"


def _advisor_plan(positions: list, raw_profile: dict) -> dict:
    total = sum(p["value"] for p in positions) or 1.0
    risk = (raw_profile.get("risk_tolerance") or "moderate").lower()
    if risk not in _TARGETS:
        risk = "moderate"
    horizon = int(raw_profile.get("horizon_years", 10) or 10)

    # --- Real current allocation by asset class -------------------------------
    current = {c: 0.0 for c in ASSET_CLASSES}
    for p in positions:
        cls = _classify_asset_class(p["ticker"], p.get("sector"))
        current[cls] += p.get("weight", 0.0)

    # --- Targets, horizon-adjusted -------------------------------------------
    targets = dict(_TARGETS[risk])
    if horizon < 5:
        # Shift 15pts from equities/real-assets into bonds+cash for short horizon
        shift = 15
        take = min(shift, targets["US Equity"] - 20)
        targets["US Equity"] -= take
        targets["Bonds"] += take * 0.6
        targets["Cash"] += take * 0.4
    elif horizon < 10:
        shift = 7
        take = min(shift, targets["US Equity"] - 20)
        targets["US Equity"] -= take
        targets["Bonds"] += take
    # Normalize to 100
    tsum = sum(targets.values()) or 1
    targets = {k: v / tsum * 100 for k, v in targets.items()}

    target_rows = []
    for c in ASSET_CLASSES:
        cur = round(current[c], 1)
        tgt = round(targets[c], 1)
        target_rows.append({"category": c, "target": tgt, "current": cur, "gap": round(tgt - cur, 1)})

    # --- Action items from largest gaps + concentration ----------------------
    actions = []
    held_tickers = {p["ticker"] for p in positions}
    by_gap = sorted(target_rows, key=lambda r: r["gap"], reverse=True)  # most under-target first
    prio = 1
    for row in by_gap:
        if row["gap"] > 3 and prio <= 3:
            pick, why = _CLASS_PICK.get(row["category"], (None, ""))
            if pick:
                verb = "Add to" if pick in held_tickers else "Start"
                actions.append({
                    "priority": prio,
                    "action": "buy",
                    "ticker": pick,
                    "desc": f"{verb} {pick} — {row['category']} is {abs(row['gap']):.0f}pts under target ({row['current']:.0f}% vs {row['target']:.0f}%)",
                    "reason": why,
                })
                prio += 1

    # Concentration trims — any single position > 15%
    for p in sorted(positions, key=lambda x: -x.get("weight", 0)):
        if p.get("weight", 0) > 15 and prio <= 5:
            actions.append({
                "priority": prio,
                "action": "trim",
                "ticker": p["ticker"],
                "desc": f"Trim {p['ticker']} — {p['weight']:.0f}% of portfolio, above the 15% single-name limit",
                "reason": "Reduce idiosyncratic concentration risk; redeploy into under-target classes.",
            })
            prio += 1

    # Leveraged ETF warning as a trim action
    for p in positions:
        if p["ticker"] in _LEVERAGED and prio <= 5:
            actions.append({
                "priority": prio,
                "action": "trim",
                "ticker": p["ticker"],
                "desc": f"Review {p['ticker']} — leveraged ETF, not buy-and-hold",
                "reason": "Daily-reset leverage decays over time; size carefully and rebalance often.",
            })
            prio += 1
            break

    if not actions:
        actions.append({
            "priority": 1, "action": "hold", "ticker": "Portfolio",
            "desc": "Allocation is within ~3pts of every target",
            "reason": "No rebalancing needed right now — review quarterly.",
        })

    # --- Suggested tickers for largest under-target classes ------------------
    suggested = []
    for row in by_gap:
        if row["gap"] > 3:
            pick, why = _CLASS_PICK.get(row["category"], (None, ""))
            if pick:
                suggested.append({
                    "ticker": pick, "category": row["category"],
                    "weight": round(row["target"], 0), "rationale": why,
                })
        if len(suggested) >= 4:
            break

    # --- Risks from real data -------------------------------------------------
    risks = []
    top = sorted(positions, key=lambda x: -x.get("weight", 0))[:5]
    if top:
        risks.append(f"Concentration: top 5 holdings = {sum(p['weight'] for p in top):.0f}% of portfolio")
    biggest_under = min(target_rows, key=lambda r: r["gap"])
    if biggest_under["gap"] < -5:
        risks.append(f"{biggest_under['category']} is {abs(biggest_under['gap']):.0f}pts under target ({biggest_under['current']:.0f}%)")
    lev = [p["ticker"] for p in positions if p["ticker"] in _LEVERAGED]
    if lev:
        risks.append(f"Leveraged ETFs held ({', '.join(lev)}) — path-dependent decay; not buy-and-hold")
    underwater = [p["ticker"] for p in positions if (p.get("plPct") or 0) < -10]
    if underwater:
        risks.append(f"Underwater positions (>10% loss): {', '.join(underwater[:6])} — review for tax-loss harvesting")
    if not risks:
        risks.append("No major allocation or concentration risks detected.")

    # --- Fit summary ----------------------------------------------------------
    top_str = ", ".join(f"{p['ticker']} ({p['weight']:.0f}%)" for p in top[:4])
    worst = min(target_rows, key=lambda r: r["gap"])
    over = max(target_rows, key=lambda r: r["gap"])
    fit = (
        f"Your {len(positions)}-position portfolio is worth ${total:,.0f}. "
        f"Largest holdings: {top_str}. "
        f"For a {risk} profile / {horizon}yr horizon, you're most under-target on "
        f"{worst['category']} ({worst['current']:.0f}% vs {worst['target']:.0f}%) "
        f"and most over on {over['category']} ({over['current']:.0f}% vs {over['target']:.0f}%)."
    )

    return {
        "fit": fit,
        "targets": target_rows,
        "actions": actions,
        "suggested": suggested,
        "risks": risks,
        "rebalance": "Quarterly, or when any class drifts >5% from target.",
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(DESIGN_DIR, "index.html")


@app.route("/data.js")
def data_js():
    """Dynamic data.js — real portfolio data replacing mock data."""
    try:
        data = build_nexus_data()
    except Exception as e:
        app.logger.error(f"build_nexus_data failed: {e}", exc_info=True)
        return send_from_directory(DESIGN_DIR, "data.js")

    js_payload = json.dumps(data, default=str)

    js = f"""// NexusAI — dynamic data from server.py
window.NEXUS_DATA = (function() {{
  const raw = {js_payload};

  // Convert ISO date strings → Date objects
  if (raw.netWorthHistory) {{
    raw.netWorthHistory = raw.netWorthHistory.map(d => ({{...d, date: new Date(d.date)}}));
  }}
  if (raw.featuredHistory) {{
    raw.featuredHistory = raw.featuredHistory.map(d => ({{...d, date: new Date(d.date)}}));
  }}
  if (!raw.chatSeed) raw.chatSeed = [];
  if (!raw.news) raw.news = [];
  if (!raw.watchlist) raw.watchlist = [];

  return raw;
}})();

// Formatting helpers
window.fmt$ = (n, opts = {{}}) => {{
  if (n == null || isNaN(n)) return "—";
  const abs = Math.abs(n);
  if (opts.compact && abs >= 1000000) return (n >= 0 ? "$" : "-$") + (abs/1000000).toFixed(2) + "M";
  if (opts.compact && abs >= 10000)   return (n >= 0 ? "$" : "-$") + (abs/1000).toFixed(1) + "K";
  const sign = n < 0 ? "-" : (opts.signed ? "+" : "");
  return sign + "$" + abs.toLocaleString("en-US", {{minimumFractionDigits: opts.dec ?? 2, maximumFractionDigits: opts.dec ?? 2}});
}};
window.fmtPct = (n, signed = true) => {{
  if (n == null || isNaN(n)) return "—";
  const sign = n > 0 && signed ? "+" : "";
  return sign + n.toFixed(2) + "%";
}};
window.fmtNum = (n, dec = 2) => {{
  if (n == null || isNaN(n)) return "—";
  return n.toLocaleString("en-US", {{minimumFractionDigits: dec, maximumFractionDigits: dec}});
}};
"""
    return Response(js, mimetype="application/javascript")


_TICKER_RE = __import__("re").compile(r"^[A-Z0-9.\-^]{1,12}$")


@app.route("/api/analyze/<ticker>")
def api_analyze(ticker: str):
    ticker = ticker.strip().upper()
    if not _TICKER_RE.match(ticker):
        return jsonify({"ok": False, "error": "Invalid ticker format"}), 400
    try:
        featured = _build_featured(ticker)
        history = _featured_history(ticker)
        return jsonify({"featured": featured, "featuredHistory": history, "ok": True})
    except DataError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


def _chat_context_from_cache():
    """Build (profile, val, plan) for the analyst from CACHED data — no network."""
    raw_profile = pr.load_profile()
    val, plan = None, None
    try:
        data = build_nexus_data()
        plan = data.get("advisorPlan")
        positions = data.get("positions", [])
        val = {
            "positions": [
                {
                    "ticker": p["ticker"],
                    "weight": (p.get("weight") or 0) / 100.0,
                    "unrealized_pct": p.get("plPct"),
                    "sector": p.get("sector"),
                    "value": p.get("value"),
                }
                for p in positions
            ],
            "sector_weights": {
                s["sector"]: (s["weight"] / 100.0) for s in data.get("sectorWeights", [])
            },
            "total_value": data.get("portfolioValue", 0),
            "total_cost": data.get("totalCost", 0),
            "total_unrealized_pct": data.get("totalPLPct"),
            "concentration_flags": [],
        }
    except Exception:
        val, plan = None, None
    return raw_profile, val, plan


@app.route("/api/chat", methods=["POST"])
def api_chat():
    body = request.get_json(force=True) or {}
    message = (body.get("message") or "").strip()[:2000]
    history = body.get("history") or []
    if isinstance(history, list):
        history = history[-20:]
    if not message:
        return jsonify({"reply": ""}), 400

    raw_profile, val, plan = _chat_context_from_cache()
    messages = list(history) + [{"role": "user", "content": message}]
    try:
        result = chat_with_advisor(messages, raw_profile, val, plan)
        reply = result.get("content", "Sorry, I could not generate a response.")
    except Exception as e:
        reply = f"Advisor unavailable: {e}"
    return jsonify({"reply": reply})


@app.route("/api/chat/stream", methods=["POST"])
def api_chat_stream():
    """Server-Sent Events: stream the advisor reply token-by-token."""
    body = request.get_json(force=True) or {}
    message = (body.get("message") or "").strip()[:2000]
    history = body.get("history") or []
    if isinstance(history, list):
        history = history[-20:]
    if not message:
        return jsonify({"reply": ""}), 400

    raw_profile, val, plan = _chat_context_from_cache()
    messages = list(history) + [{"role": "user", "content": message}]

    def _gen():
        try:
            for chunk in stream_chat_reply(messages, raw_profile, val, plan):
                yield f"data: {json.dumps({'delta': chunk})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'delta': f'Advisor unavailable: {e}'})}\n\n"
        yield "data: {\"done\": true}\n\n"

    return Response(_gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/accounts", methods=["POST"])
def api_save_accounts():
    body = request.get_json(force=True) or {}
    accts = body.get("accounts") or []
    # Skip computed brokerage account; save only user-managed ones
    ac_list = []
    for a in accts:
        if a.get("id") in ("brokerage",) or a.get("_computed"):
            continue
        ui_type = a.get("type", "Cash")
        ac_type = _UI_TO_AC.get(ui_type, "Other Asset")
        balance = abs(float(a.get("balance") or 0))
        # Liabilities → use the liability type
        if ui_type == "Debt":
            ac_type = "Credit Card"
        ac_list.append({
            "name": a.get("name", "Account"),
            "type": ac_type,
            "balance": balance,
            "notes": a.get("institution", ""),
            # Stamp today only when the balance changed; else keep prior date
            "updated": a.get("updated") or datetime.date.today().isoformat(),
        })
    ac.save_accounts(ac_list)
    # Invalidate data cache
    global _data_cache_ts
    _data_cache_ts = 0.0
    return jsonify({"ok": True})


def _refresh_after_holdings_change(holdings) -> None:
    """Invalidate caches + warm new tickers in the background after holdings edit."""
    global _data_cache_ts
    _data_cache_ts = 0.0

    def _warm():
        try:
            tickers = [h["ticker"] for h in holdings]
            if tickers:
                batch_prices(tickers)
                compute_period_prices(tickers)
                compute_portfolio_risk(holdings)
                _prefetch_sectors(tickers)
            global _data_cache_ts
            _data_cache_ts = 0.0
            build_nexus_data(force=True)
        except Exception:
            pass
    threading.Thread(target=_warm, daemon=True).start()


@app.route("/api/portfolio", methods=["POST"])
def api_save_portfolio():
    """Save the full holdings list (add/edit/delete from the UI)."""
    body = request.get_json(force=True) or {}
    rows = body.get("holdings") or []
    if not isinstance(rows, list):
        return jsonify({"ok": False, "error": "holdings must be a list"}), 400
    clean = pf.save_portfolio(rows)  # _coerce drops invalid/zero-share rows
    _refresh_after_holdings_change(clean)
    return jsonify({"ok": True, "count": len(clean)})


@app.route("/api/portfolio/import", methods=["POST"])
def api_import_portfolio():
    """Import holdings from an uploaded CSV (columns: ticker, shares, avg_cost).

    Accepts multipart file upload ('file') or raw CSV text in the body.
    """
    MAX_BYTES = 2 * 1024 * 1024  # 2MB cap
    raw = None
    if request.files.get("file"):
        raw = request.files["file"].read(MAX_BYTES + 1)
    elif request.data:
        raw = request.data[:MAX_BYTES + 1]
    if not raw:
        return jsonify({"ok": False, "error": "No CSV provided"}), 400
    if len(raw) > MAX_BYTES:
        return jsonify({"ok": False, "error": "CSV exceeds 2MB limit"}), 400
    try:
        holdings, dropped = pf.from_csv(bytes(raw))
    except Exception as e:
        return jsonify({"ok": False, "error": f"Could not parse CSV: {e}"}), 400
    if not holdings:
        return jsonify({"ok": False, "error": "No valid rows (need ticker, shares, avg_cost)"}), 400
    clean = pf.save_portfolio(holdings)
    _refresh_after_holdings_change(clean)
    return jsonify({"ok": True, "count": len(clean), "dropped": dropped})


@app.route("/api/snapshot-now", methods=["POST"])
def api_snapshot_now():
    """Force-record this month's net-worth snapshot from current data."""
    global _data_cache_ts
    _data_cache_ts = 0.0  # rebuild so latest balances are captured
    try:
        data = build_nexus_data(force=True)
        return jsonify({"ok": True, "value": data["netWorth"],
                        "points": len(data["netWorthHistory"])})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/sync-balances", methods=["GET", "POST"])
def api_sync_balances():
    """Pull real account balances via Plaid (no-op unless Plaid is configured)."""
    import plaid_sync
    result = plaid_sync.pull_balances()
    if result.get("ok"):
        global _data_cache_ts
        _data_cache_ts = 0.0  # force rebuild so new balances + snapshot reflect
    return jsonify(result)


@app.route("/api/watchlist", methods=["POST"])
def api_save_watchlist():
    body = request.get_json(force=True) or {}
    items = body.get("watchlist") or []
    wl_list = [
        {
            "ticker": w.get("ticker", ""),
            "buy_below": w.get("buyBelow"),
            "sell_above": w.get("sellAbove"),
            "note": w.get("note", ""),
        }
        for w in items if w.get("ticker")
    ]
    wl.save_watchlist(wl_list)
    return jsonify({"ok": True})


@app.route("/api/profile", methods=["POST"])
def api_save_profile():
    body = request.get_json(force=True) or {}
    existing = pr.load_profile()
    # Merge incoming fields
    if body.get("name") is not None:
        existing["name"] = str(body["name"]).strip()
    if body.get("risk_tolerance"):
        existing["risk_tolerance"] = str(body["risk_tolerance"]).strip().lower()
    if body.get("horizon_years"):
        try:
            existing["horizon_years"] = int(body["horizon_years"])
        except (TypeError, ValueError):
            pass
    if body.get("age"):
        try:
            existing["age"] = int(body["age"])
        except (TypeError, ValueError):
            pass
    if body.get("notes") is not None:
        existing["notes"] = str(body["notes"]).strip()
    pr.save_profile(existing)
    # Invalidate data cache so next /data.js reflects new name
    global _data_cache_ts
    _data_cache_ts = 0.0
    return jsonify({"ok": True})


@app.route("/api/snapshot")
def api_snapshot():
    """Lightweight enriched data for one-shot frontend refresh (P/L, prices, hero)."""
    try:
        data = build_nexus_data()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({
        "ok": True,
        "positions": data["positions"],
        "portfolioValue": data["portfolioValue"],
        "totalCost": data["totalCost"],
        "totalPL": data["totalPL"],
        "totalPLPct": data["totalPLPct"],
        "netWorth": data["netWorth"],
        "accounts": data["accounts"],
        "watchlist": data["watchlist"],
        "sectorWeights": data["sectorWeights"],
        "advisorPlan": data["advisorPlan"],
        "riskMetrics": data["riskMetrics"],
    })


@app.route("/<path:filename>")
def static_files(filename: str):
    return send_from_directory(DESIGN_DIR, filename)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    print(f"\n  NexusAI →  http://localhost:{port}\n")

    # Load persisted prices + period history + risk; warm cache in background
    _load_price_cache()
    _load_period_cache()
    _load_risk_cache()

    def _warm():
        try:
            holdings = pf.load_portfolio()
            tickers = [h["ticker"] for h in holdings]
            if tickers:
                batch_prices(tickers)
                compute_period_prices(tickers)
                compute_portfolio_risk(holdings)
                _prefetch_sectors(tickers)
                # Force a fresh enriched build so /data.js + /api/snapshot are warm
                global _data_cache_ts
                _data_cache_ts = 0.0
                build_nexus_data(force=True)
        except Exception:
            pass
    threading.Thread(target=_warm, daemon=True).start()

    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
