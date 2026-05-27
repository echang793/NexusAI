"""Market data fetching via yfinance: prices, fundamentals, market context."""

import pandas as pd
import yfinance as yf


class DataError(Exception):
    """Raised when ticker data cannot be fetched."""


def fetch_data(ticker, period="2y", interval="1d"):
    """Fetch daily OHLCV history for a ticker.

    Returns a DataFrame indexed by date with Open/High/Low/Close/Volume.
    Raises DataError if the ticker is invalid or returns no rows.
    """
    symbol = (ticker or "").strip().upper()
    if not symbol:
        raise DataError("No ticker provided.")

    df = yf.download(
        symbol,
        period=period,
        interval=interval,
        auto_adjust=True,
        progress=False,
    )

    if df is None or df.empty:
        raise DataError(f"No data found for '{symbol}'. Check the ticker symbol.")

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    keep = ["Open", "High", "Low", "Close", "Volume"]
    df = df[[c for c in keep if c in df.columns]].copy()
    df.dropna(subset=["Close"], inplace=True)

    if df.empty:
        raise DataError(f"No usable price rows for '{symbol}'.")

    return df


def get_fundamentals(ticker):
    """Fetch a fundamentals snapshot via yfinance .info.

    Returns a dict; values may be None when yfinance lacks the field.
    Never raises — fundamentals are best-effort context.
    """
    symbol = (ticker or "").strip().upper()
    out = {
        "symbol": symbol,
        "name": None,
        "sector": None,
        "industry": None,
        "market_cap": None,
        "pe_trailing": None,
        "pe_forward": None,
        "profit_margin": None,
        "dividend_yield": None,
        "beta": None,
        "fifty_two_week_high": None,
        "fifty_two_week_low": None,
        "target_mean_price": None,
        "recommendation": None,
    }
    if not symbol:
        return out

    try:
        info = yf.Ticker(symbol).info or {}
    except Exception:
        return out

    out.update(
        {
            "name": info.get("longName") or info.get("shortName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "market_cap": info.get("marketCap"),
            "pe_trailing": info.get("trailingPE"),
            "pe_forward": info.get("forwardPE"),
            "profit_margin": info.get("profitMargins"),
            "dividend_yield": info.get("dividendYield"),
            "beta": info.get("beta"),
            "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
            "target_mean_price": info.get("targetMeanPrice"),
            "recommendation": info.get("recommendationKey"),
        }
    )
    return out


def get_dividend_info(ticker):
    """Fetch dividend details: annual rate, yield, last ex-date, frequency.

    Returns a dict. Never raises — best-effort.
    """
    symbol = (ticker or "").strip().upper()
    out = {
        "annual_div": None,
        "div_yield": None,
        "last_ex_date": None,
        "frequency": None,
    }
    if not symbol:
        return out
    try:
        t = yf.Ticker(symbol)
        info = t.info or {}
        out["div_yield"] = info.get("dividendYield")

        divs = t.dividends
        if divs is not None and not divs.empty:
            # Use last 4 payments as annual estimate
            recent = divs.tail(4)
            out["annual_div"] = float(recent.sum())
            last_idx = divs.index[-1]
            out["last_ex_date"] = (
                last_idx.date().isoformat()
                if hasattr(last_idx, "date")
                else str(last_idx)[:10]
            )
            if len(divs) >= 2:
                gap = (divs.index[-1] - divs.index[-2]).days
                if gap < 45:
                    out["frequency"] = "monthly"
                elif gap < 100:
                    out["frequency"] = "quarterly"
                else:
                    out["frequency"] = "semi-annual/annual"
    except Exception:
        pass
    return out


def get_next_earnings(ticker):
    """Fetch next upcoming earnings date.

    Returns {next_earnings_date, days_until} or None. Never raises.
    """
    symbol = (ticker or "").strip().upper()
    if not symbol:
        return None
    try:
        t = yf.Ticker(symbol)
        dates = t.earnings_dates
        if dates is None or dates.empty:
            return None
        today = pd.Timestamp.now(tz=dates.index.tz)
        future = dates[dates.index > today]
        if future.empty:
            return None
        # earnings_dates is sorted descending; last() = furthest future
        next_ts = future.index[-1]
        days_until = (next_ts.date() - today.date()).days
        return {
            "next_earnings_date": next_ts.date().isoformat(),
            "days_until": int(days_until),
        }
    except Exception:
        return None


_SECTOR_ETF = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Healthcare": "XLV",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Basic Materials": "XLB",
    "Communication Services": "XLC",
}


def _pct_change_5d(symbol):
    try:
        h = yf.download(symbol, period="1mo", interval="1d", progress=False, auto_adjust=True)
        if h is None or h.empty:
            return None
        if isinstance(h.columns, pd.MultiIndex):
            h.columns = h.columns.get_level_values(0)
        closes = h["Close"].dropna()
        if len(closes) < 6:
            return None
        return float((closes.iloc[-1] / closes.iloc[-6] - 1.0) * 100.0)
    except Exception:
        return None


def get_market_context(sector=None):
    """Macro/industry proxy: SPY + VIX levels and 5-day moves, plus sector ETF.

    Best-effort; returns a dict. Never raises.
    """
    ctx = {
        "spy_5d_pct": _pct_change_5d("SPY"),
        "vix_level": None,
        "sector": sector,
        "sector_etf": None,
        "sector_5d_pct": None,
    }
    try:
        vix = yf.download("^VIX", period="5d", interval="1d", progress=False)
        if vix is not None and not vix.empty:
            if isinstance(vix.columns, pd.MultiIndex):
                vix.columns = vix.columns.get_level_values(0)
            ctx["vix_level"] = float(vix["Close"].dropna().iloc[-1])
    except Exception:
        pass

    etf = _SECTOR_ETF.get(sector) if sector else None
    if etf:
        ctx["sector_etf"] = etf
        ctx["sector_5d_pct"] = _pct_change_5d(etf)

    return ctx


def latest_price(ticker):
    """Most recent close for a ticker, or None on failure."""
    try:
        df = fetch_data(ticker, period="5d")
        return float(df["Close"].iloc[-1])
    except Exception:
        return None
