"""Scorecard: did BUY / SELL / HOLD calls from advisory.get_advice() actually
precede out-of-the-ordinary returns? Pure functions; the script feeds them
real prices."""

import json
import os
import sys

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import scorecard as sc  # noqa: E402


def frame(n=300, sma50=110.0, sma200=100.0, rsi=40.0):
    idx = pd.bdate_range("2024-01-02", periods=n)
    df = pd.DataFrame({"Close": [100.0 + i for i in range(n)]}, index=idx)
    df["SMA50"], df["SMA200"], df["RSI"] = sma50, sma200, rsi
    df.loc[df.index[:199], ["SMA50", "SMA200", "RSI"]] = float("nan")   # warm-up
    return df


def test_signal_rows_reuse_the_real_advisor_rules():
    buy = sc.signal_rows(frame(sma50=110, sma200=100, rsi=40), step=10)
    sell = sc.signal_rows(frame(sma50=90, sma200=100, rsi=50), step=10)
    hold = sc.signal_rows(frame(sma50=110, sma200=100, rsi=55), step=10)
    assert {r["signal"] for r in buy} == {"BUY"}
    assert {r["signal"] for r in sell} == {"SELL"}
    assert {r["signal"] for r in hold} == {"HOLD"}


def test_warmup_rows_without_indicators_are_skipped():
    rows = sc.signal_rows(frame(), step=1)
    assert rows and min(r["i"] for r in rows) >= 199


def test_step_thins_overlapping_samples():
    assert len(sc.signal_rows(frame(), step=1)) > 4 * len(sc.signal_rows(frame(), step=5))


def test_forward_return_and_off_the_end():
    close = pd.Series([100.0, 110.0, 121.0])
    assert sc.forward_return(close, 0, 2) == pytest.approx(0.21)
    assert sc.forward_return(close, 1, 5) is None


def _series(vals):
    return pd.Series(vals, index=pd.bdate_range("2024-01-02", periods=len(vals)))


def test_evaluate_scores_buy_that_beats_the_market_and_sell_that_falls():
    n = 40
    stock = _series([100.0] * 5 + [100.0 + 2 * i for i in range(n - 5)])        # rises from day 5
    spy = _series([100.0] * n)
    rows = [{"i": 5, "signal": "BUY"}, {"i": 6, "signal": "BUY"}, {"i": 30, "signal": "SELL"}]
    out = sc.evaluate({"X": (rows, stock)}, spy, horizons=(5,))
    buy = out["BUY"][5]
    assert buy["n"] == 2 and buy["avgExcess"] > 0 and buy["hitRate"] == 100.0
    assert out["SELL"][5]["avgRet"] > 0    # price kept rising after this SELL -> a bad call
    assert out["SELL"][5]["hitRate"] == 0.0     # it kept beating the market, so the SELL was wrong


def test_evaluate_sell_hit_means_it_underperformed():
    n = 40
    stock = _series([100.0 - i for i in range(n)])          # always falling
    spy = _series([100.0] * n)
    out = sc.evaluate({"X": ([{"i": 3, "signal": "SELL"}], stock)}, spy, horizons=(5,))
    assert out["SELL"][5]["hitRate"] == 100.0               # a SELL is "right" when it lags the market


def test_baseline_all_signals_row_present():
    n = 40
    stock = _series([100.0 + i for i in range(n)])
    spy = _series([100.0] * n)
    out = sc.evaluate({"X": ([{"i": 3, "signal": "BUY"}, {"i": 4, "signal": "HOLD"}], stock)}, spy, horizons=(5,))
    assert out["ALL"][5]["n"] == 2


def test_rows_too_close_to_the_end_are_dropped_for_that_horizon():
    n = 20
    stock = _series([100.0] * n)
    spy = _series([100.0] * n)
    out = sc.evaluate({"X": ([{"i": 18, "signal": "BUY"}], stock)}, spy, horizons=(5,))
    assert out["BUY"][5]["n"] == 0 and out["BUY"][5]["hitRate"] is None


def test_summary_is_json_safe():
    n = 40
    stock = _series([100.0 + i for i in range(n)])
    spy = _series([100.0] * n)
    out = sc.evaluate({"X": ([{"i": 3, "signal": "BUY"}], stock)}, spy, horizons=(5,))
    json.dumps(out, allow_nan=False)


def test_render_states_the_caveats_and_the_headline():
    n = 40
    stock = _series([100.0 + i for i in range(n)])
    spy = _series([100.0] * n)
    out = sc.evaluate({"X": ([{"i": 3, "signal": "BUY"}] * 30, stock)}, spy, horizons=(5,))
    text = sc.render(out, tickers=["X"], horizons=(5,))
    assert "BUY" in text and "SELL" in text
    assert "current holdings" in text.lower()      # survivorship caveat is always printed
    assert "not advice" in text.lower()


def test_render_small_sample_is_flagged_not_trusted():
    n = 40
    stock = _series([100.0 + i for i in range(n)])
    spy = _series([100.0] * n)
    out = sc.evaluate({"X": ([{"i": 3, "signal": "BUY"}], stock)}, spy, horizons=(5,))
    assert "too few" in sc.render(out, ["X"], (5,)).lower()


# --- scripts/scorecard.py pipeline ---------------------------------------------------
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import scorecard_run as sr  # noqa: E402


def _closes(n=700, tickers=("AAA", "BBB"), spy=True):
    import numpy as np
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2022-01-03", periods=n)
    data = {t: 100 * np.cumprod(1 + rng.normal(0.0004, 0.015, n)) for t in tickers}
    if spy:
        data["SPY"] = 100 * np.cumprod(1 + rng.normal(0.0004, 0.01, n))
    return pd.DataFrame(data, index=idx)


def test_pipeline_produces_summary_for_every_signal():
    summary, used = sr.build_scorecard(_closes(), horizons=(21,))
    assert used == ["AAA", "BBB"]
    assert set(summary) == {"BUY", "SELL", "HOLD", "ALL"}
    assert summary["ALL"][21]["n"] > 50
    json.dumps(summary, allow_nan=False)


def test_pipeline_fails_loudly_without_spy():
    with pytest.raises(sr.ScorecardError, match="SPY"):
        sr.build_scorecard(_closes(spy=False), horizons=(21,))


def test_pipeline_fails_loudly_when_history_is_too_short():
    with pytest.raises(sr.ScorecardError, match="no ticker"):
        sr.build_scorecard(_closes(n=150), horizons=(21,))


def test_tickers_that_cannot_be_priced_are_skipped_not_fatal():
    c = _closes()
    c["JUNK"] = float("nan")
    _, used = sr.build_scorecard(c, horizons=(21,))
    assert "JUNK" not in used


def test_held_tickers_exclude_proprietary_plan_codes_and_dedupe():
    rows = [{"ticker": "VTI"}, {"ticker": "vti"}, {"ticker": "NON40OJ1"}, {"ticker": "MU"}]
    assert sr.scorable_tickers(rows) == ["MU", "VTI"]
