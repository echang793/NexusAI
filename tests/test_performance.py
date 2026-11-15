"""performance.py: time-weighted return from daily_history records. Deposits and
new share purchases must never look like gains."""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import performance as pf  # noqa: E402


def day(holdings, spy=None, complete=True):
    d = {"netWorth": 0, "accounts": {}, "complete": complete,
         "holdings": {f"{a}|{t}": {"q": q, "p": p, "s": "—"} for (a, t), (q, p) in holdings.items()}}
    if spy is not None:
        d["spy"] = spy
    return d


A = "Brokerage"
R = "Roth IRA"


def test_simple_price_gain():
    days = {"2026-11-01": day({(A, "VTI"): (10, 100.0)}), "2026-11-02": day({(A, "VTI"): (10, 110.0)})}
    r = pf.twr(days, "2026-11-01", "2026-11-02")
    assert r["returnPct"] == pytest.approx(10.0) and r["marketGain"] == pytest.approx(100.0)
    assert r["days"] == 1


def test_buying_shares_is_not_a_gain():
    days = {"2026-11-01": day({(A, "VTI"): (10, 100.0)}),
            "2026-11-02": day({(A, "VTI"): (20, 100.0)}),       # bought 10 shares at 100, no price move
            "2026-11-03": day({(A, "VTI"): (20, 110.0)})}       # +10% on 2,000
    r = pf.twr(days, "2026-11-01", "2026-11-03")
    assert r["returnPct"] == pytest.approx(10.0)                 # not 120%
    assert r["marketGain"] == pytest.approx(200.0)


def test_returns_compound_across_days():
    days = {"2026-11-01": day({(A, "X"): (1, 100.0)}), "2026-11-02": day({(A, "X"): (1, 110.0)}),
            "2026-11-03": day({(A, "X"): (1, 121.0)})}
    assert pf.twr(days, "2026-11-01", "2026-11-03")["returnPct"] == pytest.approx(21.0)


def test_big_deposit_does_not_dilute_the_return():
    days = {"2026-11-01": day({(A, "X"): (1, 100.0)}),
            "2026-11-02": day({(A, "X"): (1, 110.0), (A, "Y"): (100, 100.0)}),   # +10% then a $10,000 buy
            "2026-11-03": day({(A, "X"): (1, 110.0), (A, "Y"): (100, 100.0)})}   # flat
    assert pf.twr(days, "2026-11-01", "2026-11-03")["returnPct"] == pytest.approx(10.0)


def test_incomplete_days_are_skipped():
    days = {"2026-11-01": day({(A, "X"): (1, 100.0)}),
            "2026-11-02": day({(A, "X"): (1, 40.0)}, complete=False),     # unpriced junk
            "2026-11-03": day({(A, "X"): (1, 110.0)})}
    assert pf.twr(days, "2026-11-01", "2026-11-03")["returnPct"] == pytest.approx(10.0)


def test_window_selects_first_and_last_usable_days():
    days = {"2026-10-30": day({(A, "X"): (1, 50.0)}), "2026-11-02": day({(A, "X"): (1, 100.0)}),
            "2026-11-20": day({(A, "X"): (1, 120.0)}), "2026-12-05": day({(A, "X"): (1, 999.0)})}
    r = pf.twr(days, "2026-11-01", "2026-11-30")
    assert r["from"] == "2026-11-02" and r["to"] == "2026-11-20" and r["returnPct"] == pytest.approx(20.0)


def test_fewer_than_two_usable_days_gives_none():
    assert pf.twr({"2026-11-01": day({(A, "X"): (1, 1.0)})}, "2026-11-01", "2026-11-30") is None
    assert pf.twr({}, "2026-11-01", "2026-11-30") is None


def test_per_account_returns_are_separate():
    days = {"2026-11-01": day({(A, "X"): (1, 100.0), (R, "Y"): (1, 100.0)}),
            "2026-11-02": day({(A, "X"): (1, 110.0), (R, "Y"): (1, 95.0)})}
    out = pf.per_account(days, "2026-11-01", "2026-11-02")
    assert out[A]["returnPct"] == pytest.approx(10.0) and out[R]["returnPct"] == pytest.approx(-5.0)


def test_account_that_did_not_exist_at_start_is_measured_from_when_it_appears():
    days = {"2026-11-01": day({(A, "X"): (1, 100.0)}),
            "2026-11-02": day({(A, "X"): (1, 100.0), (R, "Y"): (1, 100.0)}),
            "2026-11-03": day({(A, "X"): (1, 100.0), (R, "Y"): (1, 110.0)})}
    assert pf.per_account(days, "2026-11-01", "2026-11-03")[R]["returnPct"] == pytest.approx(10.0)


def test_annualized_only_for_periods_of_a_year_or_more():
    short = {"2026-01-01": day({(A, "X"): (1, 100.0)}), "2026-06-01": day({(A, "X"): (1, 110.0)})}
    assert pf.twr(short, "2026-01-01", "2026-06-30")["annualizedPct"] is None
    long = {"2025-01-01": day({(A, "X"): (1, 100.0)}), "2027-01-01": day({(A, "X"): (1, 121.0)})}
    assert pf.twr(long, "2025-01-01", "2027-01-01")["annualizedPct"] == pytest.approx(10.0, abs=0.2)


def test_vs_benchmark_compares_same_dates():
    days = {"2026-11-01": day({(A, "X"): (1, 100.0)}, spy=500.0),
            "2026-11-10": day({(A, "X"): (1, 108.0)}, spy=510.0)}
    r = pf.vs_benchmark(days, "2026-11-01", "2026-11-30")
    assert r["portfolioPct"] == pytest.approx(8.0) and r["spyPct"] == pytest.approx(2.0)
    assert r["excessPct"] == pytest.approx(6.0) and r["covered"] is True


def test_benchmark_uses_only_days_that_have_spy():
    days = {"2026-11-01": day({(A, "X"): (1, 100.0)}),                  # no SPY yet
            "2026-11-05": day({(A, "X"): (1, 110.0)}, spy=500.0),
            "2026-11-10": day({(A, "X"): (1, 121.0)}, spy=505.0)}
    r = pf.vs_benchmark(days, "2026-11-01", "2026-11-30")
    assert r["from"] == "2026-11-05"
    assert r["portfolioPct"] == pytest.approx(10.0) and r["spyPct"] == pytest.approx(1.0)


def test_benchmark_not_covered_without_two_spy_days():
    days = {"2026-11-01": day({(A, "X"): (1, 100.0)}), "2026-11-02": day({(A, "X"): (1, 101.0)}, spy=500.0)}
    r = pf.vs_benchmark(days, "2026-11-01", "2026-11-30")
    assert r["covered"] is False and r["spyPct"] is None and r["excessPct"] is None


def test_zero_base_and_nan_prices_are_safe_and_json_clean():
    days = {"2026-11-01": day({}), "2026-11-02": day({(A, "X"): (1, 100.0)}),
            "2026-11-03": day({(A, "X"): (1, float("nan"))})}
    r = pf.twr(days, "2026-11-01", "2026-11-03")
    json.dumps(r, allow_nan=False)
