"""plaid_sync._fetch_one(): turning Plaid balances into account rows.
Regression: a credit card with a $0.00 balance used to fall through `current or
available` to the UNUSED CREDIT, showing up as ~$20,000 of phantom debt."""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import plaid_sync  # noqa: E402


def acct(name="X", type_="credit", subtype="credit card", current=None, available=None, mask="1111", aid=None):
    return {"account_id": aid or f"id-{name}-{mask}", "name": name, "type": type_, "subtype": subtype, "mask": mask,
            "balances": {"current": current, "available": available, "limit": None}}


class Fake:
    def __init__(self, accounts):
        self.accounts = accounts

    def accounts_balance_get(self, request):
        return {"accounts": self.accounts}


def rows(*accounts):
    return plaid_sync._fetch_one(Fake(list(accounts)), "tok", "2026-11-14")


def by_name(rs):
    return {r["name"]: r for r in rs}


def test_zero_balance_credit_card_is_zero_not_the_available_credit():
    r = rows(acct("CARD", current=0.0, available=20998.76))[0]
    assert r["balance"] == 0.0 and r["type"] == "Credit Card"


def test_credit_card_with_a_balance_uses_the_amount_owed():
    assert rows(acct("CARD", current=307.64, available=13192.36))[0]["balance"] == 307.64


def test_credit_card_never_falls_back_to_available_credit():
    assert rows(acct("CARD", current=None, available=13500.0))[0]["balance"] == 0.0


def test_overpaid_card_is_not_turned_into_a_debt():
    assert rows(acct("CARD", current=-25.0, available=14025.0))[0]["balance"] == 0.0


def test_bank_account_uses_current_even_when_it_is_zero():
    r = rows(acct("CHK", "depository", "checking", current=0.0, available=50.0))[0]
    assert r["balance"] == 0.0 and r["type"] == "Checking"


def test_bank_account_falls_back_to_available_only_when_current_is_missing():
    assert rows(acct("CHK", "depository", "checking", current=None, available=100.0))[0]["balance"] == 100.0


def test_duplicate_names_get_the_last_four_digits_so_cards_stay_distinct():
    rs = rows(acct("CREDIT CARD", current=1.0, mask="2249"), acct("CREDIT CARD", current=2.0, mask="3487"),
              acct("TOTAL CHECKING", "depository", "checking", current=5.0, mask="2994"))
    assert sorted(r["name"] for r in rs) == ["CREDIT CARD ••2249", "CREDIT CARD ••3487", "TOTAL CHECKING"]


def test_duplicate_without_a_mask_still_gets_distinct_names():
    rs = rows(acct("CARD", current=1.0, mask=None, aid="a"), acct("CARD", current=2.0, mask=None, aid="b"))
    assert len({r["name"] for r in rs}) == 2


def test_unique_names_are_left_alone():
    assert rows(acct("TOTAL CHECKING", "depository", "checking", current=5.0))[0]["name"] == "TOTAL CHECKING"


def test_rows_keep_their_plaid_ids_so_renames_update_in_place():
    rs = rows(acct("CREDIT CARD", current=1.0, mask="2249", aid="A"), acct("CREDIT CARD", current=2.0, mask="3487", aid="B"))
    assert {r["plaid_account_id"] for r in rs} == {"A", "B"}
    existing = [{"name": "CREDIT CARD", "type": "Credit Card", "balance": 9.0, "plaid_account_id": "A", "source": "plaid"}]
    merged = plaid_sync._merge(existing, rs)
    assert len(merged) == 2 and {m["name"] for m in merged} == {"CREDIT CARD ••2249", "CREDIT CARD ••3487"}
