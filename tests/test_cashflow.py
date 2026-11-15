"""cashflow.py: monthly income / spending / savings rate from stored transactions.
Plaid sign convention: amount > 0 leaves the account, amount < 0 comes in."""

import datetime
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import cashflow as cfw  # noqa: E402

TODAY = datetime.date(2026, 11, 20)


def row(i, date, amount, cat="GENERAL_MERCHANDISE", detailed="", name="STORE", merchant="", pending=False):
    return {"id": i, "account": "a", "date": date, "amount": amount, "name": name,
            "merchant": merchant, "cat": cat, "detailed": detailed, "pending": pending}


def months(rows, rules=()):
    return cfw.monthly(rows, rules)


def test_spending_and_income_are_split_by_sign_and_category():
    m = months([row("1", "2026-10-02", 100.0, "FOOD_AND_DRINK"),
                row("2", "2026-10-03", 50.0, "TRANSPORTATION"),
                row("3", "2026-10-15", -4000.0, "INCOME")])
    o = m["2026-10"]
    assert o["spending"] == 150.0 and o["income"] == 4000.0
    assert o["byCategory"] == {"FOOD_AND_DRINK": 100.0, "TRANSPORTATION": 50.0}
    assert o["net"] == 3850.0
    assert o["savingsRate"] == pytest.approx(96.25)


def test_transfers_and_credit_card_payments_are_not_spending_or_income():
    m = months([row("1", "2026-10-02", 800.0, "TRANSFER_OUT", "TRANSFER_OUT_ACCOUNT_TRANSFER"),
                row("2", "2026-10-03", -800.0, "TRANSFER_IN", "TRANSFER_IN_ACCOUNT_TRANSFER"),
                row("3", "2026-10-04", 1200.0, "LOAN_PAYMENTS", "LOAN_PAYMENTS_CREDIT_CARD_PAYMENT"),
                row("4", "2026-10-05", 40.0, "FOOD_AND_DRINK")])
    o = m["2026-10"]
    assert o["spending"] == 40.0 and o["income"] == 0.0
    assert o["transfers"] == pytest.approx(800.0 + 800.0 + 1200.0)   # tracked, but excluded from the above


def test_other_loan_payments_still_count_as_spending():
    m = months([row("1", "2026-10-04", 300.0, "LOAN_PAYMENTS", "LOAN_PAYMENTS_CAR_PAYMENT")])
    assert m["2026-10"]["spending"] == 300.0


def test_refund_reduces_its_category():
    m = months([row("1", "2026-10-02", 100.0, "GENERAL_MERCHANDISE"),
                row("2", "2026-10-09", -30.0, "GENERAL_MERCHANDISE")])
    assert m["2026-10"]["byCategory"]["GENERAL_MERCHANDISE"] == 70.0
    assert m["2026-10"]["income"] == 0.0


def test_pending_transactions_are_ignored():
    m = months([row("1", "2026-10-02", 100.0, pending=True), row("2", "2026-10-03", 5.0)])
    assert m["2026-10"]["spending"] == 5.0


def test_months_without_income_have_no_savings_rate():
    m = months([row("1", "2026-10-02", 100.0)])
    assert m["2026-10"]["savingsRate"] is None


def test_user_rules_override_category_by_text_match_case_insensitive():
    rules = [{"match": "landlord", "category": "RENT_AND_UTILITIES"}]
    m = months([row("1", "2026-10-02", 2000.0, "GENERAL_SERVICES", name="Zelle to LANDLORD LLC")], rules)
    assert m["2026-10"]["byCategory"] == {"RENT_AND_UTILITIES": 2000.0}


def test_rule_can_mark_something_as_transfer_to_exclude_it():
    rules = [{"match": "venmo cashout", "category": "TRANSFER_OUT"}]
    m = months([row("1", "2026-10-02", 90.0, "GENERAL_SERVICES", name="VENMO CASHOUT")], rules)
    assert m["2026-10"]["spending"] == 0.0


def test_summary_uses_complete_months_only_for_averages():
    rows = []
    for mth, spend in (("2026-08", 3000), ("2026-09", 3500), ("2026-10", 4000), ("2026-11", 500)):
        rows.append(row(f"s{mth}", f"{mth}-10", float(spend), "FOOD_AND_DRINK"))
        rows.append(row(f"i{mth}", f"{mth}-01", -5000.0, "INCOME"))
    s = cfw.summary(rows, TODAY)
    assert s["completeMonths"] == 3                      # Nov is still in progress
    assert s["avgMonthlySpend"] == pytest.approx(3500.0)
    assert s["annualizedSpend"] == pytest.approx(42000.0)
    assert s["lastMonth"]["month"] == "2026-10"
    assert s["currentMonth"]["month"] == "2026-11" and s["currentMonth"]["partial"] is True
    assert s["avgSavingsRate"] == pytest.approx(30.0)    # (5000-3500)/5000


def test_summary_flags_short_history():
    s = cfw.summary([row("1", "2026-10-02", 100.0)], TODAY)
    assert s["completeMonths"] == 1 and s["shortHistory"] is True


def test_summary_empty_is_safe():
    s = cfw.summary([], TODAY)
    assert s["completeMonths"] == 0 and s["avgMonthlySpend"] is None and s["lastMonth"] is None


def test_top_categories_and_merchants_over_recent_months():
    rows = [row("1", "2026-10-02", 500.0, "FOOD_AND_DRINK", merchant="Chipotle"),
            row("2", "2026-10-03", 100.0, "FOOD_AND_DRINK", merchant="Chipotle"),
            row("3", "2026-10-04", 900.0, "RENT_AND_UTILITIES", merchant="")]
    s = cfw.summary(rows, TODAY)
    assert s["topCategories"][0]["category"] == "RENT_AND_UTILITIES"
    assert s["topMerchants"][0] == {"merchant": "Chipotle", "amount": 600.0}


def test_fire_and_emergency_comparison_against_assumed_spend():
    rows = [row(f"{i}", f"2026-{m:02d}-10", 5000.0) for i, m in enumerate((8, 9, 10))]
    s = cfw.summary(rows, TODAY, assumed_annual_spend=80000.0)
    assert s["annualizedSpend"] == 60000.0
    assert s["fireNumberAtActual"] == 1_500_000.0
    assert s["assumedAnnualSpend"] == 80000.0 and s["spendVsAssumedPct"] == pytest.approx(-25.0)


def test_labels_are_human_readable():
    assert cfw.label("FOOD_AND_DRINK") == "Food & drink"
    assert cfw.label("SOMETHING_NEW") == "Something new"


def test_output_is_json_safe():
    import json
    json.dumps(cfw.summary([row("1", "2026-10-02", 100.0), row("2", "2026-10-03", -900.0, "INCOME")], TODAY),
               allow_nan=False)


def test_summary_exposes_average_income_and_surplus():
    rows = []
    for mth, spend in (("2026-08", 3000), ("2026-09", 3500), ("2026-10", 4000)):
        rows.append(row(f"s{mth}", f"{mth}-10", float(spend), "FOOD_AND_DRINK"))
        rows.append(row(f"i{mth}", f"{mth}-01", -5000.0, "INCOME"))
    s = cfw.summary(rows, TODAY)
    assert s["avgMonthlyIncome"] == pytest.approx(5000.0) and s["avgMonthlySurplus"] == pytest.approx(1500.0)
    empty = cfw.summary([], TODAY)
    assert empty["avgMonthlyIncome"] is None and empty["avgMonthlySurplus"] is None


# --- money moved to investments; partial first month --------------------------------------
INV = "TRANSFER_OUT_INVESTMENT_AND_RETIREMENT_FUNDS"


def test_money_moved_to_investments_is_tracked_separately_from_spending():
    m = months([row("1", "2026-10-02", 6000.0, "TRANSFER_OUT", INV),
                row("2", "2026-10-03", 1500.0, "TRANSFER_OUT", "TRANSFER_OUT_ACCOUNT_TRANSFER"),
                row("3", "2026-10-04", -2000.0, "TRANSFER_IN", "TRANSFER_IN_DEPOSIT"),
                row("4", "2026-10-05", 40.0, "FOOD_AND_DRINK")])["2026-10"]
    assert m["invested"] == 6000.0 and m["spending"] == 40.0 and m["income"] == 0.0
    assert m["transfersIn"] == 2000.0


def test_investment_transfers_reversals_net_out():
    m = months([row("1", "2026-10-02", 500.0, "TRANSFER_OUT", INV),
                row("2", "2026-10-09", -100.0, "TRANSFER_IN", INV.replace("OUT", "IN"))])["2026-10"]
    assert m["invested"] == 500.0                         # only the TRANSFER_OUT investment rows count


def test_summary_reports_average_invested_and_flags_when_it_exceeds_income():
    rows = []
    for mth in ("2026-08", "2026-09", "2026-10"):
        rows += [row(f"s{mth}", f"{mth}-02", 1000.0, "FOOD_AND_DRINK"),
                 row(f"i{mth}", f"{mth}-01", -2000.0, "INCOME"),
                 row(f"v{mth}", f"{mth}-03", 5000.0, "TRANSFER_OUT", INV)]
    s = cfw.summary(rows, TODAY)
    assert s["avgMonthlyInvested"] == pytest.approx(5000.0)
    assert s["investedExceedsIncome"] is True
    ok = cfw.summary([row("a", "2026-10-02", 100.0), row("b", "2026-10-01", -3000.0, "INCOME"),
                      row("c", "2026-10-03", 500.0, "TRANSFER_OUT", INV)], TODAY)
    assert ok["investedExceedsIncome"] is False


def test_partial_first_month_is_not_averaged_in_when_enough_other_months_exist():
    rows = []
    for mth in ("2026-09", "2026-10"):
        rows.append(row(f"s{mth}", f"{mth}-04", 3000.0))
        rows.append(row(f"i{mth}", f"{mth}-01", -4000.0, "INCOME"))
    rows.append(row("aug", "2026-08-17", 400.0))           # history starts mid-August
    s = cfw.summary(rows, TODAY)
    assert s["completeMonths"] == 2 and s["avgMonthlySpend"] == pytest.approx(3000.0)


def test_partial_first_month_is_kept_when_it_is_nearly_all_we_have():
    s = cfw.summary([row("aug", "2026-08-17", 400.0), row("sep", "2026-09-03", 600.0)], TODAY)
    assert s["completeMonths"] == 2                         # only 1 other month: don't throw data away


def test_full_first_month_starting_in_the_first_days_is_kept():
    rows = [row(f"s{m}", f"{m}-03", 100.0) for m in ("2026-08", "2026-09", "2026-10")]
    assert cfw.summary(rows, TODAY)["completeMonths"] == 3


def test_summary_lists_the_partial_first_month_it_left_out():
    rows = []
    for mth in ("2026-09", "2026-10"):
        rows.append(row(f"s{mth}", f"{mth}-04", 3000.0))
    rows.append(row("aug", "2026-08-17", 400.0))
    assert cfw.summary(rows, TODAY)["partialMonths"] == ["2026-08"]
    assert cfw.summary([row("s", "2026-10-03", 5.0)], TODAY)["partialMonths"] == []
