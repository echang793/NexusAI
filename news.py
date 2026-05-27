"""News fetching: Finnhub (preferred) with yfinance fallback."""

import datetime as dt

import config

try:
    import finnhub
except Exception:  # finnhub-python not installed
    finnhub = None

import yfinance as yf


def _normalize(headline, summary, source, ts, url, news_source="unknown"):
    return {
        "headline": (headline or "").strip(),
        "summary": (summary or "").strip(),
        "source": (source or "").strip(),
        "datetime": ts,  # python datetime or None
        "url": (url or "").strip(),
        "news_source": news_source,  # "finnhub" | "yfinance" | "unknown"
    }


def _dedupe(items):
    seen = set()
    out = []
    for it in items:
        key = it["headline"].lower()[:120]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def _finnhub_client():
    if finnhub is None or not config.HAS_FINNHUB:
        return None
    try:
        return finnhub.Client(api_key=config.FINNHUB_API_KEY)
    except Exception:
        return None


def company_news(ticker, days=7, limit=10):
    """Recent company headlines. Finnhub first, yfinance fallback."""
    symbol = (ticker or "").strip().upper()
    if not symbol:
        return []

    client = _finnhub_client()
    if client is not None:
        try:
            today = dt.date.today()
            frm = (today - dt.timedelta(days=days)).isoformat()
            to = today.isoformat()
            raw = client.company_news(symbol, _from=frm, to=to) or []
            items = [
                _normalize(
                    r.get("headline"),
                    r.get("summary"),
                    r.get("source"),
                    dt.datetime.fromtimestamp(r["datetime"]) if r.get("datetime") else None,
                    r.get("url"),
                    news_source="finnhub",
                )
                for r in raw
            ]
            items = _dedupe(items)
            if items:
                items.sort(key=lambda x: x["datetime"] or dt.datetime.min, reverse=True)
                return items[:limit]
        except Exception:
            pass  # fall through to yfinance

    return _yf_news(symbol, limit)


def _yf_news(symbol, limit=10):
    try:
        raw = yf.Ticker(symbol).news or []
    except Exception:
        return []

    items = []
    for r in raw:
        # yfinance news shape changed across versions; handle both.
        content = r.get("content", r)
        headline = content.get("title") or r.get("title")
        summary = content.get("summary") or content.get("description") or ""
        provider = content.get("provider") or {}
        source = provider.get("displayName") if isinstance(provider, dict) else r.get("publisher")
        url = ""
        cu = content.get("canonicalUrl") or content.get("clickThroughUrl")
        if isinstance(cu, dict):
            url = cu.get("url", "")
        url = url or r.get("link", "")
        ts = None
        pubdate = content.get("pubDate") or r.get("providerPublishTime")
        if isinstance(pubdate, (int, float)):
            ts = dt.datetime.fromtimestamp(pubdate)
        elif isinstance(pubdate, str):
            try:
                ts = dt.datetime.fromisoformat(pubdate.replace("Z", "+00:00"))
            except Exception:
                ts = None
        items.append(_normalize(headline, summary, source, ts, url, news_source="yfinance"))

    return _dedupe(items)[:limit]


def market_news(limit=8):
    """General market/economy headlines. Finnhub only (empty if no key)."""
    client = _finnhub_client()
    if client is None:
        return []
    try:
        raw = client.general_news("general") or []
        items = [
            _normalize(
                r.get("headline"),
                r.get("summary"),
                r.get("source"),
                dt.datetime.fromtimestamp(r["datetime"]) if r.get("datetime") else None,
                r.get("url"),
                news_source="finnhub",
            )
            for r in raw
        ]
        items = _dedupe(items)
        items.sort(key=lambda x: x["datetime"] or dt.datetime.min, reverse=True)
        return items[:limit]
    except Exception:
        return []
