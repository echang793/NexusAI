"""Central configuration: API keys, model, weights, thresholds."""

import os

try:
    from dotenv import load_dotenv

    load_dotenv()  # load .env from cwd if present
except Exception:  # python-dotenv not installed — env vars still work
    pass


# --- API keys --------------------------------------------------------------
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "").strip()

HAS_ANTHROPIC = bool(ANTHROPIC_API_KEY)
HAS_FINNHUB = bool(FINNHUB_API_KEY)


# --- LLM -------------------------------------------------------------------
# Anthropic cloud (paid)
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6").strip()
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2000"))

# Ollama local (free)
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").strip()
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b").strip()  # recommended: llama3.1:8b

# Which LLM backend to use: "ollama" or "anthropic"
# Ollama takes priority if configured, then Anthropic, then rule-based fallback.
LLM_BACKEND = os.getenv("LLM_BACKEND", "ollama").strip()  # default: free local

HAS_OLLAMA = LLM_BACKEND == "ollama"  # always try ollama if backend set


# --- Indicator params ------------------------------------------------------
SMA_FAST = 50
SMA_SLOW = 200
RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
BOLLINGER_WINDOW = 20
BOLLINGER_STD = 2.0
VOLUME_AVG_WINDOW = 20
SR_LOOKBACK = 60  # bars for support/resistance


# --- Advisory thresholds ---------------------------------------------------
RSI_BUY_BELOW = 45.0
RSI_SELL_ABOVE = 70.0


# --- Portfolio -------------------------------------------------------------
PORTFOLIO_FILE = os.getenv("PORTFOLIO_FILE", "portfolio.json")
# Flag a position if it exceeds this share of total portfolio value.
CONCENTRATION_THRESHOLD = float(os.getenv("CONCENTRATION_THRESHOLD", "0.25"))

# Rule-based fallback trim suggestion when overbought with a large gain.
TRIM_GAIN_THRESHOLD = 0.25  # +25% unrealized
TRIM_DEFAULT_PCT = 25  # trim 25% of the position


# --- Caching ---------------------------------------------------------------
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "900"))  # 15 min
