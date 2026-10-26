"""Tests for daily_history.py (per-day per-account/holding record) and
attribution.py (split a net-worth change into market / contributions / other)."""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import daily_history as dh  # noqa: E402
import attribution as at  # noqa: E402


def pos(ticker, account, shares, price, sector="—"):
    return {"ticker": ticker, "account": account, "shares": shares, "price": price,
            "value": shares * price, "sector": sector}


# --- daily_history ----------------------------------------------------------
@pytest.fixture
def hist(tmp_path, monkeypatch):
    monkeypatch.setattr(dh, "HISTORY_FILE", str(tmp_path / "daily.json"))
    return dh


def test_record_and_load_roundtrip(hist):
    hist.record_day("2026-10-26", 1000.0, {"TOTAL CHECKING": 3500.4},
                    [pos("VTI", "Roth IRA", 2, 100.0, "ETF")], complete=True)
    days = hist.load_days()
    d = days["2026-10-26"]
    assert d["netWorth"] == 1000
    assert d["accounts"] == {"TOTAL CHECKING": 3500}
    assert d["holdings"]["Roth IRA|VTI"] == {"q": 2, "p": 100.0, "s": "ETF"}
    assert d["complete"] is True


def test_same_day_is_overwritten_by_latest_complete_reading(hist):
    hist.record_day("2026-10-26", 1000, {}, [pos("VTI", "Roth IRA", 2, 100.0)], True)
    hist.record_day("2026-10-26", 1100, {}, [pos("VTI", "Roth IRA", 2, 110.0)], True)
    assert hist.load_days()["2026-10-26"]["netWorth"] == 1100


def test_incomplete_reading_never_overwrites_a_complete_one(hist):
    hist.record_day("2026-10-26", 1000, {}, [pos("VTI", "Roth IRA", 2, 100.0)], True)
    hist.record_day("2026-10-26", 400, {}, [pos("VTI", "Roth IRA", 2, 40.0)], False)
    assert hist.load_days()["2026-10-26"]["netWorth"] == 1000


def test_incomplete_reading_is_kept_if_nothing_better_exists(hist):
    hist.record_day("2026-10-26", 400, {}, [pos("VTI", "Roth IRA", 2, 40.0)], False)
    assert hist.load_days()["2026-10-26"]["complete"] is False


def test_nan_and_none_values_never_reach_the_file(hist):
    hist.record_day("2026-10-26", float("nan"), {"A": float("inf"), "B": None}, [], True)
    raw = open(hist.HISTORY_FILE).read()
    assert "NaN" not in raw and "Infinity" not in raw


def test_missing_or_corrupt_file_loads_empty(hist):
    assert hist.load_days() == {}
    open(hist.HISTORY_FILE, "w").write("{not json")
    assert hist.load_days() == {}


def test_prune_keeps_only_recent_days(hist, monkeypatch):
    monkeypatch.setattr(hist, "KEEP_DAYS", 3)
    for i in range(1, 7):
        hist.record_day(f"2026-10-{i:02d}", i, {}, [], True)
    assert sorted(hist.load_days()) == ["2026-10-04", "2026-10-05", "2026-10-06"]


# --- attribution ------------------------------------------------------------
def day(nw, accounts=None, holdings=None, complete=True):
    h = {}
    for (acct, tk), (q, p) in (holdings or {}).items():
        h[f"{acct}|{tk}"] = {"q": q, "p": p, "s": "—"}
    return {"netWorth": nw, "accounts": accounts or {}, "holdings": h, "complete": complete}


def test_pure_market_move():
    prev = day(1000, holdings={("Roth", "VTI"): (10, 100.0)})
    cur = day(1100, holdings={("Roth", "VTI"): (10, 110.0)})
    r = at.attribute(prev, cur)
    assert r["market"] == pytest.approx(100)
    assert r["contributions"] == pytest.approx(0)
    assert r["other"] == pytest.approx(0)


def test_new_shares_are_contributions_not_market():
    prev = day(1000, holdings={("Roth", "VTI"): (10, 100.0)})
    cur = day(1210, holdings={("Roth", "VTI"): (11, 110.0)})
    r = at.attribute(prev, cur)
    assert r["market"] == pytest.approx(100)          # 10 old shares x +$10
    assert r["contributions"] == pytest.approx(110)   # 1 new share at $110


def test_new_and_removed_holdings():
    prev = day(1000, holdings={("B", "AAA"): (10, 100.0)})
    cur = day(500, holdings={("B", "BBB"): (5, 100.0)})
    r = at.attribute(prev, cur)
    assert r["contributions"] == pytest.approx(500 - 1000)
    assert r["market"] == pytest.approx(0)


def test_other_accounts_change_is_cash_flow_bucket():
    prev = day(1000, accounts={"TOTAL CHECKING": 3900, "401k": 78000})
    cur = day(1000, accounts={"TOTAL CHECKING": 3480, "401k": 78875})
    r = at.attribute(prev, cur)
    assert r["other"] == pytest.approx(-420 + 875)
    assert r["other_by_account"] == {"TOTAL CHECKING": -420, "401k": 875}


def test_components_add_up_to_total_change():
    prev = day(0, accounts={"C": 100}, holdings={("A", "X"): (10, 10.0), ("A", "Y"): (3, 50.0)})
    cur = day(0, accounts={"C": 80, "NEW": 5}, holdings={("A", "X"): (12, 11.0), ("A", "Z"): (1, 7.0)})
    r = at.attribute(prev, cur)
    before = 100 + 100 + 150
    after = 80 + 5 + 132 + 7
    assert r["market"] + r["contributions"] + r["other"] == pytest.approx(after - before)
    assert r["total"] == pytest.approx(after - before)


def test_top_movers_sorted_by_dollar_market_move():
    prev = day(0, holdings={("A", "X"): (10, 10.0), ("A", "Y"): (10, 10.0)})
    cur = day(0, holdings={("A", "X"): (10, 11.0), ("A", "Y"): (10, 5.0)})
    r = at.attribute(prev, cur)
    assert [m["ticker"] for m in r["movers"]] == ["Y", "X"]
    assert r["movers"][0]["market"] == pytest.approx(-50)


def test_same_ticker_in_two_accounts_is_tracked_separately():
    prev = day(0, holdings={("Roth", "MU"): (1, 100.0), ("Brokerage", "MU"): (2, 100.0)})
    cur = day(0, holdings={("Roth", "MU"): (1, 110.0), ("Brokerage", "MU"): (2, 110.0)})
    assert at.attribute(prev, cur)["market"] == pytest.approx(30)


def test_range_sums_daily_steps_so_a_mid_month_buy_isnt_called_market():
    days = {
        "2026-10-01": day(0, holdings={("A", "X"): (10, 100.0)}),
        "2026-10-02": day(0, holdings={("A", "X"): (20, 100.0)}),   # buys 10 at 100
        "2026-10-03": day(0, holdings={("A", "X"): (20, 110.0)}),   # +10/share on 20 shares
    }
    r = at.attribute_range(days, "2026-10-01", "2026-10-03")
    assert r["contributions"] == pytest.approx(1000)
    assert r["market"] == pytest.approx(200)
    assert r["total"] == pytest.approx(1200)


def test_range_skips_incomplete_days():
    days = {
        "2026-10-01": day(0, holdings={("A", "X"): (10, 100.0)}),
        "2026-10-02": day(0, holdings={("A", "X"): (10, 40.0)}, complete=False),  # unpriced junk
        "2026-10-03": day(0, holdings={("A", "X"): (10, 110.0)}),
    }
    r = at.attribute_range(days, "2026-10-01", "2026-10-03")
    assert r["market"] == pytest.approx(100)


def test_range_returns_none_without_two_usable_days():
    days = {"2026-10-01": day(0)}
    assert at.attribute_range(days, "2026-10-01", "2026-10-31") is None


def test_range_uses_first_and_last_available_days_in_window():
    days = {
        "2026-09-30": day(0, accounts={"C": 1}),
        "2026-10-02": day(0, accounts={"C": 10}),
        "2026-10-20": day(0, accounts={"C": 30}),
        "2026-11-01": day(0, accounts={"C": 99}),
    }
    r = at.attribute_range(days, "2026-10-01", "2026-10-31")
    assert r["start"] == "2026-10-02" and r["end"] == "2026-10-20"
    assert r["other"] == pytest.approx(20)


def test_analytics_blob_is_stored_with_the_day(hist):
    hist.record_day("2026-10-26", 1000, {}, [], True, analytics={"top5Pct": 61.5, "top": []})
    assert hist.load_days()["2026-10-26"]["analytics"]["top5Pct"] == 61.5


def test_day_without_analytics_has_no_key(hist):
    hist.record_day("2026-10-26", 1000, {}, [], True)
    assert "analytics" not in hist.load_days()["2026-10-26"]
