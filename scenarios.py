"""What-if planner: change retirement age, spending, contribution or return and
see the effect on the FIRE number, timing, projection and odds, side by side
with the current plan. Reuses fire.py / coastfire.py; deterministic (seeded)."""

import math

import coastfire
import fire

# override name -> (profile field, min, max, integer?)
_RANGES = {
    "retire_age": ("coastfire_retire_age", 18, 100, True),
    "annual_spend": ("coastfire_annual_spend", 0.0, 10_000_000.0, False),
    "monthly_contribution": ("coastfire_monthly_contribution", 0.0, 1_000_000.0, False),
    "return_pct": ("coastfire_return_pct", 0.0, 20.0, False),
}
_SEED = 42
_DELTA_KEYS = ("fireNumber", "fireAge", "projectedAtRetirement", "yearsToRetire",
               "coastNumberNeeded", "pctOfCoast", "coastOddsPct", "fullFireOddsPct")


def _apply(overrides: dict) -> dict:
    applied = {}
    for name, (_field, lo, hi, as_int) in _RANGES.items():
        if name not in (overrides or {}):
            continue
        try:
            v = float(overrides[name])
        except (TypeError, ValueError):
            continue
        if not math.isfinite(v):
            continue
        v = max(lo, min(hi, v))
        applied[name] = int(v) if as_int else v
    return applied


def _snapshot(profile: dict, invested: float) -> dict:
    f = fire.compute(profile, invested)
    c = coastfire.compute(profile, invested)
    years = c["yearsToRetire"]
    mc = fire.monte_carlo(invested, f["monthlyContribution"] * 12.0, years, f["fireNumber"],
                          mean_return=c["returnPct"] / 100.0, seed=_SEED)
    return {
        "retireAge": c["retireAge"], "annualSpend": c["annualSpend"],
        "monthlyContribution": f["monthlyContribution"], "returnPct": c["returnPct"],
        "fireNumber": f["fireNumber"], "fireAge": f["fireAge"], "yearsToFire": f["yearsToFire"],
        "projectedAtRetirement": f["projectedAtRetirement"], "yearsToRetire": years,
        "coastNumberNeeded": c["coastNumberNeeded"], "pctOfCoast": c["pctOfCoast"],
        "coastOddsPct": (c.get("odds") or {}).get("successPct"),
        "fullFireOddsPct": mc.get("successPct"),
    }


def what_if(profile: dict, invested: float, overrides: dict) -> dict:
    applied = _apply(overrides)
    scenario_profile = dict(profile)
    for name, v in applied.items():
        scenario_profile[_RANGES[name][0]] = v
    baseline = _snapshot(profile, invested)
    scenario = _snapshot(scenario_profile, invested)
    delta = {k: (None if baseline[k] is None or scenario[k] is None else round(scenario[k] - baseline[k], 2))
             for k in _DELTA_KEYS}
    return {"baseline": baseline, "scenario": scenario, "delta": delta, "applied": applied}
