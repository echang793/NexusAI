"""transactions.py: validated local store for Plaid /transactions/sync data.
Bad payloads must raise (never store partial/garbled data); the cursor only
advances when a whole sync was applied."""

import datetime
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import transactions as tx  # noqa: E402


def t(i="t1", date="2026-11-03", amount=12.5, name="COFFEE SHOP", cat="FOOD_AND_DRINK",
      detailed="FOOD_AND_DRINK_COFFEE", account="acc1", pending=False, **extra):
    return {"transaction_id": i, "account_id": account, "date": date, "amount": amount,
            "name": name, "merchant_name": name.title(), "pending": pending,
            "personal_finance_category": {"primary": cat, "detailed": detailed}, **extra}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(tx, "TX_FILE", str(tmp_path / "transactions.json"))
    return tx


def test_added_transactions_are_stored_with_only_needed_fields(store):
    store.apply_sync("k", [t(location={"lat": 1.0}, counterparties=[{"x": 1}])], [], [], "c1")
    row = store.load()["txns"]["t1"]
    assert row == {"id": "t1", "account": "acc1", "date": "2026-11-03", "amount": 12.5,
                   "name": "COFFEE SHOP", "merchant": "Coffee Shop", "cat": "FOOD_AND_DRINK",
                   "detailed": "FOOD_AND_DRINK_COFFEE", "pending": False}


def test_modified_replaces_and_removed_deletes(store):
    store.apply_sync("k", [t("a"), t("b")], [], [], "c1")
    store.apply_sync("k", [], [t("a", amount=99.0)], [{"transaction_id": "b"}], "c2")
    txns = store.load()["txns"]
    assert txns["a"]["amount"] == 99.0 and "b" not in txns


def test_removing_an_unknown_id_is_not_an_error(store):
    store.apply_sync("k", [], [], [{"transaction_id": "ghost"}], "c1")


def test_cursor_is_stored_per_item_key(store):
    store.apply_sync("k1", [t("a")], [], [], "c1")
    store.apply_sync("k2", [t("b")], [], [], "z9")
    assert store.get_cursor("k1") == "c1" and store.get_cursor("k2") == "z9"
    assert store.get_cursor("nope") is None


@pytest.mark.parametrize("bad", [
    t(i=""), t(date="11/03/2026"), t(date=None), t(amount="abc"), t(amount=float("nan")),
    t(amount=float("inf")), t(amount=None),
])
def test_invalid_transaction_raises_and_nothing_is_written(store, bad):
    store.apply_sync("k", [t("keep")], [], [], "c0")
    with pytest.raises(store.TransactionsError):
        store.apply_sync("k", [t("new"), bad], [], [], "c1")
    assert set(store.load()["txns"]) == {"keep"}          # whole batch rejected
    assert store.get_cursor("k") == "c0"                  # cursor did not advance


def test_missing_lists_in_payload_are_an_error(store):
    with pytest.raises(store.TransactionsError):
        store.apply_sync("k", None, [], [], "c1")


def test_old_transactions_are_pruned(store, monkeypatch):
    monkeypatch.setattr(store, "KEEP_DAYS", 100)
    today = datetime.date.today()
    old = (today - datetime.timedelta(days=400)).isoformat()
    new = (today - datetime.timedelta(days=5)).isoformat()
    store.apply_sync("k", [t("old", date=old), t("new", date=new)], [], [], "c1")
    assert set(store.load()["txns"]) == {"new"}


def test_missing_or_corrupt_file_loads_empty(store):
    assert store.load() == {"cursors": {}, "txns": {}}
    open(store.TX_FILE, "w").write("{broken")
    assert store.load() == {"cursors": {}, "txns": {}}


def test_file_is_valid_json_without_nan_and_has_no_tmp_left(store):
    store.apply_sync("k", [t()], [], [], "c1")
    json.loads(open(store.TX_FILE).read())
    assert not os.path.exists(store.TX_FILE + ".tmp")


def test_item_key_never_contains_the_access_token():
    key = tx.item_key("access-production-abc123")
    assert "access" not in key and "abc123" not in key and len(key) == 12


def test_plaid_model_objects_and_date_objects_are_normalised():
    class Obj:
        def __init__(self, d): self._d = d
        def to_dict(self): return self._d
    raw = Obj({**t(), "date": datetime.date(2026, 11, 3)})
    assert tx.to_plain(raw)["date"] == "2026-11-03"


# --- paging ------------------------------------------------------------------------
def page(added=(), next_cursor="n", has_more=False, modified=(), removed=()):
    return {"added": list(added), "modified": list(modified), "removed": list(removed),
            "next_cursor": next_cursor, "has_more": has_more}


def test_fetch_all_follows_pages_and_returns_final_cursor():
    pages = iter([page([t("a")], "c1", True), page([t("b")], "c2", True), page([t("c")], "c3", False)])
    calls = []
    def sync(cursor):
        calls.append(cursor)
        return next(pages)
    added, modified, removed, cursor = tx.fetch_all(sync, None)
    assert [x["transaction_id"] for x in added] == ["a", "b", "c"]
    assert cursor == "c3" and calls == [None, "c1", "c2"]


def test_fetch_all_restarts_from_original_cursor_on_mutation_during_pagination():
    class Mutation(Exception):
        pass
    state = {"n": 0}
    calls = []
    def sync(cursor):
        calls.append(cursor)
        state["n"] += 1
        if state["n"] == 2:
            raise Mutation("TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION")
        return page([t(f"x{state['n']}")], f"c{state['n']}", state["n"] < 3 and state["n"] != 2)
    added, _, _, cursor = tx.fetch_all(sync, "orig")
    assert calls[0] == "orig" and calls[2] == "orig"      # second attempt restarted from the start
    assert cursor is not None


def test_fetch_all_gives_up_after_repeated_mutation_errors():
    def sync(cursor):
        raise RuntimeError("TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION")
    with pytest.raises(tx.TransactionsError):
        tx.fetch_all(sync, None)


def test_fetch_all_rejects_malformed_page():
    with pytest.raises(tx.TransactionsError):
        tx.fetch_all(lambda c: {"added": [], "has_more": False}, None)   # no next_cursor / lists


def test_fetch_all_other_errors_propagate():
    def sync(cursor):
        raise RuntimeError("ITEM_LOGIN_REQUIRED")
    with pytest.raises(RuntimeError, match="ITEM_LOGIN_REQUIRED"):
        tx.fetch_all(sync, None)


# --- freshly linked Items: Plaid is still preparing history ------------------------------
def test_empty_cursor_with_no_data_means_not_ready_yet():
    with pytest.raises(tx.NotReady):
        tx.fetch_all(lambda c: page([], next_cursor=""), None)


def test_not_ready_status_means_not_ready_even_with_a_cursor():
    p = page([], next_cursor="c1")
    p["transactions_update_status"] = "NOT_READY"
    with pytest.raises(tx.NotReady):
        tx.fetch_all(lambda c: p, None)


def test_empty_cursor_with_data_is_a_malformed_response_not_a_wait():
    with pytest.raises(tx.TransactionsError) as e:
        tx.fetch_all(lambda c: page([t("a")], next_cursor=""), None)
    assert not isinstance(e.value, tx.NotReady)


def test_not_ready_is_a_kind_of_transactions_error():
    assert issubclass(tx.NotReady, tx.TransactionsError)
