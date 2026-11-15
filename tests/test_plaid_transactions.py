"""plaid_sync.pull_transactions(): per-Item incremental sync into transactions.py.
Uses a fake Plaid client; never touches the network or real files."""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import plaid_sync  # noqa: E402
import transactions as tx  # noqa: E402


def txn(i, amount=10.0, date="2026-11-02", cat="FOOD_AND_DRINK"):
    return {"transaction_id": i, "account_id": "acc", "date": date, "amount": amount, "name": "X",
            "merchant_name": "X", "pending": False,
            "personal_finance_category": {"primary": cat, "detailed": ""}}


class FakeClient:
    """behaviour[token] -> callable(cursor) returning a page dict or raising."""
    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.seen = []

    def transactions_sync(self, request):
        token, cursor = request["access_token"], (request["cursor"] if "cursor" in request else None)
        self.seen.append((token, cursor))
        return self.behaviour[token](cursor)


def page(added=(), nc="n1", more=False):
    return {"added": list(added), "modified": [], "removed": [], "next_cursor": nc, "has_more": more}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(tx, "TX_FILE", str(tmp_path / "transactions.json"))
    monkeypatch.setattr(plaid_sync, "HAS_PLAID", True)
    monkeypatch.setattr(plaid_sync, "PLAID_ACCESS_TOKENS", ["tokA", "tokB"])

    def install(behaviour):
        fake = FakeClient(behaviour)
        monkeypatch.setattr(plaid_sync, "_make_client", lambda: fake)
        return fake
    return install


def test_noop_when_plaid_not_configured(monkeypatch):
    monkeypatch.setattr(plaid_sync, "HAS_PLAID", False)
    r = plaid_sync.pull_transactions()
    assert r["ok"] is False and "not configured" in r["reason"].lower()


def test_syncs_each_item_and_stores_cursors_by_hash(env):
    env({"tokA": lambda c: page([txn("a1")], "cA"), "tokB": lambda c: page([txn("b1"), txn("b2")], "cB")})
    r = plaid_sync.pull_transactions()
    assert r["ok"] is True and r["added"] == 3 and r["items_synced"] == 2
    data = tx.load()
    assert set(data["txns"]) == {"a1", "b1", "b2"}
    assert data["cursors"] == {tx.item_key("tokA"): "cA", tx.item_key("tokB"): "cB"}


def test_second_run_resumes_from_saved_cursor(env):
    fake = env({"tokA": lambda c: page([], "cA2"), "tokB": lambda c: page([], "cB2")})
    tx.apply_sync(tx.item_key("tokA"), [], [], [], "cA1")
    plaid_sync.pull_transactions()
    assert ("tokA", "cA1") in fake.seen and ("tokB", None) in fake.seen


def test_item_without_transactions_consent_is_skipped_not_failed(env):
    def no_consent(c):
        raise RuntimeError('{"error_code": "ADDITIONAL_CONSENT_REQUIRED"}')
    env({"tokA": lambda c: page([txn("a1")], "cA"), "tokB": no_consent})
    r = plaid_sync.pull_transactions()
    assert r["ok"] is True and r["items_synced"] == 1 and len(r["skipped"]) == 1
    assert r["errors"] == []


@pytest.mark.parametrize("code", ["INVALID_PRODUCT", "PRODUCTS_NOT_SUPPORTED", "PRODUCT_NOT_READY"])
def test_other_not_available_codes_are_skips(env, code):
    def nope(c):
        raise RuntimeError(f'{{"error_code": "{code}"}}')
    env({"tokA": nope, "tokB": nope})
    r = plaid_sync.pull_transactions()
    assert r["ok"] is True and r["items_synced"] == 0 and len(r["skipped"]) == 2


def test_real_errors_fail_the_run_but_other_items_still_sync(env):
    def login(c):
        raise RuntimeError('{"error_code": "ITEM_LOGIN_REQUIRED"}')
    env({"tokA": login, "tokB": lambda c: page([txn("b1")], "cB")})
    r = plaid_sync.pull_transactions()
    assert r["ok"] is False and "ITEM_LOGIN_REQUIRED" in r["errors"][0]
    assert set(tx.load()["txns"]) == {"b1"}


def test_malformed_page_stores_nothing_and_keeps_old_cursor(env):
    env({"tokA": lambda c: {"added": [txn("a1", amount="oops")], "modified": [], "removed": [],
                            "next_cursor": "cNEW", "has_more": False},
         "tokB": lambda c: page([], "cB")})
    tx.apply_sync(tx.item_key("tokA"), [txn("keep")], [], [], "cOLD")
    r = plaid_sync.pull_transactions()
    assert r["ok"] is False
    assert set(tx.load()["txns"]) == {"keep"} and tx.get_cursor(tx.item_key("tokA")) == "cOLD"


def test_tokens_never_appear_in_results_or_the_file(env):
    env({"tokA": lambda c: page([txn("a1")], "cA"), "tokB": lambda c: page([], "cB")})
    r = plaid_sync.pull_transactions()
    assert "tokA" not in str(r) and "tokA" not in open(tx.TX_FILE).read()


# --- Link request construction (scripts/plaid_link.py uses this) ---------------------
def test_new_link_defaults_to_investments_like_before():
    assert plaid_sync.link_request_kwargs() == {"products": ["investments"]}


def test_new_link_for_a_bank_can_request_transactions():
    assert plaid_sync.link_request_kwargs(products=["transactions"]) == {"products": ["transactions"]}


def test_update_mode_adds_consent_to_an_existing_item_without_new_products():
    kw = plaid_sync.link_request_kwargs(update_index=1, tokens=["tA", "tB"], products=["transactions"])
    assert kw == {"access_token": "tB", "additional_consented_products": ["transactions"]}
    assert "products" not in kw


@pytest.mark.parametrize("kwargs", [
    {"products": ["crypto"]}, {"products": []},
    {"update_index": 5, "tokens": ["tA"], "products": ["transactions"]},
    {"update_index": -1, "tokens": ["tA"], "products": ["transactions"]},
    {"update_index": 0, "tokens": [], "products": ["transactions"]},
])
def test_bad_link_requests_are_rejected(kwargs):
    with pytest.raises(ValueError):
        plaid_sync.link_request_kwargs(**kwargs)


def test_item_still_preparing_history_is_skipped_not_failed(env):
    env({"tokA": lambda c: page([], nc=""), "tokB": lambda c: page([txn("b1")], "cB")})
    r = plaid_sync.pull_transactions()
    assert r["ok"] is True and r["items_synced"] == 1
    assert len(r["skipped"]) == 1 and "not ready" in r["skipped"][0].lower() and r["errors"] == []
    assert tx.get_cursor(tx.item_key("tokA")) is None            # nothing stored; retried tomorrow
