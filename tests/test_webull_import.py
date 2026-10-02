"""Tests for scripts/webull_import.py — loads Webull connector data into the
holdings CSVs / accounts.json / portfolio.json. Everything runs in tmp_path;
the real data files are never touched."""

import csv
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import accounts as ac  # noqa: E402
import webull_import as wi  # noqa: E402


def pos(sym, qty, cost_price, value):
    return {"symbol": sym, "quantity": str(qty), "cost_price": str(cost_price),
            "market_value": str(value), "instrument_type": "EQUITY"}


def bal(market_value, cash):
    return {"total_market_value": str(market_value), "total_cash_balance": str(cash)}


def payload(**over):
    p = {"accounts": [
        {"account_class": "INDIVIDUAL_CASH", "balance": bal(1500.0, 136.54),
         "positions": [pos("VOO", 2, 500.0, 1000.0), pos("AAPL", 2, 200.0, 500.0)]},
        {"account_class": "ROTH_IRA", "balance": bal(300.0, 13.03),
         "positions": [pos("BRKB", 1, 400.0, 300.0)]},
        {"account_class": "INDIVIDUAL_CASH", "balance": {"total_market_value": "0.00"}, "positions": []},
    ]}
    p.update(over)
    return p


@pytest.fixture
def env(tmp_path):
    root = tmp_path
    (root / "brokerage_holdings.csv").write_text("ticker,shares,avg_cost\nVOO,1,450.0\n")
    (root / "roth_ira_holdings.csv").write_text("ticker,shares,avg_cost\nBRK-B,1,400.0\n")
    (root / "hsa_holdings.csv").write_text("ticker,shares,avg_cost\nFXAIX,5,250.0\n")
    acct = root / "accounts.json"
    acct.write_text(json.dumps({"accounts": [
        {"name": "Webull Cash", "type": "Other Asset", "balance": 251.65, "notes": "", "updated": "2026-08-31"},
        {"name": "RoboInvestor", "type": "Taxable", "balance": 840.5, "notes": "", "updated": "2026-10-02"}]}))
    return root, str(acct), str(root / "portfolio.json")


def read_csv(path):
    return {r["ticker"]: (float(r["shares"]), float(r["avg_cost"])) for r in csv.DictReader(open(path))}


def run(env, p=None):
    root, acct, port = env
    return wi.import_webull(p or payload(), str(root), accounts_path=acct, portfolio_path=port)


def test_writes_both_csvs_and_normalizes_class_b_ticker(env):
    root = env[0]
    run(env)
    assert read_csv(root / "brokerage_holdings.csv") == {"VOO": (2.0, 500.0), "AAPL": (2.0, 200.0)}
    assert read_csv(root / "roth_ira_holdings.csv") == {"BRK-B": (1.0, 400.0)}  # BRKB -> BRK-B


def test_updates_webull_cash_and_leaves_other_manual_accounts(env):
    _, acct, _ = env
    run(env)
    by = {a["name"]: a for a in ac.load_accounts(acct)}
    assert by["Webull Cash"]["balance"] == 136.54
    assert by["RoboInvestor"]["balance"] == 840.5  # not visible via Webull API: untouched


def test_rebuilds_combined_and_portfolio_and_keeps_hsa(env):
    root, _, port = env
    run(env)
    tickers = {(r["account"], r["ticker"]) for r in csv.DictReader(open(root / "combined_holdings.csv"))}
    assert ("brokerage", "VOO") in tickers and ("roth", "BRK-B") in tickers and ("hsa", "FXAIX") in tickers
    assert json.load(open(port))  # portfolio.json written


def test_empty_third_account_is_ignored(env):
    result = run(env)
    assert result["ok"] is True
    assert result["positions"] == {"brokerage": 2, "roth": 1}


def test_aborts_and_writes_nothing_when_totals_do_not_match(env):
    root = env[0]
    bad = payload()
    bad["accounts"][0]["balance"] = bal(9999.0, 0)  # positions sum to 1500
    before = (root / "brokerage_holdings.csv").read_text()
    with pytest.raises(wi.ImportAbort):
        run(env, bad)
    assert (root / "brokerage_holdings.csv").read_text() == before
    assert not (root / "backups").exists()


def test_aborts_when_an_expected_account_is_missing(env):
    root = env[0]
    p = payload()
    p["accounts"] = [a for a in p["accounts"] if a["account_class"] != "ROTH_IRA"]
    before = (root / "roth_ira_holdings.csv").read_text()
    with pytest.raises(wi.ImportAbort):
        run(env, p)  # half an update must never be written
    assert (root / "roth_ira_holdings.csv").read_text() == before


def test_aborts_on_garbage_position(env):
    p = payload()
    p["accounts"][0]["positions"][0]["quantity"] = "not-a-number"
    with pytest.raises(wi.ImportAbort):
        run(env, p)


def test_backs_up_previous_files_before_overwriting(env):
    root = env[0]
    run(env)
    backups = list((root / "backups").iterdir())
    assert len(backups) == 1
    assert "VOO,1,450.0" in (backups[0] / "brokerage_holdings.csv").read_text()
    assert (backups[0] / "accounts.json").exists()


def test_reports_changes_against_previous_holdings(env):
    result = run(env)
    ch = result["changes"]["brokerage"]
    assert ch["added"] == ["AAPL"] and ch["removed"] == []
    assert ch["resized"] == [("VOO", 1.0, 2.0)]


def test_aborts_when_a_quantity_disagrees_with_its_own_market_value(env):
    # A mistyped share count is caught per position even if the account total
    # still looks plausible: quantity x last_price must match market_value.
    p = payload()
    p["accounts"][0]["positions"][0].update(last_price="500.0")           # 2 sh x 500 = 1000 == value: ok
    p["accounts"][0]["positions"][1].update(last_price="250.0", quantity="3")  # 3 x 250 = 750, value says 500
    p["accounts"][0]["balance"] = bal(1500.0, 136.54)
    with pytest.raises(wi.ImportAbort, match="AAPL"):
        run(env, p)


def test_positions_without_last_price_still_import(env):
    result = run(env)  # fixture positions carry no last_price: the check is skipped, not failed
    assert result["ok"] is True


def test_consistent_last_price_passes(env):
    p = payload()
    p["accounts"][0]["positions"][0].update(last_price="500.0")
    p["accounts"][0]["positions"][1].update(last_price="250.0")
    assert run(env, p)["ok"] is True
