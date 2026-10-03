"""Tests for scripts/monthly_report.py — month-over-month report built purely
from stored files (never recomputes net worth or fetches prices)."""

import datetime
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import monthly_report as mr  # noqa: E402

TODAY = datetime.date(2026, 11, 1)


def snap(month, value, inv, other, accounts=None, coast=None, recorded=None):
    s = {"date": f"{month}-01", "value": value, "investments": inv, "otherAssets": other,
         "liabilities": 0, "recordedAt": recorded or f"{month}-01"}
    if accounts or coast:
        s["details"] = {}
        if accounts:
            s["details"]["accounts"] = accounts
        if coast:
            s["details"]["coast"] = coast
    return s


COAST_OCT = {"invested": 270000, "needed": 281000, "fireNumber": 2000000, "pctOfCoast": 96.1, "yearsToRetire": 29}
COAST_NOV = {"invested": 281000, "needed": 282000, "fireNumber": 2000000, "pctOfCoast": 99.6, "yearsToRetire": 29}

OCT = snap("2026-10", 273585, 190152, 83433, {"Webull Brokerage": 100000, "TOTAL CHECKING": 3500}, COAST_OCT)
NOV = snap("2026-11", 290000, 200000, 90000, {"Webull Brokerage": 108000, "TOTAL CHECKING": 3000, "Brand New": 500}, COAST_NOV)
SEP = snap("2026-09", 274491, 188076, 86416)


def text(snaps, accounts=(), files=None):
    return mr.render_text(mr.build_report(list(snaps), list(accounts), files or {}, TODAY))


def test_headline_change_in_dollars_and_percent():
    t = text([SEP, OCT, NOV])
    assert "$290,000" in t
    assert "+$16,415" in t and "+6.0%" in t  # vs October's $273,585
    assert "October" in t


def test_goes_down_shows_minus_sign():
    t = text([snap("2026-10", 100000, 0, 0), snap("2026-11", 98000, 0, 0)])
    assert "-$2,000" in t and "-2.0%" in t


def test_investments_vs_other_split():
    t = text([OCT, NOV])
    assert "+$9,848" in t   # investments 190,152 -> 200,000
    assert "+$6,567" in t   # other 83,433 -> 90,000


def test_coastfire_progress_and_last_month_comparison():
    t = text([OCT, NOV])
    assert "COASTFIRE" in t
    assert "99.6%" in t and "96.1%" in t
    assert "$1,000" in t  # shortfall left: needed 282,000 - invested 281,000


def test_coastfire_surplus_wording_when_past_coast_number():
    over = dict(COAST_NOV, invested=290000, pctOfCoast=102.8)
    t = text([OCT, snap("2026-11", 300000, 1, 1, coast=over)])
    assert "ahead" in t.lower() and "$8,000" in t


def test_per_account_changes_sorted_by_size_and_new_accounts_flagged():
    t = text([OCT, NOV])
    assert t.index("Webull Brokerage") < t.index("TOTAL CHECKING")  # biggest move first
    assert "+$8,000" in t and "-$500" in t
    assert "Brand New" in t and "new" in t.lower()


def test_missing_details_last_month_explains_instead_of_crashing():
    t = text([SEP, snap("2026-10", 273585, 190152, 83433, {"A": 1}, COAST_OCT)])
    assert "per-account comparison" in t.lower()  # Sep has no breakdown


def test_first_ever_month_has_no_comparison_but_does_not_crash():
    t = text([OCT])
    assert "$273,585" in t
    assert "first" in t.lower()


def test_empty_history_is_a_clear_message():
    assert "no net worth history" in text([]).lower()


def test_since_start_line():
    t = text([snap("2026-07", 245093, 0, 0), SEP, OCT])
    assert "since july 2026" in t.lower()
    assert "+$28,492" in t


def test_stale_manual_account_is_flagged_but_fresh_plaid_is_not():
    accounts = [
        {"name": "RoboInvestor", "balance": 840.5, "updated": "2026-09-08"},                       # 54 days
        {"name": "NORTHROP", "balance": 1, "updated": "2026-11-01", "source": "plaid"},
    ]
    t = text([OCT, NOV], accounts)
    assert "RoboInvestor" in t and "54 days" in t
    assert "NORTHROP" not in t.split("HEADS UP")[-1]


def test_stale_plaid_account_means_sync_may_be_broken():
    accounts = [{"name": "TOTAL CHECKING", "balance": 1, "updated": "2026-10-20", "source": "plaid"}]
    t = text([OCT, NOV], accounts)
    assert "TOTAL CHECKING" in t and "sync" in t.lower()


def test_old_webull_holdings_flagged():
    t = text([OCT, NOV], files={"Webull holdings": datetime.date(2026, 9, 1)})
    assert "Webull holdings" in t and "61 days" in t


def test_all_fresh_says_so():
    accounts = [{"name": "TOTAL CHECKING", "balance": 1, "updated": "2026-11-01", "source": "plaid"}]
    assert "all data is fresh" in text([OCT, NOV], accounts, {"Webull holdings": TODAY}).lower()


def test_plain_text_has_no_markdown():
    t = text([OCT, NOV])
    assert "**" not in t and "##" not in t and "|" not in t  # email body is plain text


def test_always_states_when_webull_holdings_were_last_refreshed():
    # An unattended run can't know whether Webull was refreshed by hand earlier,
    # so the report states the real date instead of guessing.
    files = {"Webull taxable holdings": datetime.date(2026, 10, 28),
             "Webull Roth holdings": datetime.date(2026, 10, 2)}
    t = text([OCT, NOV], files=files)
    assert "Webull holdings last refreshed: Oct 2" in t  # the OLDER of the two files


def test_no_webull_line_when_file_dates_unknown():
    assert "last refreshed" not in text([OCT, NOV])
