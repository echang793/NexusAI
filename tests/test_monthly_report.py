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


def text(snaps, accounts=(), files=None, **kw):
    return mr.render_text(mr.build_report(list(snaps), list(accounts), files or {}, TODAY, **kw))


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


# --- why it moved (attribution) ------------------------------------------------------
def hday(q, p, chk, complete=True):
    return {"netWorth": 0, "accounts": {"TOTAL CHECKING": chk}, "complete": complete,
            "holdings": {"Roth IRA|VTI": {"q": q, "p": p, "s": "ETF"}}}


DAYS = {
    "2026-10-01": hday(100, 100.0, 3000),
    "2026-10-15": hday(100, 105.0, 3000),
    "2026-11-01": hday(110, 105.0, 2000),   # bought 10 shares; checking down $1,000
}


def test_why_it_moved_splits_market_new_money_and_other():
    t = text([OCT, NOV], days=DAYS)
    assert "WHY IT MOVED" in t
    assert "Market moves: +$500" in t and "+5.0%" in t
    assert "New shares bought: +$1,050" in t
    assert "Other accounts: -$1,000" in t
    assert "TOTAL CHECKING" in t.split("WHY IT MOVED")[1].split("COASTFIRE")[0]


def test_why_it_moved_names_biggest_market_movers():
    t = text([OCT, NOV], days=DAYS)
    assert "VTI" in t.split("WHY IT MOVED")[1].split("COASTFIRE")[0]


def test_window_note_when_daily_records_start_after_last_snapshot():
    days = {"2026-10-20": hday(100, 102.0, 3000), "2026-11-01": DAYS["2026-11-01"]}
    t = text([OCT, NOV], days=days)
    assert "Oct 20" in t.split("WHY IT MOVED")[1].split("COASTFIRE")[0]
    assert "only" in t.split("WHY IT MOVED")[1].lower()


def test_without_daily_records_it_says_tracking_just_started():
    t = text([OCT, NOV], days={})
    assert "WHY IT MOVED" in t and "just started" in t.lower()


# --- CoastFIRE odds --------------------------------------------------------------------
ODDS_OCT = dict(COAST_OCT, oddsPct=47.5, p10=1_200_000, p50=2_050_000, p90=3_600_000)
ODDS_NOV = dict(COAST_NOV, oddsPct=52.0, p10=1_300_000, p50=2_150_000, p90=3_700_000)


def test_odds_line_with_range_and_change_from_last_month():
    t = text([snap("2026-10", 1, 1, 1, coast=ODDS_OCT), snap("2026-11", 1, 1, 1, coast=ODDS_NOV)])
    c = t.split("COASTFIRE")[1].split("BY ACCOUNT")[0]
    assert "52.0%" in c and "47.5%" in c
    assert "$2,150,000" in c and "$1,300,000" in c and "$3,700,000" in c


def test_no_odds_text_when_snapshot_predates_odds():
    c = text([OCT, NOV]).split("COASTFIRE")[1].split("BY ACCOUNT")[0]
    assert "odds" not in c.lower()


# --- portfolio check -------------------------------------------------------------------
AN = {"top5Pct": 61.5, "effectiveN": 8.2,
      "top": [{"ticker": "NVDA", "pct": 14.1, "accounts": ["Brokerage"]}],
      "singleNameFlags": [{"ticker": "NVDA", "pct": 14.1}],
      "multiAccount": [{"ticker": "MU", "pct": 5.0, "accounts": ["Brokerage", "Roth IRA"]}],
      "location": [{"ticker": f"D{i}", "account": "Brokerage", "yieldPct": 4.0, "why": "taxed yearly"}
                   for i in range(5)],
      "allocation": {"US Equity": 90.0, "Bonds": 10.0},
      "risk": {"sharpe": 1.1, "maxDrawdown": -18.0, "benchmarkSharpe": 0.9}}
DAYS_AN = {"2026-11-01": {**hday(1, 1, 1), "analytics": AN}}


def test_portfolio_check_reports_concentration_and_flags():
    t = text([OCT, NOV], days=DAYS_AN)
    pc = t.split("PORTFOLIO CHECK")[1].split("HEADS UP")[0]
    assert "61.5%" in pc and "NVDA" in pc and "14.1%" in pc
    assert "8.2" in pc                                 # effective number of holdings
    assert "1.1" in pc and "18" in pc                  # Sharpe and drawdown
    assert "US Equity 90.0%" in pc


def test_location_nudges_capped_at_three():
    pc = text([OCT, NOV], days=DAYS_AN).split("PORTFOLIO CHECK")[1].split("HEADS UP")[0]
    assert pc.count("taxed yearly") == 3


def test_no_portfolio_check_section_without_analytics():
    assert "PORTFOLIO CHECK" not in text([OCT, NOV], days=DAYS)


# --- signal scorecard ---------------------------------------------------------------------
def sc_json(buy_hit=52.3, base_hit=51.5, n=1498):
    return {"horizons": [21, 63], "tickers": ["A"] * 41, "summary": {
        "ALL": {"63": {"n": 9993, "avgRet": 5, "avgExcess": 3.4, "hitRate": base_hit}},
        "BUY": {"63": {"n": n, "avgRet": 9, "avgExcess": 3.8, "hitRate": buy_hit}},
        "SELL": {"63": {"n": 4112, "avgRet": 5.4, "avgExcess": 2.5, "hitRate": 50.0}},
        "HOLD": {"63": {"n": 4383, "avgRet": 7, "avgExcess": 4, "hitRate": None}}}}


def test_scorecard_says_no_clear_edge_when_buy_matches_baseline():
    t = text([OCT, NOV], scorecard=sc_json())
    s = t.split("SIGNAL SCORECARD")[1].split("HEADS UP")[0]
    assert "52.3%" in s and "51.5%" in s and "no clear edge" in s.lower()


def test_scorecard_reports_edge_only_when_clearly_better_with_enough_calls():
    s = text([OCT, NOV], scorecard=sc_json(buy_hit=62.0)).split("SIGNAL SCORECARD")[1]
    assert "edge" in s.lower() and "no clear edge" not in s.lower()


def test_scorecard_small_sample_is_not_trusted():
    s = text([OCT, NOV], scorecard=sc_json(buy_hit=80.0, n=10)).split("SIGNAL SCORECARD")[1]
    assert "too few" in s.lower()


# --- watchdog problems in HEADS UP ---------------------------------------------------------
def test_health_problems_listed_and_suppress_all_fresh():
    probs = [{"code": "plaid_stale", "message": "Plaid balances not updating: TOTAL CHECKING (7d)"}]
    t = text([OCT, NOV], problems=probs)
    h = t.split("HEADS UP")[1]
    assert "TOTAL CHECKING (7d)" in h and "all data is fresh" not in h.lower()


def test_plain_text_still_has_no_markdown_with_everything_on():
    t = text([OCT, NOV], days=DAYS_AN, scorecard=sc_json(), problems=[])
    assert "**" not in t and "##" not in t and "|" not in t


def test_scorecard_shows_when_it_was_generated():
    sc = sc_json()
    sc["generated"] = datetime.date(2026, 10, 26)
    assert "as of Oct 26" in text([OCT, NOV], scorecard=sc)


def test_stock_tilt_line_uses_individual_stocks_not_funds():
    an = {**AN, "stocksPct": 38.5, "topStocks": [{"ticker": "SNDK", "pct": 6.0}, {"ticker": "MU", "pct": 5.6}]}
    pc = text([OCT, NOV], days={"2026-11-01": {**hday(1, 1, 1), "analytics": an}}).split("PORTFOLIO CHECK")[1]
    assert "38.5%" in pc and "SNDK 6.0%" in pc and "MU 5.6%" in pc


def test_overlap_is_summarised_not_listed_name_by_name():
    many = [{"ticker": f"T{i}", "pct": 1.0, "accounts": ["Brokerage", "Roth IRA"]} for i in range(14)]
    pc = text([OCT, NOV], days={"2026-11-01": {**hday(1, 1, 1), "analytics": {**AN, "multiAccount": many}}}
              ).split("PORTFOLIO CHECK")[1].split("HEADS UP")[0]
    assert "14 holdings" in pc and "T13" not in pc


def test_unknown_yield_is_not_printed_as_zero():
    an = {**AN, "location": [{"ticker": "SGOV", "account": "Brokerage", "yieldPct": 0.0,
                              "why": "bond/T-bill interest is taxed as ordinary income"}]}
    pc = text([OCT, NOV], days={"2026-11-01": {**hday(1, 1, 1), "analytics": an}}).split("PORTFOLIO CHECK")[1]
    assert "SGOV" in pc and "0.0% yield" not in pc
