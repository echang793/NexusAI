"""Savings goals, monthly budget, and the what-if planner."""

import datetime
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import goals as gl  # noqa: E402
import budget as bg  # noqa: E402
import scenarios as sc  # noqa: E402
import profile as pr  # noqa: E402
import fire  # noqa: E402

TODAY = datetime.date(2026, 11, 14)


# --- profile storage keeps goals and budget (it used to drop unknown fields) --------------
def test_goals_and_budget_survive_a_save_load_roundtrip(tmp_path):
    path = str(tmp_path / "p.json")
    pr.save_profile({"savings_goals": [{"name": "House", "target": 60000, "date": "2028-06-01",
                                        "linked": ["TOTAL CHECKING"], "extra": 500}],
                     "budget": {"FOOD_AND_DRINK": 600}}, path)
    p = pr.load_profile(path)
    g = p["savings_goals"][0]
    assert g["name"] == "House" and g["target"] == 60000.0 and g["date"] == "2028-06-01"
    assert g["linked"] == ["TOTAL CHECKING"] and g["extra"] == 500.0 and g["id"]
    assert p["budget"] == {"FOOD_AND_DRINK": 600.0}


def test_invalid_goals_are_dropped_and_fields_clamped():
    p = pr._coerce({"savings_goals": [
        {"name": "ok", "target": 100, "date": "2030-01-01"},
        {"name": "", "target": 100},                       # no name
        {"name": "neg", "target": -5},                     # bad target
        {"name": "baddate", "target": 10, "date": "soon"},   # date ignored, goal kept
        "garbage", None,
        {"name": "x" * 200, "target": 1}]})
    names = [g["name"] for g in p["savings_goals"]]
    assert names == ["ok", "baddate", "x" * 60]
    assert p["savings_goals"][1]["date"] == ""


def test_goal_ids_are_unique_and_stable():
    p = pr._coerce({"savings_goals": [{"name": "Car", "target": 1}, {"name": "Car", "target": 2}]})
    ids = [g["id"] for g in p["savings_goals"]]
    assert len(set(ids)) == 2
    assert pr._coerce(p)["savings_goals"][0]["id"] == ids[0]


def test_goal_count_is_capped():
    p = pr._coerce({"savings_goals": [{"name": f"g{i}", "target": 1} for i in range(50)]})
    assert len(p["savings_goals"]) == 20


def test_budget_keeps_only_sane_category_keys_and_nonnegative_amounts():
    p = pr._coerce({"budget": {"FOOD_AND_DRINK": "450", "rent": 1, "BAD KEY!": 5, "TRAVEL": -10, "X": "abc"}})
    assert p["budget"] == {"FOOD_AND_DRINK": 450.0}


def test_defaults_have_empty_goals_and_budget():
    assert pr.load_profile("/nonexistent/p.json")["savings_goals"] == []
    assert pr.load_profile("/nonexistent/p.json")["budget"] == {}


# --- goals.progress ----------------------------------------------------------------------
def goal(**kw):
    return {"id": "g1", "name": "House", "target": 12000.0, "date": "2027-11-14", "linked": [], "extra": 0.0, **kw}


def test_progress_sums_linked_account_balances_plus_extra():
    r = gl.progress([goal(linked=["CHK", "SAV"], extra=1000.0)], {"CHK": 2000.0, "SAV": 3000.0, "OTHER": 99.0}, TODAY)[0]
    assert r["saved"] == 6000.0 and r["pct"] == 50.0 and r["remaining"] == 6000.0


def test_required_monthly_is_remaining_over_months_left():
    r = gl.progress([goal(extra=6000.0)], {}, TODAY)[0]          # 6000 left, exactly 12 months
    assert r["monthsLeft"] == pytest.approx(12.0, abs=0.1)
    assert r["requiredMonthly"] == pytest.approx(500.0, rel=0.01)


def test_done_goal_needs_nothing():
    r = gl.progress([goal(extra=20000.0)], {}, TODAY)[0]
    assert r["status"] == "done" and r["requiredMonthly"] == 0.0 and r["pct"] == 100.0


def test_overdue_goal_is_flagged():
    r = gl.progress([goal(date="2026-01-01", extra=1.0)], {}, TODAY)[0]
    assert r["status"] == "overdue" and r["requiredMonthly"] is None


def test_goal_without_a_date_has_no_monthly_requirement():
    r = gl.progress([goal(date="", extra=1.0)], {}, TODAY)[0]
    assert r["status"] == "no date" and r["requiredMonthly"] is None


def test_summary_compares_total_requirement_with_monthly_surplus():
    gs = [goal(id="a", extra=6000.0), goal(id="b", name="Car", target=6000.0, extra=0.0)]   # 500 + 500
    s = gl.summary(gl.progress(gs, {}, TODAY), monthly_surplus=800.0)
    assert s["totalRequiredMonthly"] == pytest.approx(1000.0, rel=0.02) and s["fundable"] is False
    assert gl.summary(gl.progress(gs, {}, TODAY), monthly_surplus=2000.0)["fundable"] is True
    assert gl.summary(gl.progress(gs, {}, TODAY), monthly_surplus=None)["fundable"] is None


def test_progress_is_json_safe_and_handles_empty():
    assert gl.progress([], {}, TODAY) == []
    json.dumps(gl.progress([goal(extra=1.0)], {}, TODAY), allow_nan=False)


# --- budget.compare ----------------------------------------------------------------------
def test_budget_rows_show_actual_vs_target_sorted_by_overage():
    rows = bg.compare({"FOOD_AND_DRINK": 500.0, "TRAVEL": 300.0},
                      {"FOOD_AND_DRINK": 650.0, "TRAVEL": 100.0, "GENERAL_MERCHANDISE": 80.0})
    by = {r["category"]: r for r in rows["rows"]}
    assert by["FOOD_AND_DRINK"]["over"] is True and by["FOOD_AND_DRINK"]["remaining"] == -150.0
    assert by["FOOD_AND_DRINK"]["pctUsed"] == 130.0 and by["TRAVEL"]["over"] is False
    assert rows["rows"][0]["category"] == "FOOD_AND_DRINK"
    assert rows["unbudgeted"] == 80.0
    assert rows["totalTarget"] == 800.0 and rows["totalActual"] == 750.0


def test_budget_empty_is_safe():
    r = bg.compare({}, {"FOOD_AND_DRINK": 10.0})
    assert r["rows"] == [] and r["unbudgeted"] == 10.0


def test_budget_pace_flag_for_a_partial_month():
    r = bg.compare({"FOOD_AND_DRINK": 600.0}, {"FOOD_AND_DRINK": 400.0}, month_fraction=0.3)
    row = r["rows"][0]
    assert row["over"] is False and row["aheadOfPace"] is True      # 67% spent with 30% of the month gone


# --- what-if ----------------------------------------------------------------------------
PROFILE = {"age": 26, "coastfire_retire_age": 55, "coastfire_annual_spend": 80000.0,
           "coastfire_return_pct": 7.0, "coastfire_monthly_contribution": 1000.0}


def test_baseline_matches_the_existing_calculators():
    r = sc.what_if(PROFILE, 270000.0, {})
    base = fire.compute(PROFILE, 270000.0)
    assert r["baseline"]["fireNumber"] == base["fireNumber"] == 2_000_000
    assert r["baseline"]["projectedAtRetirement"] == base["projectedAtRetirement"]
    assert r["scenario"] == r["baseline"] and all(v == 0 for v in r["delta"].values() if v is not None)


def test_lower_spend_means_smaller_target_and_earlier_fire():
    r = sc.what_if(PROFILE, 270000.0, {"annual_spend": 60000.0})
    assert r["scenario"]["fireNumber"] == 1_500_000
    assert r["delta"]["fireNumber"] == -500_000
    assert r["scenario"]["fireAge"] < r["baseline"]["fireAge"]


def test_more_contribution_raises_projection_and_odds():
    r = sc.what_if(PROFILE, 270000.0, {"monthly_contribution": 3000.0})
    assert r["scenario"]["projectedAtRetirement"] > r["baseline"]["projectedAtRetirement"]
    assert r["scenario"]["fullFireOddsPct"] >= r["baseline"]["fullFireOddsPct"]


def test_later_retirement_gives_compounding_more_time():
    r = sc.what_if(PROFILE, 270000.0, {"retire_age": 65})
    assert r["scenario"]["projectedAtRetirement"] > r["baseline"]["projectedAtRetirement"]
    assert r["scenario"]["yearsToRetire"] == 39


def test_results_are_deterministic_for_identical_inputs():
    a = sc.what_if(PROFILE, 270000.0, {"annual_spend": 70000.0})
    b = sc.what_if(PROFILE, 270000.0, {"annual_spend": 70000.0})
    assert a == b


def test_overrides_are_validated_and_clamped():
    r = sc.what_if(PROFILE, 270000.0, {"retire_age": 5, "return_pct": 500, "annual_spend": -1,
                                       "monthly_contribution": "abc", "bogus": 1})
    assert r["scenario"]["yearsToRetire"] == 0          # retire_age clamps to 18, already past at 26
    assert r["applied"].get("return_pct") == 20.0 and r["applied"].get("annual_spend") == 0.0
    assert "monthly_contribution" not in r["applied"] and "bogus" not in r["applied"]
    json.dumps(r, allow_nan=False)


def test_fire_monte_carlo_accepts_a_seed():
    a = fire.monte_carlo(270000, 12000, 29, 2_000_000, seed=5)
    assert a == fire.monte_carlo(270000, 12000, 29, 2_000_000, seed=5)
