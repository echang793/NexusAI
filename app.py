"""Stock Picker & AI Financial Advisor dashboard (Streamlit)."""

from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import streamlit as st

import config
from analyst import analyze_portfolio, analyze_ticker, build_portfolio_plan, chat_with_advisor
from data import (
    DataError,
    fetch_data,
    get_dividend_info,
    get_fundamentals,
    get_market_context,
    get_next_earnings,
    latest_price,
)
from indicators import (
    add_indicators,
    latest_snapshot,
    max_drawdown,
    sharpe_ratio,
    sortino_ratio,
)
from news import company_news, market_news
import accounts as ac
import portfolio as pf
import profile as pr
import watchlist as wl

st.set_page_config(
    page_title="Stock Picker & AI Advisor",
    page_icon=":chart_with_upwards_trend:",
    layout="wide",
)

PERIOD_CHOICES = {"1 Year": "1y", "2 Years": "2y", "5 Years": "5y", "Max": "max"}

SIGNAL_BANNER = {"BUY": st.success, "SELL": st.error, "HOLD": st.warning}
ACTION_LABEL = {
    "buy": "BUY",
    "hold": "HOLD",
    "trim_partial": "TRIM POSITION",
    "sell_full": "SELL FULL POSITION",
    "sell": "SELL",
}
TTL = config.CACHE_TTL_SECONDS

ACTION_COLORS = {
    "sell": "🔴",
    "trim": "🟠",
    "buy": "🟢",
    "add_new": "🟢",
    "hold": "⚪",
}


# --- Cached data layer -----------------------------------------------------
@st.cache_data(ttl=TTL, show_spinner=False)
def load_priced(ticker, period):
    df = fetch_data(ticker, period=period)
    return add_indicators(df)


@st.cache_data(ttl=TTL, show_spinner=False)
def load_fundamentals(ticker):
    return get_fundamentals(ticker)


@st.cache_data(ttl=TTL, show_spinner=False)
def load_dividend_info(ticker):
    return get_dividend_info(ticker)


@st.cache_data(ttl=TTL, show_spinner=False)
def load_next_earnings(ticker):
    return get_next_earnings(ticker)


@st.cache_data(ttl=TTL, show_spinner=False)
def load_market(sector):
    return get_market_context(sector)


@st.cache_data(ttl=TTL, show_spinner=False)
def load_company_news(ticker):
    return company_news(ticker)


@st.cache_data(ttl=TTL, show_spinner=False)
def load_macro_news():
    return market_news()


@st.cache_data(ttl=TTL, show_spinner=False)
def load_verdict(ticker, period, position=None):
    df = load_priced(ticker, period)
    snap = latest_snapshot(df)
    fund = load_fundamentals(ticker)
    ctx = load_market(fund.get("sector"))
    cnews = load_company_news(ticker)
    mnews = load_macro_news()
    div_info = load_dividend_info(ticker)
    earnings_info = load_next_earnings(ticker)
    verdict = analyze_ticker(
        ticker, snap, fund, ctx, cnews, mnews,
        position=position,
        dividend_info=div_info,
        earnings_info=earnings_info,
    )
    return df, snap, fund, ctx, cnews, mnews, verdict


# --- Sidebar ---------------------------------------------------------------
st.sidebar.title("Stock Picker")
ticker = st.sidebar.text_input("Ticker symbol", value="AAPL").strip().upper()
period_label = st.sidebar.selectbox("History", list(PERIOD_CHOICES.keys()), index=1)
period = PERIOD_CHOICES[period_label]

st.sidebar.divider()
if config.LLM_BACKEND == "ollama":
    _llm_label = f"ON — Ollama ({config.OLLAMA_MODEL})"
elif config.HAS_ANTHROPIC:
    _llm_label = f"ON — Claude ({config.ANTHROPIC_MODEL})"
else:
    _llm_label = "OFF (rule-based)"
st.sidebar.caption(
    f"LLM advisor: {_llm_label}\n\n"
    f"News API: {'Finnhub' if config.HAS_FINNHUB else 'yfinance only'}"
)
st.sidebar.caption(
    "Base rules — BUY: SMA50>SMA200 & RSI<45 · SELL: SMA50<SMA200 or RSI>70 · else HOLD"
)

# Profile chip
st.sidebar.divider()
_profile_state = pr.load_profile()
st.sidebar.caption(f"**Profile**: {pr.profile_summary(_profile_state)}  \nEdit in Advisor tab.")


# --- UI helpers ------------------------------------------------------------
def banner(verdict, title):
    sig = verdict.get("signal", "HOLD")
    fn = SIGNAL_BANNER.get(sig, st.info)
    action = ACTION_LABEL.get(verdict.get("action"), verdict.get("action", ""))
    conf = verdict.get("confidence", "")
    trim = verdict.get("trim_pct") or 0
    src = verdict.get("source", "")

    head = f"### {title}: {action} ({sig})"
    if verdict.get("action") == "trim_partial" and trim:
        head += f" — {trim}%"
    if conf:
        head += f"  ·  confidence: {conf}"
    if src == "ollama":
        head += "  ·  🦙 Ollama"

    fn(head + "\n\n" + verdict.get("thesis", ""))
    if src == "fallback":
        st.caption("Rule-based fallback (no LLM configured or LLM call failed).")
    if verdict.get("error"):
        st.caption(f"⚠️ {verdict['error']}")


def render_charts(df):
    c1, c2, c3, c4 = st.columns(4)
    last = df.iloc[-1]
    prev = df["Close"].iloc[-2] if len(df) > 1 else last["Close"]
    chg = (last["Close"] - prev) / prev * 100 if prev else 0.0
    c1.metric("Last Close", f"${last['Close']:.2f}", f"{chg:+.2f}%")
    c2.metric("SMA 50", "n/a" if pd.isna(last.get("SMA50")) else f"${last['SMA50']:.2f}")
    c3.metric("SMA 200", "n/a" if pd.isna(last.get("SMA200")) else f"${last['SMA200']:.2f}")
    c4.metric("RSI (14)", "n/a" if pd.isna(last.get("RSI")) else f"{last['RSI']:.1f}")

    st.subheader("Price, Moving Averages & Bollinger Bands")
    cols = [c for c in ["Close", "SMA50", "SMA200", "BB_upper", "BB_lower"] if c in df]
    st.line_chart(df[cols])

    cc1, cc2 = st.columns(2)
    with cc1:
        st.subheader("MACD")
        mcols = [c for c in ["MACD", "MACD_signal"] if c in df]
        if mcols:
            st.line_chart(df[mcols])
    with cc2:
        st.subheader("RSI (14)")
        rsi_df = df[["RSI"]].copy()
        rsi_df["Oversold (45)"] = config.RSI_BUY_BELOW
        rsi_df["Overbought (70)"] = config.RSI_SELL_ABOVE
        st.line_chart(rsi_df)

    st.subheader("Volume")
    if "Volume" in df:
        st.bar_chart(df["Volume"])


def render_fundamentals(fund, div_info=None, earnings_info=None):
    rows = [
        ("Name", fund.get("name")),
        ("Sector", fund.get("sector")),
        ("Industry", fund.get("industry")),
        ("Market Cap", fund.get("market_cap")),
        ("P/E (trailing)", fund.get("pe_trailing")),
        ("P/E (forward)", fund.get("pe_forward")),
        ("Profit Margin", fund.get("profit_margin")),
        ("Beta", fund.get("beta")),
        ("52w High", fund.get("fifty_two_week_high")),
        ("52w Low", fund.get("fifty_two_week_low")),
        ("Analyst Target", fund.get("target_mean_price")),
        ("Street Rating", fund.get("recommendation")),
    ]

    # Dividend info
    if div_info:
        yield_val = div_info.get("div_yield")
        annual_div = div_info.get("annual_div")
        last_ex = div_info.get("last_ex_date")
        freq = div_info.get("frequency")
        if yield_val or annual_div:
            yield_str = f"{yield_val * 100:.2f}%" if yield_val else "n/a"
            annual_str = f"${annual_div:.2f}/yr" if annual_div else "n/a"
            rows.append(("Dividend Yield", yield_str))
            rows.append(("Annual Dividend", annual_str))
            if last_ex:
                rows.append(("Last Ex-Div Date", last_ex))
            if freq:
                rows.append(("Div Frequency", freq))

    # Earnings info
    if earnings_info:
        next_date = earnings_info.get("next_earnings_date")
        days = earnings_info.get("days_until")
        if next_date:
            days_str = f" ({days}d away)" if days is not None else ""
            rows.append(("Next Earnings", f"{next_date}{days_str}"))

    table = pd.DataFrame(
        [(k, "n/a" if v is None else v) for k, v in rows],
        columns=["Metric", "Value"],
    )
    st.dataframe(table, hide_index=True, width="stretch")


def render_news(items, empty_msg):
    if not items:
        st.caption(empty_msg)
        return
    # Detect if any items fell back to yfinance
    sources = {it.get("news_source", "") for it in items}
    if "yfinance" in sources and "finnhub" not in sources:
        st.caption("⚠️ Using yfinance news (Finnhub unavailable or returned no results)")
    for it in items:
        when = it.get("datetime")
        when_s = when.strftime("%Y-%m-%d") if hasattr(when, "strftime") else ""
        head = it.get("headline") or "(no title)"
        url = it.get("url")
        src = it.get("source") or ""
        line = f"- {'[' + head + '](' + url + ')' if url else head}"
        meta = " · ".join([x for x in [src, when_s] if x])
        if meta:
            line += f"  \n  _{meta}_"
        st.markdown(line)


def _parallel_verdicts(positions, period_str, progress_label="Analyzing"):
    """Run per-position verdicts in parallel. Returns dict {ticker: verdict_tuple}."""
    n = len(positions)
    if n == 0:
        return {}

    def _one(pos):
        pos_ctx = {
            "shares": pos["shares"],
            "avg_cost": pos["avg_cost"],
            "price": pos["price"],
            "unrealized": pos["unrealized"],
            "unrealized_pct": pos["unrealized_pct"],
            "weight": pos["weight"],
        }
        return pos["ticker"], load_verdict(pos["ticker"], period_str, position=pos_ctx)

    prog = st.progress(0, text=f"{progress_label} 0/{n}...")
    results = {}
    with ThreadPoolExecutor(max_workers=min(6, n)) as pool:
        fut_map = {pool.submit(_one, p): p["ticker"] for p in positions}
        done = 0
        for fut in as_completed(fut_map):
            done += 1
            prog.progress(done / n, text=f"{progress_label} {done}/{n}...")
            try:
                t_key, result = fut.result()
                results[t_key] = result
            except Exception as e:
                t_key = fut_map[fut]
                st.warning(f"{t_key}: analysis failed ({e})")
    prog.empty()
    return results


# --- Main ------------------------------------------------------------------
st.title("Stock Picker & AI Financial Advisor")

tab_analyze, tab_portfolio, tab_networth, tab_watchlist, tab_advisor = st.tabs(
    ["Analyze", "Portfolio", "Net Worth", "Watchlist", "Advisor"]
)

# ===========================================================================
# ANALYZE TAB
# ===========================================================================
with tab_analyze:
    if not ticker:
        st.info("Enter a ticker in the sidebar.")
    else:
        try:
            with st.spinner(f"Analyzing {ticker}..."):
                df, snap, fund, ctx, cnews, mnews, verdict = load_verdict(ticker, period)
                div_info = load_dividend_info(ticker)
                earnings_info = load_next_earnings(ticker)
        except DataError as e:
            st.error(
                f"Ticker `{ticker}` not found. {e}  \n"
                "Check spelling or try the full exchange symbol (e.g. `BRK-B`)."
            )
            st.stop()
        except Exception as e:
            err_msg = str(e)
            if "ollama not running" in err_msg.lower() or "connection refused" in err_msg.lower():
                st.error("⚠️ Ollama not running. Start it with: `ollama serve`")
            else:
                st.error(f"Failed to analyze {ticker}: {e}")
            st.stop()

        banner(verdict, ticker)

        rc1, rc2 = st.columns(2)
        with rc1:
            if verdict.get("risks"):
                st.markdown("**Risks**")
                for r in verdict["risks"]:
                    st.markdown(f"- {r}")
        with rc2:
            if verdict.get("catalysts"):
                st.markdown("**Catalysts**")
                for c in verdict["catalysts"]:
                    st.markdown(f"- {c}")

        if verdict.get("source") in ("llm", "ollama"):
            with st.expander("Analyst breakdown", expanded=True):
                st.markdown(f"**Technical:** {verdict.get('technical_summary', '')}")
                st.markdown(f"**Fundamental:** {verdict.get('fundamental_summary', '')}")
                st.markdown(f"**News:** {verdict.get('news_summary', '')}")

        render_charts(df)

        fcol, ncol = st.columns(2)
        with fcol:
            st.subheader("Fundamentals")
            render_fundamentals(fund, div_info=div_info, earnings_info=earnings_info)
        with ncol:
            st.subheader("Company News")
            render_news(cnews, "No company news available.")
            st.subheader("Market / Economy News")
            render_news(mnews, "Set FINNHUB_API_KEY for market news.")

        # Watchlist expander
        with st.expander("🔖 Add / Update Watchlist"):
            _wl_items = wl.load_watchlist()
            _existing = next((i for i in _wl_items if i["ticker"] == ticker), None)
            wl_c1, wl_c2 = st.columns(2)
            with wl_c1:
                _buy_val = float(_existing["buy_below"] or 0) if _existing and _existing.get("buy_below") else 0.0
                buy_below_in = st.number_input(
                    "Buy below ($) — 0 = no alert",
                    min_value=0.0, step=1.0,
                    value=_buy_val, key="wl_buy",
                )
            with wl_c2:
                _sell_val = float(_existing["sell_above"] or 0) if _existing and _existing.get("sell_above") else 0.0
                sell_above_in = st.number_input(
                    "Sell above ($) — 0 = no alert",
                    min_value=0.0, step=1.0,
                    value=_sell_val, key="wl_sell",
                )
            note_in = st.text_input(
                "Note (optional)",
                value=_existing.get("note", "") if _existing else "",
                key="wl_note",
            )
            if st.button("Save to Watchlist", key="wl_save"):
                _wl_items = [i for i in _wl_items if i["ticker"] != ticker]
                _wl_items.append({
                    "ticker": ticker,
                    "buy_below": buy_below_in if buy_below_in > 0 else None,
                    "sell_above": sell_above_in if sell_above_in > 0 else None,
                    "note": note_in,
                })
                wl.save_watchlist(_wl_items)
                st.success(f"**{ticker}** saved to watchlist.")

        with st.expander("Recent price data"):
            st.dataframe(df.tail(20).iloc[::-1])


# ===========================================================================
# PORTFOLIO TAB
# ===========================================================================
with tab_portfolio:
    st.subheader("Your Holdings")
    st.caption("Edit the table, then Save. Or import a CSV with columns: ticker, shares, avg_cost.")

    if "holdings" not in st.session_state:
        st.session_state.holdings = pf.load_portfolio()

    up = st.file_uploader("Import holdings CSV", type=["csv"], key="csv_up")
    if up is not None:
        try:
            imported, dropped = pf.from_csv(up.getvalue())
            st.session_state.holdings = imported
            msg = f"Imported {len(imported)} holdings."
            if dropped:
                msg += f" ⚠️ {dropped} row(s) skipped (invalid ticker/shares/cost)."
            st.success(msg)
        except Exception as e:
            st.error(f"CSV import failed: {e}")

    base = pd.DataFrame(st.session_state.holdings, columns=pf.COLUMNS)
    if base.empty:
        base = pd.DataFrame([{"ticker": "", "shares": 0.0, "avg_cost": 0.0}])

    edited = st.data_editor(
        base,
        num_rows="dynamic",
        width="stretch",
        key="holdings_editor",
        column_config={
            "ticker": st.column_config.TextColumn("Ticker"),
            "shares": st.column_config.NumberColumn("Shares", min_value=0.0, step=1.0),
            "avg_cost": st.column_config.NumberColumn("Avg Cost", min_value=0.0, format="$%.2f"),
        },
    )

    bcol1, bcol2, _ = st.columns([1, 1, 2])
    with bcol1:
        if st.button("Save holdings", type="primary"):
            st.session_state.holdings = pf.save_portfolio(edited.to_dict("records"))
            st.success("Saved to portfolio.json")
    with bcol2:
        st.download_button(
            "Export CSV",
            data=pf.to_csv(edited.to_dict("records")),
            file_name="portfolio.csv",
            mime="text/csv",
        )

    holdings = pf._coerce(edited.to_dict("records"))

    if not holdings:
        st.info("Add at least one holding (ticker, shares, avg cost) to get advice.")
    else:
        if st.button("Analyze portfolio"):
            with st.spinner("Valuing positions..."):
                val = pf.value_portfolio(holdings)

            # --- Summary metrics ---
            m1, m2, m3 = st.columns(3)
            m1.metric("Total Value", f"${val['total_value']:,.2f}")
            m2.metric("Total Cost", f"${val['total_cost']:,.2f}")
            tp = val["total_unrealized_pct"]
            m3.metric(
                "Unrealized P/L",
                f"${val['total_unrealized']:,.2f}",
                None if tp is None else f"{tp:+.1f}%",
            )

            table = pd.DataFrame([
                {
                    "Ticker": p["ticker"],
                    "Shares": p["shares"],
                    "Avg Cost": p["avg_cost"],
                    "Price": p["price"],
                    "Value": p["value"],
                    "Weight %": None if p["weight"] is None else round(p["weight"] * 100, 1),
                    "Unreal. $": p["unrealized"],
                    "Unreal. %": None if p["unrealized_pct"] is None else round(p["unrealized_pct"], 1),
                    "Sector": p.get("sector"),
                }
                for p in val["positions"]
            ])
            st.dataframe(table, hide_index=True, width="stretch")

            # --- Risk Metrics ---
            st.subheader("Risk Metrics")
            risk_rows = []
            all_returns = {}
            for p in val["positions"]:
                try:
                    df_p = load_priced(p["ticker"], period)
                    rets = df_p["Close"].pct_change().dropna()
                    all_returns[p["ticker"]] = rets
                    sr = sharpe_ratio(rets)
                    md = max_drawdown(df_p["Close"])
                    so = sortino_ratio(rets)
                    risk_rows.append({
                        "Ticker": p["ticker"],
                        "Sharpe": f"{sr:.2f}" if sr is not None else "n/a",
                        "Max Drawdown": f"{md * 100:.1f}%" if md is not None else "n/a",
                        "Sortino": f"{so:.2f}" if so is not None else "n/a",
                    })
                except Exception:
                    risk_rows.append({
                        "Ticker": p["ticker"],
                        "Sharpe": "n/a",
                        "Max Drawdown": "n/a",
                        "Sortino": "n/a",
                    })

            if risk_rows:
                st.caption("Based on selected history period. Sharpe/Sortino use 4.5% risk-free rate.")
                st.dataframe(pd.DataFrame(risk_rows), hide_index=True, width="stretch")

            # Portfolio-level risk
            if len(all_returns) >= 2:
                returns_df = pd.DataFrame(all_returns).dropna()
                weights_map = {
                    p["ticker"]: (p.get("weight") or 0)
                    for p in val["positions"]
                }
                valid_tickers = [t for t in returns_df.columns if t in weights_map]
                if valid_tickers:
                    w_series = pd.Series({t: weights_map[t] for t in valid_tickers})
                    w_series = w_series / w_series.sum()
                    port_returns = returns_df[valid_tickers].dot(w_series)
                    port_price = (1 + port_returns).cumprod() * 100

                    pm1, pm2, pm3 = st.columns(3)
                    ps = sharpe_ratio(port_returns)
                    pm1.metric("Portfolio Sharpe", f"{ps:.2f}" if ps is not None else "n/a")
                    pmd = max_drawdown(port_price)
                    pm2.metric("Portfolio Max DD", f"{pmd * 100:.1f}%" if pmd is not None else "n/a")
                    pso = sortino_ratio(port_returns)
                    pm3.metric("Portfolio Sortino", f"{pso:.2f}" if pso is not None else "n/a")

            # --- Correlation Matrix ---
            if len(all_returns) >= 2:
                with st.expander("Correlation Matrix"):
                    returns_df_corr = pd.DataFrame(all_returns).dropna()
                    corr = returns_df_corr.corr()
                    st.caption(
                        "Daily return correlation over the selected period. "
                        "Green = positive correlation, Red = inverse."
                    )
                    def _corr_color(v):
                        try:
                            x = float(v)
                        except (TypeError, ValueError):
                            return ""
                        x = max(-1.0, min(1.0, x))
                        if x >= 0:
                            r = int(255 + (76 - 255) * x)
                            g = int(235 + (175 - 235) * x)
                            b = int(130 + (80 - 130) * x)
                        else:
                            t = -x
                            r = int(255 + (244 - 255) * t)
                            g = int(235 + (67 - 235) * t)
                            b = int(130 + (54 - 130) * t)
                        luminance = 0.299 * r + 0.587 * g + 0.114 * b
                        text = "#000" if luminance > 140 else "#fff"
                        return f"background-color: rgb({r},{g},{b}); color: {text}"

                    st.dataframe(
                        corr.style.map(_corr_color).format("{:.2f}"),
                        width="stretch",
                    )

            # --- Per-Position Advice (parallel) ---
            st.subheader("Per-Position Advice")
            results_map = _parallel_verdicts(val["positions"], period, progress_label="Analyzing")

            per_position = []
            for p in val["positions"]:
                result = results_map.get(p["ticker"])
                if result:
                    _, _, _, _, _, _, v = result
                    per_position.append({"ticker": p["ticker"], "verdict": v})
                    with st.container():
                        banner(v, p["ticker"])

            # --- Portfolio-level assessment ---
            st.subheader("Portfolio Assessment")
            passessment = analyze_portfolio(val, per_position)
            st.markdown(passessment.get("summary", ""))
            st.markdown(f"**P/L:** {passessment.get('pl_comment', '')}")
            if passessment.get("concentration_flags"):
                st.markdown("**Concentration / Diversification**")
                for f in passessment["concentration_flags"]:
                    st.markdown(f"- {f}")
            if passessment.get("rebalancing"):
                st.markdown("**Rebalancing Suggestions**")
                for r in passessment["rebalancing"]:
                    st.markdown(f"- {r}")


# ===========================================================================
# NET WORTH TAB
# ===========================================================================
with tab_networth:
    st.subheader("Net Worth")
    st.caption(
        "Track other money accounts (HYSA, HSA, checking, crypto, real estate) "
        "and debts (credit cards, loans). Combined with brokerage holdings to "
        "compute total net worth."
    )

    if "accounts" not in st.session_state:
        st.session_state.accounts = ac.load_accounts()

    base_acc = pd.DataFrame(st.session_state.accounts, columns=ac.COLUMNS)
    if base_acc.empty:
        base_acc = pd.DataFrame([{"name": "", "type": "HYSA", "balance": 0.0, "notes": ""}])

    edited_acc = st.data_editor(
        base_acc,
        num_rows="dynamic",
        width="stretch",
        key="accounts_editor",
        column_config={
            "name": st.column_config.TextColumn("Name", help="e.g. Ally HYSA, Fidelity HSA"),
            "type": st.column_config.SelectboxColumn("Type", options=ac.ALL_TYPES, required=True),
            "balance": st.column_config.NumberColumn("Balance", format="$%.2f"),
            "notes": st.column_config.TextColumn("Notes"),
        },
    )

    acc_c1, acc_c2 = st.columns([1, 3])
    with acc_c1:
        if st.button("Save accounts", type="primary", key="save_accounts"):
            st.session_state.accounts = ac.save_accounts(edited_acc.to_dict("records"))
            st.success("Saved to accounts.json")

    accounts_now = ac._coerce(edited_acc.to_dict("records"))
    summary = ac.summarize(accounts_now)

    # Brokerage value (from current holdings if available, else 0)
    nw_holdings = pf._coerce(st.session_state.get("holdings", []) or pf.load_portfolio())
    brokerage_value = 0.0
    if nw_holdings:
        with st.spinner("Pricing brokerage holdings..."):
            try:
                val_nw = pf.value_portfolio(nw_holdings)
                brokerage_value = val_nw.get("total_value", 0.0) or 0.0
            except Exception as e:
                st.warning(f"Could not price brokerage holdings: {e}")

    nw = ac.net_worth(brokerage_value, summary)

    st.divider()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Investments", f"${nw['investments']:,.2f}")
    m2.metric("Other Assets", f"${nw['other_assets']:,.2f}")
    m3.metric("Liabilities", f"${nw['total_liabilities']:,.2f}")
    m4.metric("Net Worth", f"${nw['net_worth']:,.2f}")

    if summary["by_type"]:
        st.subheader("Breakdown by Type")
        bd_rows = []
        denom = nw["total_assets"] + nw["total_liabilities"]
        for t, bal in sorted(summary["by_type"].items(), key=lambda x: -abs(x[1])):
            kind = "Liability" if ac.is_liability(t) else "Asset"
            share = (abs(bal) / denom * 100.0) if denom else 0.0
            bd_rows.append({
                "Type": t,
                "Kind": kind,
                "Balance": bal,
                "% of Gross": round(share, 1),
            })
        if brokerage_value > 0:
            share_b = (brokerage_value / denom * 100.0) if denom else 0.0
            bd_rows.insert(0, {
                "Type": "Brokerage (stocks)",
                "Kind": "Asset",
                "Balance": brokerage_value,
                "% of Gross": round(share_b, 1),
            })
        st.dataframe(pd.DataFrame(bd_rows), hide_index=True, width="stretch")


# ===========================================================================
# WATCHLIST TAB
# ===========================================================================
with tab_watchlist:
    st.subheader("Watchlist")
    st.caption("Track price targets for stocks you're watching. Add tickers from the Analyze tab.")

    if "wl_data" not in st.session_state:
        st.session_state.wl_data = wl.load_watchlist()

    wl_items = st.session_state.wl_data

    if not wl_items:
        st.info("No watchlist entries yet. Go to **Analyze** tab, search a ticker, and click **Add / Update Watchlist**.")
    else:
        # Fetch live prices
        with st.spinner("Checking prices..."):
            prices = {}
            for item in wl_items:
                prices[item["ticker"]] = latest_price(item["ticker"])

        # Show alerts
        alerts = wl.check_alerts(wl_items, prices)
        if alerts:
            st.markdown("### 🔔 Price Alerts")
            for a in alerts:
                if a["type"] == "buy":
                    st.success(a["message"])
                else:
                    st.warning(a["message"])
            st.divider()

        # Build table
        rows = []
        for item in wl_items:
            t = item["ticker"]
            price = prices.get(t)
            buy_b = item.get("buy_below")
            sell_a = item.get("sell_above")

            if price and buy_b and price <= buy_b:
                status = "🔴 BUY TARGET HIT"
            elif price and sell_a and price >= sell_a:
                status = "🟢 SELL TARGET HIT"
            else:
                status = "—"

            rows.append({
                "Ticker": t,
                "Price": f"${price:.2f}" if price else "n/a",
                "Buy Below": f"${buy_b:.2f}" if buy_b else "—",
                "Sell Above": f"${sell_a:.2f}" if sell_a else "—",
                "Status": status,
                "Note": item.get("note", ""),
            })

        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

        st.divider()
        # Remove entry
        col_rm1, col_rm2 = st.columns([2, 1])
        with col_rm1:
            to_remove = st.selectbox(
                "Remove from watchlist",
                ["—"] + [i["ticker"] for i in wl_items],
                key="wl_remove_select",
            )
        with col_rm2:
            st.write("")
            st.write("")
            if to_remove != "—" and st.button("Remove", key="wl_remove_btn"):
                updated = wl.save_watchlist([i for i in wl_items if i["ticker"] != to_remove])
                st.session_state.wl_data = updated
                st.success(f"{to_remove} removed from watchlist.")
                st.rerun()

        if st.button("↻ Refresh prices", key="wl_refresh"):
            st.cache_data.clear()
            st.rerun()


# ===========================================================================
# ADVISOR TAB
# ===========================================================================
with tab_advisor:
    st.subheader("Personalized Portfolio Advisor")
    st.caption(
        "Tell us about your investing situation. Then run the advisor to get a tailored "
        "allocation plan, gap analysis vs your current holdings, and concrete action items."
    )

    # Load current profile
    current_profile = pr.load_profile()

    with st.expander("📋 Investor Profile", expanded=not bool(_profile_state.get("notes"))):
        risk_options = ["conservative", "moderate", "aggressive"]
        risk_in = st.select_slider(
            "Risk tolerance",
            options=risk_options,
            value=current_profile.get("risk_tolerance", "moderate"),
            key="adv_risk",
        )
        horizon_in = st.slider(
            "Time horizon (years until you need the money)",
            min_value=1, max_value=40,
            value=int(current_profile.get("horizon_years", 10)),
            key="adv_horizon",
        )
        goal_options = ["retirement", "wealth_building", "income", "preservation"]
        goals_in = st.multiselect(
            "Goals (select all that apply)",
            options=goal_options,
            default=current_profile.get("goals", ["retirement"]),
            key="adv_goals",
        )

        col_a, col_b = st.columns(2)
        with col_a:
            age_in = st.number_input(
                "Age",
                min_value=18, max_value=100,
                value=int(current_profile.get("age", 35)),
                key="adv_age",
            )
        with col_b:
            stability_options = ["stable", "variable", "uncertain"]
            stability_in = st.radio(
                "Income stability",
                options=stability_options,
                index=stability_options.index(current_profile.get("income_stability", "stable")),
                horizontal=True,
                key="adv_stability",
            )

        emergency_in = st.checkbox(
            "I have 3-6 months of expenses set aside as an emergency fund",
            value=bool(current_profile.get("emergency_fund", True)),
            key="adv_emergency",
        )
        notes_in = st.text_area(
            "Notes (optional context — e.g., 'saving for house in 5y', 'major medical expenses ahead')",
            value=current_profile.get("notes", ""),
            key="adv_notes",
        )

        if st.button("💾 Save Profile", key="adv_save_profile", type="primary"):
            new_profile = pr.save_profile({
                "risk_tolerance": risk_in,
                "horizon_years": horizon_in,
                "goals": goals_in,
                "age": age_in,
                "income_stability": stability_in,
                "emergency_fund": emergency_in,
                "notes": notes_in,
            })
            st.success("Profile saved.")
            current_profile = new_profile

    st.divider()

    # Run Advisor button
    adv_holdings = pf.load_portfolio()
    if not adv_holdings:
        st.warning(
            "No holdings found in portfolio.json. The advisor will still propose a starter "
            "allocation — but for full gap analysis, add holdings in the Portfolio tab first."
        )

    if st.button("🎯 Run Advisor Analysis", type="primary", key="adv_run"):
        with st.spinner("Building portfolio plan (≈2 min)..."):
            val_adv = pf.value_portfolio(adv_holdings) if adv_holdings else None
            # Skip per-position verdicts — advisor uses valuation (weights,
            # sectors, P/L, concentration) which is the signal that matters
            # for allocation. Cuts runtime ~8x.
            plan = build_portfolio_plan(current_profile, val_adv, [])

        # Cache to session state so plan survives reruns (e.g. chat submissions).
        st.session_state.advisor_plan = plan
        st.session_state.advisor_valuation = val_adv
        st.session_state.advisor_profile_snapshot = dict(current_profile)
        # Reset chat when a new plan is generated.
        st.session_state.advisor_chat = []

    # Render the plan from session state if it exists (survives page reruns).
    if st.session_state.get("advisor_plan"):
        plan = st.session_state.advisor_plan
        val_adv = st.session_state.get("advisor_valuation")

        # --- Fit Assessment ---
        src = plan.get("source", "")
        src_badge = " · 🦙 Ollama" if src == "ollama" else (" · ☁️ Claude" if src == "llm" else " · rule-based")
        st.info(f"**Portfolio Fit Assessment**{src_badge}\n\n{plan.get('fit_assessment', '')}")
        if plan.get("error"):
            st.caption(f"⚠️ {plan['error']}")

        # --- Target Allocation ---
        st.subheader("🎯 Target Allocation")
        ta = plan.get("target_allocation", [])
        if ta:
            ta_df = pd.DataFrame([
                {
                    "Category": r["category"],
                    "Target %": r["target_pct"],
                    "Rationale": r["rationale"],
                }
                for r in ta
            ])
            st.dataframe(ta_df, hide_index=True, width="stretch")

        # --- Current vs Target ---
        cvt = plan.get("current_vs_target", [])
        if cvt:
            st.subheader("📊 Current vs Target Allocation")

            cvt_df = pd.DataFrame([
                {
                    "Category": r["category"],
                    "Current %": r.get("current_pct", 0),
                    "Target %": r.get("target_pct", 0),
                    "Gap %": r.get("gap_pct", 0),
                    "Action": r.get("action", "—"),
                }
                for r in cvt
            ])

            # Bar chart: current vs target side-by-side
            chart_data = pd.DataFrame({
                "Current": [r.get("current_pct", 0) for r in cvt],
                "Target": [r.get("target_pct", 0) for r in cvt],
            }, index=[r["category"] for r in cvt])
            st.bar_chart(chart_data)

            # Color-coded gap table
            def _color_gap(v):
                try:
                    val_f = float(v)
                except (TypeError, ValueError):
                    return ""
                if abs(val_f) < 5:
                    return "background-color: #d4edda; color: #155724"
                if abs(val_f) < 15:
                    return "background-color: #fff3cd; color: #856404"
                return "background-color: #f8d7da; color: #721c24"

            st.dataframe(
                cvt_df.style.map(_color_gap, subset=["Gap %"]),
                hide_index=True, width="stretch",
            )

        # --- Action Items ---
        ai_items = plan.get("action_items", [])
        if ai_items:
            st.subheader("✅ Action Items (in order)")
            for item in sorted(ai_items, key=lambda x: x.get("priority", 99)):
                action = (item.get("action") or "").lower()
                icon = ACTION_COLORS.get(action, "•")
                p = item.get("priority", "?")
                t = item.get("ticker", "—")
                amt = item.get("amount_desc", "")
                reason = item.get("reason", "")
                st.markdown(f"**{p}.** {icon} **{action.upper()}** `{t}` — {amt}  \n   _{reason}_")

        # --- Suggested Tickers ---
        suggested = plan.get("suggested_tickers", [])
        if suggested:
            st.subheader("💡 Suggested Tickers to Consider")
            for i, sug in enumerate(suggested):
                t = sug.get("ticker", "")
                cat = sug.get("category", "")
                rat = sug.get("rationale", "")
                tw = sug.get("target_weight_pct", 0)
                cols = st.columns([4, 1])
                with cols[0]:
                    st.markdown(f"**`{t}`** ({cat}) — target ~{tw}%  \n_{rat}_")
                with cols[1]:
                    if st.button("➕ Watchlist", key=f"adv_add_wl_{i}_{t}"):
                        existing_wl = wl.load_watchlist()
                        if not any(w["ticker"] == t for w in existing_wl):
                            existing_wl.append({
                                "ticker": t,
                                "buy_below": None,
                                "sell_above": None,
                                "note": f"Advisor suggestion: {cat}",
                            })
                            wl.save_watchlist(existing_wl)
                            st.session_state.wl_data = existing_wl
                            st.success(f"{t} added to watchlist.")
                        else:
                            st.info(f"{t} already in watchlist.")

        # --- Risks ---
        risks = plan.get("risks_to_watch", [])
        if risks:
            st.subheader("⚠️ Risks to Watch")
            for r in risks:
                st.markdown(f"- {r}")

        # --- Rebalance frequency ---
        rebal = plan.get("rebalance_frequency", "")
        if rebal:
            st.caption(f"📅 **Rebalance:** {rebal}")

    # --- Conversational chat about the plan -----------------------------------
    st.divider()
    st.subheader("💬 Discuss with your advisor")

    if "advisor_chat" not in st.session_state:
        st.session_state.advisor_chat = []

    plan_ready = bool(st.session_state.get("advisor_plan"))
    if not plan_ready:
        st.caption(
            "Run the advisor above first. Once a plan exists, you can ask follow-up "
            "questions or challenge any recommendation here."
        )
    else:
        st.caption(
            "Tip: be specific. e.g. _'Why trim VOO when it's up 32%?'_ or "
            "_'I want to keep all my PLTR — convince me otherwise.'_"
        )

    # Render existing chat history.
    for msg in st.session_state.advisor_chat:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            src = msg.get("source")
            if src and src != "user":
                badge = {"ollama": "🦙 Ollama", "anthropic": "☁️ Claude", "error": "⚠️ error"}.get(src, src)
                st.caption(badge)

    # Chat input (always rendered so layout is stable; disabled until plan ready).
    user_input = st.chat_input(
        "Ask about your portfolio..." if plan_ready else "Run advisor first to enable chat",
        disabled=not plan_ready,
        key="advisor_chat_input",
    )

    if user_input:
        user_input = user_input.strip()[:1000]  # cap input length
        if user_input:
            st.session_state.advisor_chat.append({"role": "user", "content": user_input})
            with st.chat_message("user"):
                st.markdown(user_input)
            with st.chat_message("assistant"):
                with st.spinner("Thinking..."):
                    reply = chat_with_advisor(
                        st.session_state.advisor_chat,
                        st.session_state.get("advisor_profile_snapshot") or current_profile,
                        st.session_state.get("advisor_valuation"),
                        st.session_state.get("advisor_plan"),
                    )
                st.markdown(reply["content"])
                src = reply.get("source")
                badge = {"ollama": "🦙 Ollama", "anthropic": "☁️ Claude", "error": "⚠️ error"}.get(src, "")
                if badge:
                    st.caption(badge)
            st.session_state.advisor_chat.append(reply)
            st.rerun()

    if st.session_state.advisor_chat:
        if st.button("🗑 Reset chat", key="adv_chat_reset"):
            st.session_state.advisor_chat = []
            st.rerun()


# --- Footer ----------------------------------------------------------------
st.divider()
st.caption(
    "Educational tool only — not financial advice. Data via yfinance/Finnhub may be "
    "delayed or inaccurate. Verify before making any investment decision."
)
