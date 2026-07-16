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


def test_sync_balances_noop_without_plaid(client):
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
