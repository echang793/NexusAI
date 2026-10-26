"""Portfolio analytics: concentration, overlap, asset location, allocation."""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import analytics as an  # noqa: E402


def p(ticker, account, value, sector="—"):
    return {"ticker": ticker, "account": account, "value": value, "sector": sector,
            "shares": 1, "price": value}


def cls(ticker, sector):
    return {"BND": "Bonds", "VXUS": "International"}.get(ticker, "US Equity")


def run(positions, div=None, risk=None):
    return an.compute(positions, div or {}, cls, risk=risk)


def test_weights_aggregate_across_accounts():
    r = run([p("MU", "Roth IRA", 300), p("MU", "Brokerage", 100), p("VTI", "Brokerage", 600)])
    top = {t["ticker"]: t for t in r["top"]}
    assert top["MU"]["pct"] == pytest.approx(40.0)
    assert sorted(top["MU"]["accounts"]) == ["Brokerage", "Roth IRA"]


def test_top_is_sorted_and_capped_at_five():
    pos = [p(f"T{i}", "Brokerage", 100 + i) for i in range(8)]
    r = run(pos)
    assert len(r["top"]) == 5
    assert [t["ticker"] for t in r["top"]] == ["T7", "T6", "T5", "T4", "T3"]
    assert r["top5Pct"] == pytest.approx(sum(t["pct"] for t in r["top"]), abs=0.1)


def test_effective_number_of_holdings():
    equal4 = run([p(f"T{i}", "B", 100) for i in range(4)])
    assert equal4["effectiveN"] == pytest.approx(4.0)
    lopsided = run([p("BIG", "B", 970), p("S1", "B", 10), p("S2", "B", 10), p("S3", "B", 10)])
    assert lopsided["effectiveN"] < 1.2


def test_single_stock_over_limit_is_flagged_but_broad_fund_is_not():
    r = run([p("NVDA", "B", 300), p("VOO", "B", 600), p("X", "B", 100)])
    flagged = [f["ticker"] for f in r["singleNameFlags"]]
    assert "NVDA" in flagged and "VOO" not in flagged


def test_mutual_fund_ticker_shape_is_treated_as_a_fund():
    r = run([p("FXAIX", "HSA", 900), p("X", "B", 100)])
    assert r["singleNameFlags"] == []


def test_multi_account_listing():
    r = run([p("MU", "Roth IRA", 50), p("MU", "Brokerage", 50), p("VTI", "Brokerage", 900)])
    assert [m["ticker"] for m in r["multiAccount"]] == ["MU"]


def test_asset_location_flags_dividend_payers_and_bonds_in_taxable_only():
    pos = [{**p("O", "Brokerage", 1000), "price": 50.0, "shares": 20},      # $3/yr on $50 = 6%
           {**p("O", "Roth IRA", 1000), "price": 50.0, "shares": 20},       # same yield, sheltered
           p("NVDA", "Brokerage", 1000),                                    # ~0% yield
           p("BND", "Brokerage", 1000)]                                     # bond fund
    r = run(pos, div={"O": 3.0, "NVDA": 0.04})
    names = [(x["ticker"], x["account"]) for x in r["location"]]
    assert ("O", "Brokerage") in names           # 6% yield in a taxable account
    assert ("O", "Roth IRA") not in names        # sheltered: fine
    assert ("NVDA", "Brokerage") not in names
    assert ("BND", "Brokerage") in names         # bond fund interest is ordinary income


def test_allocation_uses_injected_classifier():
    r = run([p("BND", "B", 100), p("VXUS", "B", 100), p("VTI", "B", 800)])
    assert r["allocation"] == {"US Equity": 80.0, "Bonds": 10.0, "International": 10.0}


def test_empty_portfolio_is_safe():
    r = run([])
    assert r["total"] == 0 and r["top"] == [] and r["effectiveN"] is None


def test_risk_passthrough_and_json_safe():
    r = run([p("VTI", "B", 100)], risk={"sharpe": 1.1, "maxDrawdown": -12.0, "benchmarkSharpe": 0.9,
                                       "sortino": None, "coverage": 100})
    assert r["risk"]["sharpe"] == 1.1
    json.dumps(r, allow_nan=False)


def test_nan_values_are_dropped_not_propagated():
    r = run([p("A", "B", float("nan")), p("VTI", "B", 100)])
    assert r["total"] == 100
    json.dumps(r, allow_nan=False)


def test_individual_stock_share_excludes_funds_and_ranks_stocks_only():
    r = run([p("VOO", "B", 600), p("NVDA", "B", 200), p("MU", "B", 150), p("FXAIX", "H", 50)])
    assert r["stocksPct"] == pytest.approx(35.0)
    assert [s["ticker"] for s in r["topStocks"]] == ["NVDA", "MU"]
    assert r["topStocks"][0]["pct"] == pytest.approx(20.0)
