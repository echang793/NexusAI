"""POST /api/accounts must not destroy what the dashboard cannot show: the Plaid
tags (source / plaid_account_id) and the specific account type. Losing them made
the next Plaid sync append duplicate rows and hid a 401(k) from CoastFIRE."""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import accounts as ac  # noqa: E402
import server  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    f = tmp_path / "accounts.json"
    f.write_text(json.dumps({"accounts": [
        {"name": "Webull Cash", "type": "Other Asset", "balance": 1.05, "notes": "", "updated": "2026-11-16"},
        {"name": "RoboInvestor", "type": "Taxable", "balance": 840.5, "notes": "", "updated": "2026-10-02"},
        {"name": "NORTHROP GRUMMAN SAVINGS PLAN", "type": "Retirement", "balance": 79633.98, "notes": "Fidelity",
         "updated": "2026-11-15", "source": "plaid", "plaid_account_id": "p401"},
        {"name": "TOTAL CHECKING", "type": "Checking", "balance": 2227.26, "notes": "", "updated": "2026-11-15",
         "source": "plaid", "plaid_account_id": "pchk"},
        {"name": "Health Savings Account (Cash)", "type": "HSA", "balance": 0.0, "notes": "", "updated": "2026-11-15",
         "source": "plaid", "plaid_account_id": "phsa_cash"},
        {"name": "CREDIT CARD ••2249", "type": "Credit Card", "balance": 24.73, "notes": "", "updated": "2026-11-15",
         "source": "plaid", "plaid_account_id": "pcc"},
    ]}))
    monkeypatch.setattr(ac, "ACCOUNTS_FILE", str(f))
    server.app.config["TESTING"] = True
    with server.app.test_client() as c:
        c.file = f
        yield c


def ui_payload(client):
    """What the dashboard sends back: names, UI-level types, balances, no Plaid tags."""
    out = []
    for a in ac.load_accounts():
        out.append({"id": a["name"], "name": a["name"], "type": server._AC_TO_UI.get(a["type"], "Other Asset"),
                    "balance": a["balance"], "institution": a["notes"], "updated": a["updated"]})
    return out


def saved(client):
    return {a["name"]: a for a in json.loads(client.file.read_text())["accounts"]}


def test_untouched_roundtrip_keeps_plaid_tags_and_specific_types(client):
    r = client.post("/api/accounts", json={"accounts": ui_payload(client)})
    assert r.status_code == 200
    s = saved(client)
    assert s["NORTHROP GRUMMAN SAVINGS PLAN"]["plaid_account_id"] == "p401"
    assert s["NORTHROP GRUMMAN SAVINGS PLAN"]["source"] == "plaid"
    assert s["NORTHROP GRUMMAN SAVINGS PLAN"]["type"] == "Retirement"
    assert s["TOTAL CHECKING"]["type"] == "Checking" and s["TOTAL CHECKING"]["plaid_account_id"] == "pchk"
    assert s["Health Savings Account (Cash)"]["type"] == "HSA"
    assert s["CREDIT CARD ••2249"]["type"] == "Credit Card"
    assert s["RoboInvestor"]["type"] == "Taxable"
    assert "plaid_account_id" not in s["RoboInvestor"]  # manual rows stay manual


def test_editing_a_balance_keeps_tags(client):
    payload = ui_payload(client)
    for a in payload:
        if a["name"] == "RoboInvestor":
            a["balance"] = 815.34
    client.post("/api/accounts", json={"accounts": payload})
    assert saved(client)["RoboInvestor"]["balance"] == 815.34


def test_changing_a_type_in_the_dashboard_still_takes_effect(client):
    payload = ui_payload(client)
    for a in payload:
        if a["name"] == "RoboInvestor":
            a["type"] = "Crypto"
    client.post("/api/accounts", json={"accounts": payload})
    assert saved(client)["RoboInvestor"]["type"] == "Crypto"


def test_new_accounts_and_deletions_still_work(client):
    payload = [a for a in ui_payload(client) if a["name"] != "Webull Cash"]
    payload.append({"id": "n1", "name": "Old Car", "type": "Other Asset", "balance": 9000, "institution": ""})
    client.post("/api/accounts", json={"accounts": payload})
    s = saved(client)
    assert "Webull Cash" not in s and s["Old Car"]["balance"] == 9000.0


def test_a_new_row_never_inherits_tags_from_a_different_name(client):
    payload = ui_payload(client) + [{"id": "n2", "name": "Another", "type": "Cash", "balance": 5, "institution": ""}]
    client.post("/api/accounts", json={"accounts": payload})
    assert "plaid_account_id" not in saved(client)["Another"]
