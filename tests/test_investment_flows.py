"""investment_flows.py: monthly contribution / dividend / withdrawal totals from
Plaid investment transactions, and YTD figures for the contribution limits."""

import datetime
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import investment_flows as fl  # noqa: E402
import contributions as ct  # noqa: E402

SUB = {"a401": "401k", "ahsa": "hsa"}


def tx(account, date, type_, subtype, amount):
    return {"account_id": account, "date": date, "type": type_, "subtype": subtype, "amount": amount}


def test_inflows_are_positive_and_buys_sells_are_ignored():
    txs = [tx("a401", "2026-10-05", "cash", "contribution", -500.0),
           tx("a401", "2026-10-06", "buy", "buy", 500.0),
           tx("a401", "2026-10-06", "sell", "sell", -20.0),
           tx("ahsa", "2026-10-07", "cash", "deposit", -150.0),
           tx("ahsa", "2026-10-08", "cash", "dividend", -1.25),
           tx("ahsa", "2026-10-09", "cash", "withdrawal", 40.0)]
    m = fl.aggregate(txs, SUB)["months"]["2026-10"]
    assert m["401k"] == {"contributions": 500.0, "dividends": 0.0, "withdrawals": 0.0}
    assert m["hsa"] == {"contributions": 150.0, "dividends": 1.25, "withdrawals": 40.0}


def test_months_are_bucketed_and_amounts_summed():
    txs = [tx("a401", "2026-09-30", "cash", "contribution", -100.0),
           tx("a401", "2026-10-01", "cash", "contribution", -50.0),
           tx("a401", "2026-10-15", "cash", "contribution", -25.5)]
    months = fl.aggregate(txs, SUB)["months"]
    assert months["2026-09"]["401k"]["contributions"] == 100.0
    assert months["2026-10"]["401k"]["contributions"] == 75.5


def test_unknown_account_and_unknown_kinds_are_ignored_not_fatal():
    txs = [tx("mystery", "2026-10-05", "cash", "contribution", -500.0),
           tx("a401", "2026-10-05", "fee", "management fee", 3.0),
           tx("a401", "2026-10-05", "cash", "contribution", -10.0)]
    m = fl.aggregate(txs, SUB)["months"]["2026-10"]
    assert list(m) == ["401k"] and m["401k"]["contributions"] == 10.0


@pytest.mark.parametrize("bad", [
    tx("a401", "not-a-date", "cash", "contribution", -1.0),
    tx("a401", "2026-10-05", "cash", "contribution", "x"),
    tx("a401", "2026-10-05", "cash", "contribution", float("nan")),
])
def test_malformed_rows_raise(bad):
    with pytest.raises(fl.FlowsError):
        fl.aggregate([bad], SUB)


def test_ytd_sums_only_the_year():
    flows = fl.aggregate([tx("a401", "2025-12-20", "cash", "contribution", -999.0),
                          tx("a401", "2026-01-15", "cash", "contribution", -100.0),
                          tx("ahsa", "2026-03-15", "cash", "dividend", -2.0)], SUB)
    y = fl.ytd(flows, 2026)
    assert y["401k"]["contributions"] == 100.0 and y["hsa"]["dividends"] == 2.0
    assert fl.limit_ytd(flows, 2026) == {"401k": 100.0, "hsa": 0.0}


def test_limit_ytd_maps_roth_and_ira_to_the_roth_key():
    flows = fl.aggregate([tx("r", "2026-02-01", "cash", "contribution", -700.0)], {"r": "roth"})
    assert fl.limit_ytd(flows, 2026)["roth"] == 700.0


def test_trailing_dividends_window():
    flows = fl.aggregate([tx("ahsa", "2025-06-01", "cash", "dividend", -9.0),
                          tx("ahsa", "2026-01-01", "cash", "dividend", -3.0),
                          tx("ahsa", "2026-11-01", "cash", "dividend", -1.0)], SUB)
    assert fl.trailing_dividends(flows, datetime.date(2026, 11, 14)) == pytest.approx(4.0)


def test_save_load_roundtrip_is_atomic_and_json_clean(tmp_path, monkeypatch):
    monkeypatch.setattr(fl, "FLOWS_FILE", str(tmp_path / "f.json"))
    flows = fl.aggregate([tx("a401", "2026-10-05", "cash", "contribution", -5.0)], SUB)
    fl.save(flows)
    assert fl.load()["months"]["2026-10"]["401k"]["contributions"] == 5.0
    assert not os.path.exists(str(tmp_path / "f.json") + ".tmp")
    json.dumps(flows, allow_nan=False)


def test_load_missing_or_corrupt_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(fl, "FLOWS_FILE", str(tmp_path / "f.json"))
    assert fl.load() == {"months": {}, "synced_at": None}
    open(fl.FLOWS_FILE, "w").write("{bad")
    assert fl.load() == {"months": {}, "synced_at": None}


def test_pagination_collects_every_page_and_stops_at_total():
    data = list(range(23))
    calls = []
    def get_page(offset):
        calls.append(offset)
        return data[offset:offset + 10], len(data)
    assert fl.fetch_all_pages(get_page) == data and calls == [0, 10, 20]


def test_pagination_guards_against_a_server_that_never_advances():
    with pytest.raises(fl.FlowsError):
        fl.fetch_all_pages(lambda off: ([], 50))


# --- contribution limits use detected figures unless the user typed a number ----------
def test_detected_ytd_fills_in_when_no_manual_number():
    out = ct.compute({}, year=2026, detected={"401k": 13521.21, "hsa": 3961.95})
    assert out["hsa"]["ytd"] == 3961.95 and out["hsa"]["room"] == pytest.approx(438.05)
    assert out["hsa"]["source"] == "fidelity" and out["roth"]["source"] == "none"


def test_manual_number_wins_over_detected():
    out = ct.compute({"contrib_401k_ytd": 20000}, year=2026, detected={"401k": 13521.21})
    assert out["401k"]["ytd"] == 20000.0 and out["401k"]["source"] == "manual"


def test_401k_detected_figure_is_flagged_as_possibly_including_employer_money():
    out = ct.compute({}, year=2026, detected={"401k": 13521.21})
    assert out["401k"]["mayIncludeEmployer"] is True and out["hsa"]["mayIncludeEmployer"] is False
