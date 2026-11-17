"""API tests for the screenshot-import routes. The vision model is faked and
every data file lives in tmp_path."""

import io
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import accounts as ac  # noqa: E402
import config  # noqa: E402
import screenshot_import as si  # noqa: E402
import server  # noqa: E402

RAW = {"accounts": [{
    "institution": "Webull", "account_label": "Individual Cash",
    "total_value": "1540", "positions_total": "1500", "cash": "40",
    "positions": [{"symbol": "VOO", "quantity": "2", "last_price": "500", "market_value": "1000",
                   "avg_cost": "450"},
                  {"symbol": "AAPL", "quantity": "2", "last_price": "250", "market_value": "500",
                   "avg_cost": "200"}]}]}


def png_bytes():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 30)).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def env(tmp_path, monkeypatch):
    (tmp_path / "brokerage_holdings.csv").write_text("ticker,shares,avg_cost\nAAPL,2,200.0\nVOO,1,450.0\n")
    (tmp_path / "roth_ira_holdings.csv").write_text("ticker,shares,avg_cost\nBRK-B,1,400.0\n")
    (tmp_path / "hsa_holdings.csv").write_text("ticker,shares,avg_cost\nFXAIX,5,250.0\n")
    accts = tmp_path / "accounts.json"
    accts.write_text(json.dumps({"accounts": [
        {"name": "Webull Cash", "type": "Other Asset", "balance": 251.65, "notes": "", "updated": "2026-08-31"},
        {"name": "RoboInvestor", "type": "Taxable", "balance": 840.5, "notes": "", "updated": "2026-10-02"},
        {"name": "TOTAL CHECKING", "type": "Checking", "balance": 3500.0, "notes": "",
         "updated": "2026-11-14", "source": "plaid", "plaid_account_id": "abc"}]}))
    pf = tmp_path / "portfolio.json"
    pf.write_text(json.dumps({"holdings": []}))
    monkeypatch.setattr(server, "DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(ac, "ACCOUNTS_FILE", str(accts))
    monkeypatch.setattr(config, "PORTFOLIO_FILE", str(pf))
    monkeypatch.setattr(server, "_refresh_after_holdings_change", lambda holdings: None)
    monkeypatch.setattr(si, "ollama_vision", lambda image, **kw: RAW)
    return tmp_path


@pytest.fixture
def client():
    server.app.config["TESTING"] = True
    with server.app.test_client() as c:
        yield c


def upload(client, data=None, name="shot.png", **kw):
    return client.post("/api/screenshot/parse",
                       data={"file": (io.BytesIO(png_bytes() if data is None else data), name)},
                       content_type="multipart/form-data", **kw)


def item(positions, bucket="brokerage", mode="merge", **account):
    return {"target": {"type": "holdings", "bucket": bucket}, "mode": mode,
            "account": {"positions": positions, **account}}


VOO2 = {"symbol": "VOO", "quantity": 2, "price": 500, "value": 1000, "avg_cost": 450}


# --- parse -------------------------------------------------------------------------
def test_parse_returns_accounts_with_suggested_targets(client, env):
    r = upload(client)
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True
    [a] = d["accounts"]
    assert a["suggested"] == {"type": "holdings", "bucket": "brokerage"}
    assert [p["symbol"] for p in a["positions"]] == ["VOO", "AAPL"]
    assert d["targets"]["manual"] == ["Webull Cash", "RoboInvestor"]  # Plaid-synced one is not offered
    assert {t["bucket"] for t in d["targets"]["holdings"]} == {"brokerage", "roth"}


def test_parse_never_writes_anything(client, env):
    before = {n: (env / n).read_bytes() for n in os.listdir(env)}
    upload(client)
    assert {n: (env / n).read_bytes() for n in os.listdir(env)} == before


def test_parse_without_a_file_is_400(client, env):
    r = client.post("/api/screenshot/parse", data={}, content_type="multipart/form-data")
    assert r.status_code == 400 and r.get_json()["ok"] is False


def test_parse_rejects_non_images(client, env):
    r = upload(client, data=b"<html>hi</html>", name="x.png")
    assert r.status_code == 400 and r.get_json()["ok"] is False


def test_parse_reports_when_ollama_is_down(client, env, monkeypatch):
    def down(image, **kw):
        raise si.ExtractError("Ollama is not reachable at http://localhost:11434")
    monkeypatch.setattr(si, "ollama_vision", down)
    r = upload(client)
    assert r.status_code == 503 and "ollama" in r.get_json()["error"].lower()


def test_parse_unreadable_screenshot_is_422(client, env, monkeypatch):
    monkeypatch.setattr(si, "ollama_vision", lambda image, **kw: {"accounts": []})
    r = upload(client)
    assert r.status_code == 422


def test_parse_is_one_at_a_time(client, env):
    assert server._screenshot_lock.acquire(blocking=False)
    try:
        assert upload(client).status_code == 429
    finally:
        server._screenshot_lock.release()
    assert upload(client).status_code == 200  # lock released after the busy rejection


def test_parse_releases_the_lock_after_a_failure(client, env, monkeypatch):
    def down(image, **kw):
        raise si.ExtractError("boom")
    monkeypatch.setattr(si, "ollama_vision", down)
    assert upload(client).status_code == 503
    monkeypatch.setattr(si, "ollama_vision", lambda image, **kw: RAW)
    assert upload(client).status_code == 200


# --- cross-site protection -----------------------------------------------------------
def test_foreign_origin_is_refused_on_every_route(client, env):
    bad = {"Origin": "http://evil.example"}
    assert upload(client, headers=bad).status_code == 403
    for path in ("preview", "apply"):
        r = client.post(f"/api/screenshot/{path}", json={"items": []}, headers=bad)
        assert r.status_code == 403


def test_same_origin_is_allowed(client, env):
    ok = {"Origin": "http://localhost"}
    assert upload(client, headers=ok).status_code == 200


def test_json_routes_require_a_json_content_type(client, env):
    # text/plain is a "simple" cross-site request that skips the CORS preflight.
    r = client.post("/api/screenshot/apply", data=json.dumps({"items": [item([VOO2])]}),
                    content_type="text/plain")
    assert r.status_code == 415
    assert "VOO,2" not in (env / "brokerage_holdings.csv").read_text()


# --- preview -------------------------------------------------------------------------
def test_preview_returns_the_plan_without_writing(client, env):
    before = {n: (env / n).read_bytes() for n in os.listdir(env)}
    r = client.post("/api/screenshot/preview", json={"items": [item([VOO2])]})
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True and d["changes"][0]["rows"][0]["status"] == "resized"
    assert {n: (env / n).read_bytes() for n in os.listdir(env)} == before


def test_preview_reports_errors_without_failing_the_request(client, env):
    d = client.post("/api/screenshot/preview", json={"items": []}).get_json()
    assert d["ok"] is False and d["errors"]


def test_preview_with_garbage_body_is_400(client, env):
    r = client.post("/api/screenshot/preview", data="not json", content_type="application/json")
    assert r.status_code == 400


# --- apply ---------------------------------------------------------------------------
def test_apply_writes_and_reports(client, env):
    r = client.post("/api/screenshot/apply", json={"items": [item([VOO2], cash=12.5)]})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert "VOO,2.0,450.0" in (env / "brokerage_holdings.csv").read_text()
    assert json.loads((env / "accounts.json").read_text())["accounts"][0]["balance"] == 12.5
    assert any(h["ticker"] == "VOO" for h in json.load(open(env / "portfolio.json"))["holdings"])


def test_apply_with_errors_is_422_and_writes_nothing(client, env):
    before = {n: (env / n).read_bytes() for n in os.listdir(env)}
    r = client.post("/api/screenshot/apply", json={"items": [item([])]})
    assert r.status_code == 422 and r.get_json()["errors"]
    assert {n: (env / n).read_bytes() for n in os.listdir(env)} == before


def test_apply_asks_for_confirmation_on_warnings(client, env):
    bad = dict(VOO2, value=1100)
    r = client.post("/api/screenshot/apply", json={"items": [item([bad])]})
    assert r.status_code == 409
    d = r.get_json()
    assert d["needs_confirmation"] is True and d["warnings"]
    assert "VOO,2" not in (env / "brokerage_holdings.csv").read_text()
    r = client.post("/api/screenshot/apply", json={"items": [item([bad])], "accept_warnings": True})
    assert r.status_code == 200


def test_apply_invalidates_the_dashboard_cache(client, env):
    server._data_cache_ts = 12345.0
    client.post("/api/screenshot/apply", json={"items": [item([VOO2])]})
    assert server._data_cache_ts == 0.0


def test_oversize_json_body_is_rejected(client, env):
    big = {"items": [item([VOO2])], "pad": "x" * (2 * 1024 * 1024)}
    r = client.post("/api/screenshot/apply", data=json.dumps(big), content_type="application/json")
    assert r.status_code == 413
