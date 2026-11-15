"""plaid_sync.pull_investment_activity(): rebuild investment_flows.json from Plaid
investment transactions. Fake client; no network, no real files."""

import datetime
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import plaid_sync  # noqa: E402
import investment_flows as fl  # noqa: E402

TODAY = datetime.date.today().isoformat()


def itx(account, subtype, amount, type_="cash", date=None):
    return {"account_id": account, "type": type_, "subtype": subtype, "amount": amount,
            "date": date or TODAY}


class FakeClient:
    def __init__(self, items):
        self.items = items          # token -> {"accounts": {id: subtype}, "txs": [...]} or an Exception
        self.calls = []

    def _item(self, request):
        item = self.items[request["access_token"]]
        if isinstance(item, Exception):
            raise item
        return item

    def accounts_get(self, request):
        item = self._item(request)
        return {"accounts": [{"account_id": k, "subtype": v} for k, v in item["accounts"].items()]}

    def investments_transactions_get(self, request):
        item = self._item(request)
        off, cnt = request["options"]["offset"], request["options"]["count"]
        self.calls.append(off)
        return {"investment_transactions": item["txs"][off:off + cnt],
                "total_investment_transactions": len(item["txs"])}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(fl, "FLOWS_FILE", str(tmp_path / "flows.json"))
    monkeypatch.setattr(plaid_sync, "HAS_PLAID", True)
    monkeypatch.setattr(plaid_sync, "PLAID_ACCESS_TOKENS", ["tokA", "tokB"])

    def install(items):
        fake = FakeClient(items)
        monkeypatch.setattr(plaid_sync, "_make_client", lambda: fake)
        return fake
    return install


def test_noop_when_not_configured(monkeypatch):
    monkeypatch.setattr(plaid_sync, "HAS_PLAID", False)
    assert plaid_sync.pull_investment_activity()["ok"] is False


def test_builds_flows_from_the_investment_item_and_skips_the_bank_item(env):
    no_inv = RuntimeError('{"error_code": "PRODUCTS_NOT_SUPPORTED"}')
    env({"tokA": {"accounts": {"a1": "401k", "h1": "hsa"},
                  "txs": [itx("a1", "contribution", -500.0), itx("h1", "deposit", -150.0),
                          itx("h1", "dividend", -1.0), itx("a1", "buy", 500.0, type_="buy")]},
         "tokB": no_inv})
    r = plaid_sync.pull_investment_activity()
    assert r["ok"] is True and r["items_synced"] == 1 and len(r["skipped"]) == 1
    y = fl.ytd(fl.load(), datetime.date.today().year)
    assert y["401k"]["contributions"] == 500.0 and y["hsa"]["contributions"] == 150.0
    assert fl.load()["synced_at"] == TODAY


def test_paginates_large_histories(env):
    txs = [itx("a1", "contribution", -1.0) for _ in range(1203)]
    fake = env({"tokA": {"accounts": {"a1": "401k"}, "txs": txs}, "tokB": RuntimeError('{"error_code": "PRODUCTS_NOT_SUPPORTED"}')})
    plaid_sync.pull_investment_activity()
    assert fake.calls == [0, 500, 1000]
    assert fl.ytd(fl.load(), datetime.date.today().year)["401k"]["contributions"] == 1203.0


def test_a_failing_item_leaves_the_stored_flows_untouched(env):
    fl.save({"months": {"2026-01": {"401k": {"contributions": 1.0, "dividends": 0.0, "withdrawals": 0.0}}},
             "synced_at": "2026-01-02"})
    env({"tokA": RuntimeError('{"error_code": "ITEM_LOGIN_REQUIRED"}'),
         "tokB": {"accounts": {"a1": "401k"}, "txs": [itx("a1", "contribution", -9.0)]}})
    r = plaid_sync.pull_investment_activity()
    assert r["ok"] is False and "ITEM_LOGIN_REQUIRED" in r["reason"]
    assert fl.load()["synced_at"] == "2026-01-02"             # not overwritten with a partial picture


def test_nothing_synced_does_not_overwrite_existing_flows(env):
    fl.save({"months": {"2026-01": {}}, "synced_at": "2026-01-02"})
    skip = RuntimeError('{"error_code": "PRODUCTS_NOT_SUPPORTED"}')
    env({"tokA": skip, "tokB": skip})
    r = plaid_sync.pull_investment_activity()
    assert r["ok"] is True and r["items_synced"] == 0
    assert fl.load()["synced_at"] == "2026-01-02"


def test_malformed_transaction_fails_loudly_and_stores_nothing(env):
    env({"tokA": {"accounts": {"a1": "401k"}, "txs": [itx("a1", "contribution", "oops")]},
         "tokB": RuntimeError('{"error_code": "PRODUCTS_NOT_SUPPORTED"}')})
    r = plaid_sync.pull_investment_activity()
    assert r["ok"] is False and fl.load()["synced_at"] is None


def test_tokens_never_leak_into_the_result(env):
    env({"tokA": {"accounts": {"a1": "401k"}, "txs": []}, "tokB": RuntimeError('{"error_code": "PRODUCTS_NOT_SUPPORTED"}')})
    assert "tokA" not in str(plaid_sync.pull_investment_activity())
