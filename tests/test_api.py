"""Smoke tests for NexusAI — API routes + advisor/snapshot logic.

Run: .venv/bin/python3 -m pytest tests/ -q
Network-light: uses cached data; does not assert on live yfinance calls.
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import server  # noqa: E402
import nw_snapshots  # noqa: E402
import accounts as ac  # noqa: E402


@pytest.fixture
def client():
    server.app.config["TESTING"] = True
    with server.app.test_client() as c:
        yield c


# --- Routes ----------------------------------------------------------------
def test_index_ok(client):
    assert client.get("/").status_code == 200


def test_data_js(client):
    r = client.get("/data.js")
    assert r.status_code == 200
    assert b"NEXUS_DATA" in r.data


def test_snapshot_shape(client):
    r = client.get("/api/snapshot")
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True
    assert isinstance(d["positions"], list)
    assert "riskMetrics" in d and "advisorPlan" in d


def test_analyze_rejects_bad_ticker(client):
    r = client.get("/api/analyze/BAD!TICKER")
    assert r.status_code == 400
    assert r.get_json()["ok"] is False


def test_sync_balances_noop_without_plaid(client, monkeypatch):
    # Force "unconfigured" — with real Plaid keys in .env this route would
    # otherwise run a live sync and rewrite accounts.json on every test run.
    import plaid_sync
    monkeypatch.setattr(plaid_sync, "HAS_PLAID", False)
    r = client.post("/api/sync-balances")
    d = r.get_json()
    assert d["ok"] is False  # Plaid not configured by default


def test_chat_empty_message(client):
    r = client.post("/api/chat", json={"message": "", "history": []})
    assert r.status_code == 400


# --- Advisor math ----------------------------------------------------------
def test_classify_asset_class():
    assert server._classify_asset_class("VXUS", "ETF") == "International"
    assert server._classify_asset_class("BND", "Bond ETF") == "Bonds"
    assert server._classify_asset_class("GLD", "Commodities") == "Real Assets & Crypto"
    assert server._classify_asset_class("AAPL", "Technology") == "US Equity"
    assert server._classify_asset_class("SGOV", "Cash/T-Bills") == "Cash"


def test_advisor_targets_sum_100():
    positions = [
        {"ticker": "AAPL", "sector": "Technology", "weight": 60.0, "value": 60000, "plPct": 20},
        {"ticker": "VXUS", "sector": "ETF · International", "weight": 40.0, "value": 40000, "plPct": 5},
    ]
    plan = server._advisor_plan(positions, {"risk_tolerance": "aggressive", "horizon_years": 30})
    cur_sum = sum(t["current"] for t in plan["targets"])
    tgt_sum = sum(t["target"] for t in plan["targets"])
    assert 99 <= cur_sum <= 101
    assert 99 <= tgt_sum <= 101
    assert len(plan["actions"]) >= 1


def test_advisor_empty_portfolio():
    plan = server._advisor_plan([], {"risk_tolerance": "moderate", "horizon_years": 10})
    assert "targets" in plan and "actions" in plan  # no crash on empty


# --- Snapshots -------------------------------------------------------------
def test_snapshot_roundtrip(tmp_path, monkeypatch):
    f = tmp_path / "nw.json"
    monkeypatch.setattr(nw_snapshots, "SNAPSHOT_FILE", str(f))
    nw_snapshots.record_snapshot(100000, 80000, 20000, 0)
    nw_snapshots.record_snapshot(105000, 85000, 20000, 0)  # same month → update
    hist = nw_snapshots.load_history()
    assert len(hist) == 1  # one bucket per month
    assert hist[0]["value"] == 105000


# --- Accounts --------------------------------------------------------------
def test_account_coerce_adds_timestamp():
    out = ac._coerce([{"name": "HYSA", "type": "HYSA", "balance": 1000}])
    assert out[0]["updated"]  # auto-stamped
    assert out[0]["balance"] == 1000.0


def test_account_liability_detection():
    assert ac.is_liability("Credit Card")
    assert not ac.is_liability("HYSA")


# --- Price cache resilience ------------------------------------------------
# A failed yfinance fetch must never replace a good cached price with None:
# the dashboard values a None-priced position at cost basis (avg_cost), which
# silently understates net worth (found 2026-09-23: MU/TQQQ/FFLEX/FXAIX).
@pytest.fixture
def price_env(tmp_path, monkeypatch):
    """Isolated price cache — never touches the real price_cache.json or
    prunes against the real portfolio."""
    monkeypatch.setattr(server, "PRICE_CACHE_FILE", str(tmp_path / "price_cache.json"))
    monkeypatch.setattr(server, "_known_tickers", lambda: set())
    monkeypatch.setattr(server, "_pcache", {})
    monkeypatch.setattr(server, "_pcache_ts", {})


def test_batch_prices_keeps_last_good_price_when_refresh_fails(price_env, monkeypatch):
    import data as data_mod
    import pandas as pd
    server._pcache["AAA"] = 10.0
    server._pcache_ts["AAA"] = 0.0  # expired -> forces a refresh
    monkeypatch.setattr("yfinance.download", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(data_mod, "latest_price", lambda t: None)
    assert server.batch_prices(["AAA"]) == {"AAA": 10.0}


def test_batch_prices_retries_missed_ticker_individually(price_env, monkeypatch):
    import data as data_mod
    import pandas as pd
    raw = pd.DataFrame({("Close", "AAA"): [1.0, 2.0], ("Close", "BBB"): [float("nan"), float("nan")]})
    monkeypatch.setattr("yfinance.download", lambda *a, **k: raw)
    monkeypatch.setattr(data_mod, "latest_price", lambda t: {"BBB": 42.5}.get(t))
    assert server.batch_prices(["AAA", "BBB"]) == {"AAA": 2.0, "BBB": 42.5}


def test_failed_price_is_retried_soon_not_after_full_ttl(price_env, monkeypatch):
    import time
    import data as data_mod
    import pandas as pd
    monkeypatch.setattr("yfinance.download", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(data_mod, "latest_price", lambda t: None)
    server.batch_prices(["AAA"])
    seconds_until_retry = server.config.CACHE_TTL_SECONDS - (time.time() - server._pcache_ts["AAA"])
    assert seconds_until_retry <= 120  # not stuck as None for the whole 15-min TTL


def test_unpriced_tickers_reports_missing_prices(price_env):
    server._pcache.update({"AAA": 1.0, "BBB": None})
    assert server._unpriced_tickers([{"ticker": "AAA"}, {"ticker": "BBB"}, {"ticker": "CCC"}]) == ["BBB", "CCC"]


def test_snapshot_not_overwritten_when_prices_incomplete(tmp_path, monkeypatch):
    f = tmp_path / "nw.json"
    monkeypatch.setattr(nw_snapshots, "SNAPSHOT_FILE", str(f))
    nw_snapshots.record_snapshot(100000, 80000, 20000, 0)
    server._net_worth_history(90000.0, 70000.0, [], prices_complete=False)
    assert nw_snapshots.load_history()[-1]["value"] == 100000  # bad low number not persisted
    server._net_worth_history(105000.0, 85000.0, [], prices_complete=True)
    assert nw_snapshots.load_history()[-1]["value"] == 105000  # complete data still updates


def test_data_js_exposes_prices_incomplete(client):
    assert b"pricesIncomplete" in client.get("/data.js").data


def test_none_price_is_not_treated_as_fresh_for_full_ttl(price_env, monkeypatch):
    # A None entry (e.g. persisted by an older run, or a failed fetch) must
    # be retried after the short retry window, not held for the full 15-min
    # TTL. Stamped 2 min ago = well inside the TTL, past the 60s retry window
    # (the real case: a failure persisted at 09:49, server restarted 09:53).
    import time
    import data as data_mod
    import pandas as pd
    server._pcache["AAA"] = None
    server._pcache_ts["AAA"] = time.time() - 120
    monkeypatch.setattr("yfinance.download", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(data_mod, "latest_price", lambda t: 7.5)
    assert server.batch_prices(["AAA"]) == {"AAA": 7.5}


def test_unpriced_tickers_lists_each_ticker_once(price_env):
    # A ticker held in two accounts appears as two holdings rows.
    server._pcache.update({"AAA": None})
    assert server._unpriced_tickers([{"ticker": "AAA"}, {"ticker": "AAA"}]) == ["AAA"]


@pytest.fixture(scope="session", autouse=True)
def _isolate_user_data(tmp_path_factory):
    """Keep the suite off the live price/period/risk caches and net-worth
    history — route/build tests run real builds that would otherwise write
    (and, with a flaky yfinance, poison) the user's real files."""
    d = tmp_path_factory.mktemp("userdata")
    mp = pytest.MonkeyPatch()
    mp.setattr(server, "PRICE_CACHE_FILE", str(d / "price_cache.json"))
    mp.setattr(server, "PERIOD_CACHE_FILE", str(d / "period_cache.json"))
    mp.setattr(server, "RISK_CACHE_FILE", str(d / "risk_cache.json"))
    mp.setattr(nw_snapshots, "SNAPSHOT_FILE", str(d / "nw_history.json"))
    yield
    mp.undo()
