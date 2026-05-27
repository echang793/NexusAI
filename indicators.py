"""Technical indicator calculations and portfolio risk metrics."""

import pandas as pd

import config

SMA_FAST = config.SMA_FAST
SMA_SLOW = config.SMA_SLOW
RSI_PERIOD = config.RSI_PERIOD


def sma(series, window):
    """Simple moving average."""
    return series.rolling(window=window, min_periods=window).mean()


def ema(series, span):
    """Exponential moving average."""
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def rsi(series, period=RSI_PERIOD):
    """Relative Strength Index using Wilder's smoothing (0-100)."""
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    out = 100.0 - (100.0 / (1.0 + rs))
    out = out.where(avg_loss != 0, 100.0)
    return out


def macd(series, fast=config.MACD_FAST, slow=config.MACD_SLOW, signal=config.MACD_SIGNAL):
    """MACD line, signal line, histogram. Returns a DataFrame."""
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd_line - signal_line
    return pd.DataFrame(
        {"MACD": macd_line, "MACD_signal": signal_line, "MACD_hist": hist}
    )


def bollinger(series, window=config.BOLLINGER_WINDOW, num_std=config.BOLLINGER_STD):
    """Bollinger bands. Returns a DataFrame with mid/upper/lower."""
    mid = series.rolling(window=window, min_periods=window).mean()
    std = series.rolling(window=window, min_periods=window).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return pd.DataFrame({"BB_mid": mid, "BB_upper": upper, "BB_lower": lower})


def volume_trend(volume, window=config.VOLUME_AVG_WINDOW):
    """Average volume and current-vs-average ratio."""
    avg = volume.rolling(window=window, min_periods=1).mean()
    ratio = volume / avg
    return pd.DataFrame({"Vol_avg": avg, "Vol_ratio": ratio})


def fifty_two_week(df):
    """52-week high/low and where price sits in that range (0-1).

    Uses up to 252 trading days. Returns a dict of latest values.
    """
    window = df["Close"].tail(252)
    if window.empty:
        return {"hi_52w": None, "lo_52w": None, "pct_of_range": None}
    hi = float(window.max())
    lo = float(window.min())
    last = float(window.iloc[-1])
    span = hi - lo
    pct = (last - lo) / span if span > 0 else None
    return {"hi_52w": hi, "lo_52w": lo, "pct_of_range": pct}


def support_resistance(df, lookback=config.SR_LOOKBACK):
    """Naive support/resistance from recent swing low/high.

    Returns a dict with the most recent `lookback`-bar min (support) and
    max (resistance).
    """
    window = df["Close"].tail(lookback)
    if window.empty:
        return {"support": None, "resistance": None}
    return {"support": float(window.min()), "resistance": float(window.max())}


def add_indicators(df):
    """Return a copy of df with the full technical suite added."""
    out = df.copy()
    close = out["Close"]

    out["SMA50"] = sma(close, SMA_FAST)
    out["SMA200"] = sma(close, SMA_SLOW)
    out["RSI"] = rsi(close, RSI_PERIOD)

    out = out.join(macd(close))
    out = out.join(bollinger(close))
    if "Volume" in out.columns:
        out = out.join(volume_trend(out["Volume"]))

    return out


def latest_snapshot(df):
    """Compact dict of the latest indicator values for briefing/serialization."""
    last = df.iloc[-1]

    def val(col):
        if col not in df.columns:
            return None
        v = last[col]
        return None if pd.isna(v) else float(v)

    snap = {
        "close": val("Close"),
        "sma50": val("SMA50"),
        "sma200": val("SMA200"),
        "rsi": val("RSI"),
        "macd": val("MACD"),
        "macd_signal": val("MACD_signal"),
        "macd_hist": val("MACD_hist"),
        "bb_upper": val("BB_upper"),
        "bb_lower": val("BB_lower"),
        "vol_ratio": val("Vol_ratio"),
    }
    snap.update(fifty_two_week(df))
    snap.update(support_resistance(df))
    return snap


# ---------------------------------------------------------------------------
# Portfolio risk metrics
# ---------------------------------------------------------------------------

def sharpe_ratio(returns, risk_free_annual=0.045):
    """Annualized Sharpe ratio from a daily returns Series.

    Returns float or None if insufficient data.
    """
    if returns is None or len(returns) < 10:
        return None
    rf_daily = risk_free_annual / 252
    excess = returns - rf_daily
    std = excess.std()
    if std == 0 or pd.isna(std):
        return None
    return float((excess.mean() / std) * (252 ** 0.5))


def max_drawdown(price_series):
    """Maximum drawdown as a negative decimal (e.g. -0.35 = -35%).

    price_series: pd.Series of prices (not returns).
    Returns float or None.
    """
    if price_series is None or len(price_series) < 2:
        return None
    roll_max = price_series.cummax()
    drawdown = (price_series - roll_max) / roll_max
    val = drawdown.min()
    return float(val) if not pd.isna(val) else None


def sortino_ratio(returns, risk_free_annual=0.045):
    """Annualized Sortino ratio (penalizes downside deviation only).

    Returns float or None if insufficient data.
    """
    if returns is None or len(returns) < 10:
        return None
    rf_daily = risk_free_annual / 252
    excess = returns - rf_daily
    downside = excess[excess < 0]
    if len(downside) < 3:
        return None
    d_std = downside.std()
    if d_std == 0 or pd.isna(d_std):
        return None
    return float((excess.mean() / d_std) * (252 ** 0.5))
