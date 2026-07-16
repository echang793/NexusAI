"""AI financial advisor: Ollama (free/local) with Anthropic fallback, then rule-based."""

import json
import urllib.error
import urllib.request

import config
from advisory import get_advice, technical_score

try:
    import anthropic as _anthropic_sdk
except Exception:
    _anthropic_sdk = None


SYSTEM_PROMPT = (
    "You are a seasoned sell-side equity analyst writing for a retail investor. "
    "You weigh technical signals, fundamentals, and recent news together into a "
    "single, decisive verdict. You are direct and concrete: cite the specific "
    "indicator values, fundamental metrics, and headlines that drive your view. "
    "You never give generic boilerplate. When position context is provided "
    "(shares, cost basis, unrealized P/L), you advise specifically on whether to "
    "hold, trim part of the position, or sell it fully — and you factor the "
    "investor's gain/loss and concentration risk into that call. Profit-taking on "
    "large gains and cutting losers on deteriorating technicals are both valid. "
    "When a BUY action is suggested for a new position, briefly note whether to "
    "buy all at once or dollar-cost average across tranches and why. "
    "You are not a fiduciary and your output is educational, not personalized "
    "financial advice. For every ticker analysis include a bull case, a bear case, "
    "and a final recommendation summarizing your view. "
    "Always respond with valid JSON only — no markdown, no prose outside JSON."
)

_TICKER_SCHEMA = {
    "type": "object",
    "properties": {
        "signal": {"type": "string", "enum": ["BUY", "SELL", "HOLD"]},
        "action": {"type": "string", "enum": ["buy", "hold", "trim_partial", "sell_full"]},
        "trim_pct": {"type": "integer"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "thesis": {"type": "string"},
        "technical_summary": {"type": "string"},
        "fundamental_summary": {"type": "string"},
        "news_summary": {"type": "string"},
        "risks": {"type": "array", "items": {"type": "string"}},
        "catalysts": {"type": "array", "items": {"type": "string"}},
        "bull_case": {"type": "string"},
        "bear_case": {"type": "string"},
        "recommendation": {"type": "string"},
    },
    "required": [
        "signal", "action", "trim_pct", "confidence", "thesis",
        "technical_summary", "fundamental_summary", "news_summary",
        "risks", "catalysts", "bull_case", "bear_case", "recommendation",
    ],
}

_PORTFOLIO_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "pl_comment": {"type": "string"},
        "concentration_flags": {"type": "array", "items": {"type": "string"}},
        "rebalancing": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "pl_comment", "concentration_flags", "rebalancing"],
}

_TICKER_PROMPT = (
    "Return a JSON object with exactly these fields: "
    "signal (BUY/SELL/HOLD), action (buy/hold/trim_partial/sell_full), "
    "trim_pct (integer 0-99, non-zero only when action=trim_partial), "
    "confidence (low/medium/high), thesis (2-4 sentence verdict including DCA guidance if BUY), "
    "technical_summary (string), fundamental_summary (string), "
    "news_summary (string), risks (array of strings), catalysts (array of strings), "
    "bull_case (2-3 upside drivers as one string), "
    "bear_case (2-3 downside risks as one string), "
    "recommendation (1-2 sentence final call). "
    "No other text — only the JSON object."
)

_PORTFOLIO_PROMPT = (
    "Return a JSON object with exactly these fields: "
    "summary (2-4 sentence portfolio overview), "
    "pl_comment (comment on total unrealized P/L), "
    "concentration_flags (array of strings), "
    "rebalancing (array of concrete rebalancing suggestions). "
    "No other text — only the JSON object."
)

_REQUIRED_TICKER_FIELDS = {
    "signal": "HOLD",
    "action": "hold",
    "trim_pct": 0,
    "confidence": "low",
    "thesis": "",
    "technical_summary": "",
    "fundamental_summary": "",
    "news_summary": "",
    "risks": [],
    "catalysts": [],
    "bull_case": "",
    "bear_case": "",
    "recommendation": "",
}

_REQUIRED_PORTFOLIO_FIELDS = {
    "summary": "",
    "pl_comment": "",
    "concentration_flags": [],
    "rebalancing": [],
}


def _coerce_output(raw, required_fields):
    """Fill missing required fields with defaults; return coerced dict."""
    out = dict(raw) if isinstance(raw, dict) else {}
    for k, default in required_fields.items():
        if k not in out or out[k] is None:
            out[k] = default
    return out


# ---------------------------------------------------------------------------
# Ollama backend
# ---------------------------------------------------------------------------

def _ollama_chat(messages, schema):
    """Call Ollama /api/chat with JSON format. Returns parsed dict or raises."""
    payload = {
        "model": config.OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "format": schema,
        "options": {"temperature": 0.3},
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{config.OLLAMA_HOST}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read())
    except urllib.error.URLError as e:
        reason = str(e).lower()
        if "connection refused" in reason or "errno 61" in reason or "urlopen error" in reason:
            raise ConnectionError(
                "Ollama not running. Start it with: `ollama serve`"
            ) from e
        raise

    content = body["message"]["content"]
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Try to extract JSON object from response if surrounded by text
        import re
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
        raise ValueError(f"Ollama returned non-JSON content: {content[:300]}")


def _call_ollama_ticker(briefing):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": briefing + "\n\n" + _TICKER_PROMPT},
    ]
    raw = _ollama_chat(messages, _TICKER_SCHEMA)
    return _coerce_output(raw, _REQUIRED_TICKER_FIELDS)


def _call_ollama_portfolio(briefing):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": briefing + "\n\n" + _PORTFOLIO_PROMPT},
    ]
    raw = _ollama_chat(messages, _PORTFOLIO_SCHEMA)
    return _coerce_output(raw, _REQUIRED_PORTFOLIO_FIELDS)


# ---------------------------------------------------------------------------
# Anthropic backend (cloud, paid — optional fallback)
# ---------------------------------------------------------------------------

_TICKER_TOOL = {
    "name": "submit_verdict",
    "description": "Return the structured investment verdict for a single ticker.",
    "strict": True,
    "input_schema": {**_TICKER_SCHEMA, "additionalProperties": False},
}

_PORTFOLIO_TOOL = {
    "name": "submit_portfolio_verdict",
    "description": "Return the structured portfolio-level assessment.",
    "strict": True,
    "input_schema": {**_PORTFOLIO_SCHEMA, "additionalProperties": False},
}


def _anthropic_client():
    if _anthropic_sdk is None or not config.HAS_ANTHROPIC:
        return None
    try:
        return _anthropic_sdk.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    except Exception:
        return None


def _call_anthropic_tool(client, tool, briefing, system_prompt=None, required_fields=None):
    """Call Anthropic with forced tool-use. Defaults to ticker prompt + fields."""
    sys_text = system_prompt or SYSTEM_PROMPT
    req_fields = required_fields if required_fields is not None else _REQUIRED_TICKER_FIELDS
    resp = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=config.LLM_MAX_TOKENS,
        system=[
            {
                "type": "text",
                "text": sys_text,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[tool],
        tool_choice={"type": "tool", "name": tool["name"]},
        messages=[{"role": "user", "content": briefing}],
    )
    for block in resp.content:
        if block.type == "tool_use":
            return _coerce_output(dict(block.input), req_fields)
    raise RuntimeError("Model did not return a tool_use block.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_advice_from_snapshot(snapshot):
    """Run deterministic rule on snapshot dict; return (signal, reason)."""
    import pandas as pd
    row = pd.DataFrame([{
        "SMA50": snapshot.get("sma50"),
        "SMA200": snapshot.get("sma200"),
        "RSI": snapshot.get("rsi"),
        "MACD_hist": snapshot.get("macd_hist"),
    }])
    signal, reason = get_advice(row)
    snapshot["_score"] = technical_score(row)
    return signal, reason


def _trim_news(items, n=6):
    out = []
    for it in (items or [])[:n]:
        out.append({
            "headline": it.get("headline"),
            "summary": (it.get("summary") or "")[:300],
            "source": it.get("source"),
        })
    return out


def _fallback_ticker(ticker, snapshot, position, tech_signal, tech_reason):
    action = "hold"
    signal = tech_signal if tech_signal in ("BUY", "SELL", "HOLD") else "HOLD"
    gain_pct = position.get("unrealized_pct") if position else None

    if position:
        if signal == "SELL":
            if gain_pct is not None and gain_pct >= config.TRIM_GAIN_THRESHOLD * 100:
                action = "trim_partial"
            else:
                action = "sell_full"
        elif signal == "BUY":
            action = "buy"
        else:
            action = "hold"
    else:
        action = {"BUY": "buy", "SELL": "sell_full", "HOLD": "hold"}.get(signal, "hold")

    trim_pct = config.TRIM_DEFAULT_PCT if action == "trim_partial" else 0
    thesis = f"Rule-based signal: {tech_reason}"
    if position and gain_pct is not None:
        thesis += f" Position is {gain_pct:+.1f}% vs cost."

    # Rule-based risks + catalysts from snapshot indicators
    snap = snapshot or {}
    rsi = snap.get("RSI")
    sma50 = snap.get("SMA50")
    sma200 = snap.get("SMA200")
    macd = snap.get("MACD")
    macd_sig = snap.get("MACD_signal")

    risks: list[str] = []
    catalysts: list[str] = []

    def _valid(v):
        return v is not None and v == v  # not NaN

    if _valid(rsi):
        if rsi > 70:
            risks.append(f"RSI overbought at {rsi:.1f} — momentum may be exhausted, pullback risk")
        elif rsi > 60:
            risks.append(f"RSI at {rsi:.1f} — approaching overbought territory")
        elif rsi < 30:
            catalysts.append(f"RSI oversold at {rsi:.1f} — historically strong mean-reversion setup")
        elif rsi < 45:
            catalysts.append(f"RSI at {rsi:.1f} — not extended, technical room to run")

    if _valid(sma50) and _valid(sma200):
        if sma50 > sma200:
            catalysts.append(
                f"Golden cross: SMA50 ${sma50:.2f} above SMA200 ${sma200:.2f} — bullish trend intact"
            )
        else:
            risks.append(
                f"Death cross: SMA50 ${sma50:.2f} below SMA200 ${sma200:.2f} — bearish trend structure"
            )

    if _valid(macd) and _valid(macd_sig):
        if macd > macd_sig:
            catalysts.append("MACD above signal line — positive momentum crossover")
        else:
            risks.append("MACD below signal line — weakening momentum")

    # Bull / bear case summaries
    bull_case = (
        "; ".join(catalysts)
        if catalysts
        else "No strong bullish technical signals identified at this time"
    )
    bear_case = (
        "; ".join(risks)
        if risks
        else "No strong bearish technical signals identified at this time"
    )
    recommendation = (
        f"{signal} — {tech_reason} "
        f"Confidence: low (rule-based only, no LLM configured). "
        f"{'Consider reducing position size given gain.' if gain_pct and gain_pct > 25 else ''}"
    ).strip()

    return {
        "signal": signal,
        "action": action,
        "trim_pct": trim_pct,
        "confidence": "low",
        "thesis": thesis,
        "technical_summary": tech_reason,
        "fundamental_summary": "Fundamentals not analyzed (no LLM configured).",
        "news_summary": "News not analyzed (no LLM configured).",
        "risks": risks,
        "catalysts": catalysts,
        "bull_case": bull_case,
        "bear_case": bear_case,
        "recommendation": recommendation,
        "source": "fallback",
    }


def _fallback_portfolio(valuation):
    from portfolio import _fallback_rebalancing
    pct = valuation.get("total_unrealized_pct")
    pl = f"{pct:+.1f}%" if pct is not None else "n/a"
    return {
        "summary": "Rule-based portfolio view (no LLM configured).",
        "pl_comment": f"Total unrealized P/L: {pl}.",
        "concentration_flags": valuation.get("concentration_flags", []),
        "rebalancing": _fallback_rebalancing(valuation),
        "source": "fallback",
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_ticker(
    ticker,
    snapshot,
    fundamentals,
    market_ctx,
    company_news,
    macro_news,
    position=None,
    dividend_info=None,
    earnings_info=None,
):
    """Produce structured verdict for one ticker. Falls back to rule-based if no LLM."""
    tech_signal, tech_reason = get_advice_from_snapshot(snapshot)

    briefing = json.dumps(
        {
            "ticker": ticker,
            "technical_indicators": snapshot,
            "rule_based_signal": {"signal": tech_signal, "reason": tech_reason},
            "fundamentals": fundamentals,
            "dividend_info": dividend_info,
            "next_earnings": earnings_info,
            "market_context": market_ctx,
            "company_news": _trim_news(company_news),
            "macro_news": _trim_news(macro_news),
            "position": position,
        },
        default=str,
    )

    err = ""

    # 1. Try Ollama (free, local)
    if config.LLM_BACKEND == "ollama":
        try:
            out = _call_ollama_ticker(briefing)
            out.setdefault("trim_pct", 0)
            out["source"] = "ollama"
            return out
        except ConnectionError as e:
            # Ollama offline — surface message, fall through
            err = str(e) + " Using rule-based fallback."
        except Exception as e:
            err = f"Ollama failed ({type(e).__name__}: {e}); "

    # 2. Try Anthropic (paid cloud, optional)
    client = _anthropic_client()
    if client:
        try:
            out = _call_anthropic_tool(client, _TICKER_TOOL, briefing)
            out["source"] = "llm"
            return out
        except Exception as e:
            err += f"Anthropic failed ({e}); "

    # 3. Rule-based fallback
    out = _fallback_ticker(ticker, snapshot, position, tech_signal, tech_reason)
    if err:
        out["error"] = err + (" Used rule-based fallback." if "fallback" not in err else "")
    return out


def analyze_portfolio(valuation, per_position):
    """Produce portfolio-level assessment."""
    briefing = json.dumps(
        {
            "totals": {
                "total_value": valuation.get("total_value"),
                "total_cost": valuation.get("total_cost"),
                "total_unrealized": valuation.get("total_unrealized"),
                "total_unrealized_pct": valuation.get("total_unrealized_pct"),
            },
            "positions": [
                {
                    "ticker": p["ticker"],
                    "weight": p.get("weight"),
                    "unrealized_pct": p.get("unrealized_pct"),
                    "sector": p.get("sector"),
                }
                for p in valuation.get("positions", [])
            ],
            "sector_weights": valuation.get("sector_weights"),
            "concentration_flags": valuation.get("concentration_flags"),
            "per_position_verdicts": [
                {
                    "ticker": x["ticker"],
                    "action": x["verdict"].get("action"),
                    "signal": x["verdict"].get("signal"),
                }
                for x in per_position
            ],
        },
        default=str,
    )

    err = ""

    # 1. Try Ollama
    if config.LLM_BACKEND == "ollama":
        try:
            out = _call_ollama_portfolio(briefing)
            out["source"] = "ollama"
            return out
        except ConnectionError as e:
            err = str(e) + " Using rule-based fallback."
        except Exception as e:
            err = f"Ollama failed ({type(e).__name__}: {e}); "

    # 2. Try Anthropic
    client = _anthropic_client()
    if client:
        try:
            out = _call_anthropic_tool(
                client, _PORTFOLIO_TOOL, briefing,
                required_fields=_REQUIRED_PORTFOLIO_FIELDS,
            )
            out["source"] = "llm"
            return out
        except Exception as e:
            err += f"Anthropic failed ({e}); "

    # 3. Fallback
    out = _fallback_portfolio(valuation)
    if err:
        out["error"] = err
    return out


# ===========================================================================
# Personalized Portfolio Advisor
# ===========================================================================

_ADVISOR_SCHEMA = {
    "type": "object",
    "properties": {
        "fit_assessment": {"type": "string"},
        "target_allocation": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "target_pct": {"type": "number"},
                    "rationale": {"type": "string"},
                },
                "required": ["category", "target_pct", "rationale"],
            },
        },
        "current_vs_target": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "current_pct": {"type": "number"},
                    "target_pct": {"type": "number"},
                    "gap_pct": {"type": "number"},
                    "action": {"type": "string"},
                },
                "required": ["category", "current_pct", "target_pct", "gap_pct", "action"],
            },
        },
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "priority": {"type": "integer"},
                    "action": {"type": "string"},
                    "ticker": {"type": "string"},
                    "amount_desc": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["priority", "action", "ticker", "amount_desc", "reason"],
            },
        },
        "suggested_tickers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "category": {"type": "string"},
                    "rationale": {"type": "string"},
                    "target_weight_pct": {"type": "number"},
                },
                "required": ["ticker", "category", "rationale", "target_weight_pct"],
            },
        },
        "risks_to_watch": {"type": "array", "items": {"type": "string"}},
        "rebalance_frequency": {"type": "string"},
    },
    "required": [
        "fit_assessment", "target_allocation", "current_vs_target",
        "action_items", "suggested_tickers", "risks_to_watch", "rebalance_frequency",
    ],
}

_REQUIRED_ADVISOR_FIELDS = {
    "fit_assessment": "",
    "target_allocation": [],
    "current_vs_target": [],
    "action_items": [],
    "suggested_tickers": [],
    "risks_to_watch": [],
    "rebalance_frequency": "Quarterly",
}

_ADVISOR_SYSTEM_PROMPT = (
    "You are a Certified Financial Planner (CFP)-style advisor for a retail investor. "
    "You take their full profile (risk tolerance, time horizon, goals, age, income stability, "
    "emergency fund status) and current holdings, then build a personalized portfolio plan. "
    "You map profile to appropriate asset allocation across US equities, international equities, "
    "bonds, and cash/defensive. You recommend specific tickers from a universe of broad ETFs "
    "(VTI, VXUS, BND, VIG, SCHD, VNQ, sector ETFs like XLK/XLV/XLF) and established blue-chip "
    "stocks (AAPL, MSFT, JNJ, KO, PG, V, JPM, etc.) to fill allocation gaps. "
    "You prefer incremental changes over nuke-and-replace — work with the investor's existing "
    "holdings where possible. You factor in concentration risk, sequence-of-returns risk for "
    "those near retirement, and tax efficiency. Be direct, concrete, and cite specific numbers. "
    "You are not a fiduciary; this is educational. "
    "Always respond with valid JSON only — no markdown, no prose outside JSON."
)

_ADVISOR_PROMPT = (
    "Return a JSON object with EXACTLY these fields: "
    "fit_assessment (2-4 sentence narrative on whether current portfolio matches the profile, "
    "named risks, what's working). "
    "target_allocation (array of {category, target_pct, rationale} — categories MUST be "
    "'US Equities', 'International Equities', 'Bonds', 'Cash/Defensive' and target_pct values "
    "must sum to ~100). "
    "current_vs_target (array of {category, current_pct, target_pct, gap_pct, action} where "
    "action is 'increase'/'reduce'/'on target'). "
    "action_items (ordered array of {priority (integer starting at 1), "
    "action ('sell'/'trim'/'buy'/'hold'/'add_new'), ticker (use '—' for category-level), "
    "amount_desc (e.g. 'Trim 30%' or 'Allocate ~$2,000'), reason}). "
    "suggested_tickers (array of {ticker, category, rationale, target_weight_pct} — "
    "pick from ETFs and blue-chip stocks to fill gaps). "
    "risks_to_watch (array of strings — concentration, sequence risk, etc.). "
    "rebalance_frequency (string like 'Quarterly' or 'When any category drifts >5%'). "
    "No other text — only the JSON object."
)

_ADVISOR_TOOL = {
    "name": "submit_advisor_plan",
    "description": "Return the structured personalized portfolio plan.",
    "strict": True,
    "input_schema": {**_ADVISOR_SCHEMA, "additionalProperties": False},
}


# Rule-based allocation matrix: (risk, horizon_bucket) -> (us, intl, bonds, cash)
# Buckets: short (<5 years), mid (5-15), long (>15)
_ALLOCATION_MATRIX = {
    ("conservative", "short"): (30, 5, 55, 10),
    ("conservative", "mid"):   (40, 10, 40, 10),
    ("conservative", "long"):  (50, 10, 35, 5),
    ("moderate",     "short"): (45, 10, 35, 10),
    ("moderate",     "mid"):   (55, 15, 25, 5),
    ("moderate",     "long"):  (65, 20, 12, 3),
    ("aggressive",   "short"): (60, 15, 20, 5),
    ("aggressive",   "mid"):   (70, 20, 8, 2),
    ("aggressive",   "long"):  (80, 15, 3, 2),
}

_DEFAULT_TICKERS = {
    "US Equities": [
        {"ticker": "VTI", "rationale": "Total US stock market ETF — broad diversification, low fee."},
        {"ticker": "VIG", "rationale": "Dividend-growth ETF — quality companies with growing payouts."},
    ],
    "International Equities": [
        {"ticker": "VXUS", "rationale": "Total international stock ETF — global diversification."},
    ],
    "Bonds": [
        {"ticker": "BND", "rationale": "Total US bond market ETF — stability + income."},
    ],
    "Cash/Defensive": [
        {"ticker": "SGOV", "rationale": "Short-term Treasury ETF — yield + safety."},
    ],
}

# Ticker → asset class mapping for current-portfolio categorization
_BOND_TICKERS = {"BND", "AGG", "TLT", "IEF", "SHY", "LQD", "HYG", "MUB", "TIP", "BNDX", "VCSH", "VCIT"}
_CASH_TICKERS = {"SGOV", "BIL", "VMFXX", "SHV", "USFR"}
_INTL_TICKERS = {"VXUS", "VEA", "VWO", "EFA", "EEM", "IEFA", "IEMG", "ACWI", "IXUS", "SCHF"}


def _horizon_bucket(years):
    if years is None:
        return "mid"
    if years < 5:
        return "short"
    if years <= 15:
        return "mid"
    return "long"


def _categorize_current(valuation):
    """Map current holdings into rough asset-class buckets by weight pct."""
    buckets = {
        "US Equities": 0.0,
        "International Equities": 0.0,
        "Bonds": 0.0,
        "Cash/Defensive": 0.0,
    }
    if not valuation:
        return buckets
    total = valuation.get("total_value") or 0
    if total == 0:
        return buckets

    for p in valuation.get("positions", []):
        ticker = (p.get("ticker") or "").upper()
        weight_pct = (p.get("weight") or 0) * 100
        if ticker in _BOND_TICKERS:
            buckets["Bonds"] += weight_pct
        elif ticker in _CASH_TICKERS:
            buckets["Cash/Defensive"] += weight_pct
        elif ticker in _INTL_TICKERS:
            buckets["International Equities"] += weight_pct
        else:
            buckets["US Equities"] += weight_pct

    return buckets


def _build_advisor_briefing(profile, valuation, per_position_verdicts):
    """Construct the briefing dict for the advisor LLM call."""
    positions_summary = []
    for p in (valuation.get("positions", []) if valuation else []):
        positions_summary.append({
            "ticker": p.get("ticker"),
            "weight_pct": round((p.get("weight") or 0) * 100, 2),
            "unrealized_pct": p.get("unrealized_pct"),
            "sector": p.get("sector"),
            "value": p.get("value"),
        })

    sector_weights = {
        sec: round(w * 100, 2)
        for sec, w in ((valuation or {}).get("sector_weights") or {}).items()
    }

    current_buckets = _categorize_current(valuation)

    return {
        "profile": profile,
        "current_asset_class_buckets_pct": {k: round(v, 1) for k, v in current_buckets.items()},
        "totals": {
            "total_value": (valuation or {}).get("total_value", 0),
            "total_cost": (valuation or {}).get("total_cost", 0),
            "total_unrealized_pct": (valuation or {}).get("total_unrealized_pct"),
        },
        "positions": positions_summary,
        "sector_weights_pct": sector_weights,
        "concentration_flags": (valuation or {}).get("concentration_flags", []),
        "per_position_signals": [
            {
                "ticker": x["ticker"],
                "signal": x["verdict"].get("signal"),
                "action": x["verdict"].get("action"),
            }
            for x in (per_position_verdicts or [])
        ],
    }


def build_portfolio_plan(profile, valuation, per_position_verdicts=None):
    """Produce a personalized portfolio plan from profile + current holdings.

    Falls back to rule-based allocation if no LLM configured.
    """
    briefing = json.dumps(
        _build_advisor_briefing(profile, valuation, per_position_verdicts),
        default=str,
    )
    err = ""

    # 1. Try Ollama
    if config.LLM_BACKEND == "ollama":
        try:
            messages = [
                {"role": "system", "content": _ADVISOR_SYSTEM_PROMPT},
                {"role": "user", "content": briefing + "\n\n" + _ADVISOR_PROMPT},
            ]
            raw = _ollama_chat(messages, _ADVISOR_SCHEMA)
            out = _coerce_output(raw, _REQUIRED_ADVISOR_FIELDS)
            out["source"] = "ollama"
            return out
        except ConnectionError as e:
            err = str(e) + " Using rule-based fallback."
        except Exception as e:
            err = f"Ollama failed ({type(e).__name__}: {e}); "

    # 2. Try Anthropic
    client = _anthropic_client()
    if client:
        try:
            out = _call_anthropic_tool(
                client, _ADVISOR_TOOL, briefing,
                system_prompt=_ADVISOR_SYSTEM_PROMPT,
                required_fields=_REQUIRED_ADVISOR_FIELDS,
            )
            out["source"] = "llm"
            return out
        except Exception as e:
            err += f"Anthropic failed ({e}); "

    # 3. Rule-based fallback
    out = _fallback_advisor(profile, valuation)
    if err:
        out["error"] = err
    return out


def _fallback_advisor(profile, valuation):
    """Rule-based portfolio plan when no LLM is available."""
    risk = profile.get("risk_tolerance", "moderate")
    horizon = profile.get("horizon_years", 10)
    bucket = _horizon_bucket(horizon)

    target = _ALLOCATION_MATRIX.get((risk, bucket), _ALLOCATION_MATRIX[("moderate", "mid")])
    us, intl, bonds, cash = target

    target_allocation = [
        {"category": "US Equities", "target_pct": us,
         "rationale": f"{risk.title()} risk + {bucket} horizon supports {us}% in US equities."},
        {"category": "International Equities", "target_pct": intl,
         "rationale": f"{intl}% international for global diversification."},
        {"category": "Bonds", "target_pct": bonds,
         "rationale": f"{bonds}% bonds for stability and income."},
        {"category": "Cash/Defensive", "target_pct": cash,
         "rationale": f"{cash}% cash/short-term Treasuries as buffer."},
    ]

    current_buckets = _categorize_current(valuation)
    current_vs_target = []
    for item in target_allocation:
        cat = item["category"]
        cur = current_buckets.get(cat, 0)
        tgt = item["target_pct"]
        gap = round(cur - tgt, 1)
        if abs(gap) < 5:
            action = "on target"
        elif gap < 0:
            action = "increase"
        else:
            action = "reduce"
        current_vs_target.append({
            "category": cat,
            "current_pct": round(cur, 1),
            "target_pct": tgt,
            "gap_pct": gap,
            "action": action,
        })

    # Suggested tickers — fill the biggest gaps
    suggested = []
    for cvt in current_vs_target:
        if cvt["action"] == "increase":
            cat = cvt["category"]
            for t in _DEFAULT_TICKERS.get(cat, []):
                suggested.append({
                    "ticker": t["ticker"],
                    "category": cat,
                    "rationale": t["rationale"],
                    "target_weight_pct": round(abs(cvt["gap_pct"]), 1),
                })
                break  # one per category

    # Action items
    action_items = []
    priority = 1
    for cvt in current_vs_target:
        if cvt["action"] == "increase":
            cat = cvt["category"]
            tickers = _DEFAULT_TICKERS.get(cat, [])
            if tickers:
                action_items.append({
                    "priority": priority,
                    "action": "add_new",
                    "ticker": tickers[0]["ticker"],
                    "amount_desc": f"Allocate ~{abs(cvt['gap_pct']):.0f}% of portfolio",
                    "reason": f"{cat} is {abs(cvt['gap_pct']):.0f}% below target.",
                })
                priority += 1
        elif cvt["action"] == "reduce":
            action_items.append({
                "priority": priority,
                "action": "trim",
                "ticker": "—",
                "amount_desc": f"Trim {cvt['category']} exposure by ~{cvt['gap_pct']:.0f}%",
                "reason": f"{cvt['category']} is {cvt['gap_pct']:.0f}% above target.",
            })
            priority += 1

    if not action_items:
        action_items.append({
            "priority": 1,
            "action": "hold",
            "ticker": "—",
            "amount_desc": "Hold current positions",
            "reason": "Allocation is within 5% of target across all categories.",
        })

    # Risks
    risks = []
    flags = (valuation or {}).get("concentration_flags", [])
    risks.extend(flags[:3])
    if horizon < 5 and risk == "aggressive":
        risks.append("Short horizon + aggressive risk = sequence-of-returns risk. Consider de-risking soon.")
    if not profile.get("emergency_fund", True):
        risks.append("No emergency fund flagged — build 3-6 months of cash before adding risk.")
    if profile.get("income_stability") == "uncertain":
        risks.append("Income marked uncertain — keep larger cash buffer than allocation suggests.")
    if not risks:
        risks.append("No major risks flagged from current allocation.")

    fit = (
        f"Rule-based assessment for {risk} risk / {horizon}yr horizon. "
        f"Target mix: {us}/{intl}/{bonds}/{cash} (US/Intl/Bonds/Cash). "
        f"Configure an LLM for nuanced narrative analysis."
    )

    return {
        "fit_assessment": fit,
        "target_allocation": target_allocation,
        "current_vs_target": current_vs_target,
        "action_items": action_items,
        "suggested_tickers": suggested,
        "risks_to_watch": risks,
        "rebalance_frequency": "Quarterly, or when any category drifts >5% from target.",
        "source": "fallback",
    }


# ---------------------------------------------------------------------------
# Conversational chat (free-form, no JSON schema)
# ---------------------------------------------------------------------------

_CHAT_SYSTEM_PROMPT = (
    "You are the user's personal financial advisor in a follow-up conversation. "
    "You already produced a portfolio plan (see CONTEXT below). The user now wants "
    "to discuss, question, or challenge that plan.\n\n"
    "Rules:\n"
    "1. Be direct and concrete. Cite specific tickers, weights, and percentages from CONTEXT.\n"
    "2. Reference the prior plan when relevant ('In my plan I recommended trimming VOO because...').\n"
    "3. If the user challenges a recommendation, defend it with reasoning OR concede if their "
    "counter-argument has merit. Do not be sycophantic. Do not flip on every push-back — only "
    "if their logic is sound (e.g. they have a tax constraint, a near-term cash need, or a "
    "valid contrarian view).\n"
    "4. Frame trade ideas as 'consider' or 'you might' — never give imperative buy/sell orders.\n"
    "5. Stay within investing/personal-finance scope. If asked unrelated questions, briefly "
    "redirect.\n"
    "6. Keep replies under 250 words unless the question demands more detail.\n"
    "7. You are educational, not a fiduciary. Do not promise returns.\n"
    "8. Respond in plain prose — no JSON, no excessive markdown."
)


def _ollama_chat_text(messages, max_tokens=600):
    """Call Ollama /api/chat without JSON-format constraint. Returns plain text."""
    payload = {
        "model": config.OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.4, "num_predict": max_tokens},
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{config.OLLAMA_HOST}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = json.loads(resp.read())
    except urllib.error.URLError as e:
        reason = str(e).lower()
        if "connection refused" in reason or "errno 61" in reason or "urlopen error" in reason:
            raise ConnectionError(
                "Ollama not running. Start it with: `ollama serve`"
            ) from e
        raise
    return (body.get("message") or {}).get("content", "").strip()


def _summarize_plan_for_chat(plan):
    """Produce compact text summary of advisor plan for chat system prompt."""
    if not plan:
        return "No prior plan generated yet."
    parts = [f"Fit assessment: {plan.get('fit_assessment', '(none)')}"]

    targets = plan.get("target_allocation") or []
    if targets:
        tline = ", ".join(
            f"{t.get('category', '?')} {t.get('target_pct', 0)}%" for t in targets
        )
        parts.append(f"Target allocation: {tline}")

    cvt = plan.get("current_vs_target") or []
    if cvt:
        gaps = []
        for c in cvt:
            gap = c.get("gap_pct", 0)
            gaps.append(
                f"{c.get('category', '?')}: current {c.get('current_pct', 0)}% "
                f"vs target {c.get('target_pct', 0)}% (gap {gap:+}%)"
            )
        parts.append("Current vs target:\n  - " + "\n  - ".join(gaps))

    actions = (plan.get("action_items") or [])[:5]
    if actions:
        alines = []
        for a in actions:
            alines.append(
                f"#{a.get('priority', '?')} {a.get('action', '?')} "
                f"{a.get('ticker', '')}: {a.get('amount_desc', '')} "
                f"— {a.get('reason', '')}"
            )
        parts.append("Top action items:\n  - " + "\n  - ".join(alines))

    suggested = (plan.get("suggested_tickers") or [])[:5]
    if suggested:
        slines = [
            f"{s.get('ticker', '?')} ({s.get('category', '?')}, "
            f"target {s.get('target_weight_pct', 0)}%): {s.get('rationale', '')}"
            for s in suggested
        ]
        parts.append("Suggested tickers:\n  - " + "\n  - ".join(slines))

    risks = plan.get("risks_to_watch") or []
    if risks:
        parts.append("Risks to watch: " + "; ".join(risks))

    parts.append(f"Rebalance frequency: {plan.get('rebalance_frequency', '(unspecified)')}")
    return "\n\n".join(parts)


def _build_chat_context(profile, valuation, plan):
    """Compact context block prepended to chat system prompt."""
    briefing = _build_advisor_briefing(profile, valuation, None)
    # Drop the verbose per_position_signals (empty here) and trim positions list
    briefing.pop("per_position_signals", None)
    positions = briefing.get("positions") or []
    # Keep only top 15 positions by weight to control tokens
    positions_sorted = sorted(positions, key=lambda x: x.get("weight_pct") or 0, reverse=True)
    briefing["positions"] = positions_sorted[:15]
    if len(positions) > 15:
        briefing["positions_note"] = f"(showing top 15 of {len(positions)} holdings by weight)"

    context = "=== CONTEXT ===\n"
    context += "PROFILE + PORTFOLIO SNAPSHOT:\n"
    context += json.dumps(briefing, indent=2, default=str)
    context += "\n\nPRIOR ADVISOR PLAN:\n"
    context += _summarize_plan_for_chat(plan)
    context += "\n=== END CONTEXT ==="
    return context


def _trim_chat_history(messages, max_turns=10):
    """Keep last `max_turns` user/assistant messages (system prompt handled separately)."""
    user_assist = [m for m in messages if m.get("role") in ("user", "assistant")]
    return user_assist[-max_turns:]


def chat_with_advisor(messages, profile, valuation, plan):
    """Carry on a free-form conversation about the portfolio plan.

    Args:
        messages: list of {role: "user"|"assistant", content: str} — full chat history.
        profile: investor profile dict.
        valuation: pf.value_portfolio() result (or None).
        plan: build_portfolio_plan() result (or None).

    Returns:
        dict {role: "assistant", content: str, source: "ollama"|"anthropic"|"error"}.
    """
    context = _build_chat_context(profile, valuation, plan)
    system_text = _CHAT_SYSTEM_PROMPT + "\n\n" + context
    trimmed = _trim_chat_history(messages, max_turns=10)

    # 1. Try Ollama
    if config.LLM_BACKEND == "ollama":
        try:
            ollama_msgs = [{"role": "system", "content": system_text}] + trimmed
            reply = _ollama_chat_text(ollama_msgs, max_tokens=600)
            if reply:
                return {"role": "assistant", "content": reply, "source": "ollama"}
        except ConnectionError as e:
            err_msg = str(e)
        except Exception as e:
            err_msg = f"Ollama failed ({type(e).__name__}: {e})"
    else:
        err_msg = "Ollama backend disabled."

    # 2. Try Anthropic
    client = _anthropic_client()
    if client is not None:
        try:
            resp = client.messages.create(
                model=config.ANTHROPIC_MODEL,
                max_tokens=800,
                system=[
                    {
                        "type": "text",
                        "text": system_text,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=trimmed,
            )
            parts = []
            for block in resp.content:
                if getattr(block, "type", None) == "text":
                    parts.append(block.text)
            text = "\n".join(parts).strip()
            if text:
                return {"role": "assistant", "content": text, "source": "anthropic"}
        except Exception as e:
            err_msg += f" / Anthropic failed ({type(e).__name__}: {e})"

    # 3. No LLM available
    return {
        "role": "assistant",
        "content": f"⚠️ Unable to reach an LLM right now. {err_msg}",
        "source": "error",
    }


def stream_chat_reply(messages, profile, valuation, plan):
    """Generator yielding reply text chunks as they're produced.

    Streams from Ollama token-by-token. On any failure, falls back to the
    non-streaming chat_with_advisor() and yields its full reply as one chunk.
    """
    context = _build_chat_context(profile, valuation, plan)
    system_text = _CHAT_SYSTEM_PROMPT + "\n\n" + context
    trimmed = _trim_chat_history(messages, max_turns=10)

    if config.LLM_BACKEND == "ollama":
        payload = {
            "model": config.OLLAMA_MODEL,
            "messages": [{"role": "system", "content": system_text}] + trimmed,
            "stream": True,
            "options": {"temperature": 0.4, "num_predict": 600},
        }
        req = urllib.request.Request(
            f"{config.OLLAMA_HOST}/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        got_any = False
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                for line in resp:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    chunk = (obj.get("message") or {}).get("content", "")
                    if chunk:
                        got_any = True
                        yield chunk
                    if obj.get("done"):
                        break
            if got_any:
                return
        except Exception:
            if got_any:
                return  # partial stream already sent; don't double up

    # Fallback: non-streaming path (Anthropic / rule-based / error)
    result = chat_with_advisor(messages, profile, valuation, plan)
    yield result.get("content", "Sorry, I could not generate a response.")
