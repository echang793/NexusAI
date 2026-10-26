"""CoastFIRE odds: a probability and a range, not a single 7% line."""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import coastfire as cf  # noqa: E402

PROFILE = {"age": 26, "coastfire_retire_age": 55, "coastfire_annual_spend": 80000.0,
           "coastfire_return_pct": 7.0}


def test_same_seed_same_answer():
    a = cf.odds(PROFILE, 270000, trials=500, seed=1)
    b = cf.odds(PROFILE, 270000, trials=500, seed=1)
    assert a == b


def test_far_above_coast_number_is_near_certain():
    assert cf.odds(PROFILE, 3_000_000, trials=500, seed=1)["successPct"] >= 99


def test_tiny_balance_is_near_impossible():
    assert cf.odds(PROFILE, 1000, trials=500, seed=1)["successPct"] <= 1


def test_at_the_coast_number_is_roughly_a_coin_flip_not_certainty():
    # Right at the deterministic coast number, volatility drag makes success
    # a bit worse than 50%; the point is it must not read as ~100%.
    needed = cf.compute(PROFILE, 0)["coastNumberNeeded"]
    p = cf.odds(PROFILE, needed, trials=2000, seed=3)["successPct"]
    assert 25 <= p <= 65


def test_percentiles_are_ordered_and_bracket_the_median():
    o = cf.odds(PROFILE, 270000, trials=1000, seed=2)
    assert o["p10"] < o["p50"] < o["p90"]


def test_low_base_high_scenarios_ordered_and_base_matches_deterministic_projection():
    o = cf.odds(PROFILE, 270000, trials=200, seed=2)
    s = o["scenarios"]
    assert s["low"] < s["base"] < s["high"]
    assert s["base"] == cf.compute(PROFILE, 270000)["projectedAtRetirement"]


def test_disabled_when_no_spend_target():
    o = cf.odds({**PROFILE, "coastfire_annual_spend": 0}, 270000, trials=10, seed=1)
    assert o["successPct"] is None and o["scenarios"] is None


def test_already_retired_age_is_decided_by_balance_alone():
    p = {**PROFILE, "age": 60}
    assert cf.odds(p, 3_000_000, trials=10, seed=1)["successPct"] == 100.0
    assert cf.odds(p, 1_000_000, trials=10, seed=1)["successPct"] == 0.0


def test_output_is_native_json_safe():
    json.dumps(cf.odds(PROFILE, 270000, trials=100, seed=1), allow_nan=False)


def test_higher_volatility_widens_the_range():
    lo = cf.odds(PROFILE, 270000, trials=1500, vol=0.08, seed=5)
    hi = cf.odds(PROFILE, 270000, trials=1500, vol=0.25, seed=5)
    assert (hi["p90"] - hi["p10"]) > (lo["p90"] - lo["p10"])


def test_compute_includes_stable_odds_block():
    a = cf.compute(PROFILE, 270000)
    b = cf.compute(PROFILE, 270000)
    assert a["odds"]["successPct"] == b["odds"]["successPct"]   # fixed seed: no month-to-month noise
    assert a["odds"]["p10"] < a["odds"]["p90"]


def test_snapshot_details_carry_odds_for_the_monthly_report():
    import server
    status = cf.compute(PROFILE, 270000)
    d = server._snapshot_details([], status)
    c = d["coast"]
    assert c["oddsPct"] == status["odds"]["successPct"]
    assert (c["p10"], c["p50"], c["p90"]) == (status["odds"]["p10"], status["odds"]["p50"], status["odds"]["p90"])


def test_disabled_coastfire_has_no_odds_in_details():
    import server
    status = cf.compute({**PROFILE, "coastfire_annual_spend": 0}, 270000)
    assert "coast" not in server._snapshot_details([], status)
