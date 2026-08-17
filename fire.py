"""Full FIRE projection (with ongoing contributions) + Monte Carlo success odds.

Complements coastfire.py, which answers "if I stopped contributing today,
would I still get there?" This module answers "at my current contribution
rate, when do I actually hit my number?" plus a probabilistic gut-check via
Monte Carlo since real returns aren't a smooth constant-rate line.
"""

import random

from coastfire import fire_number


def years_to_fire(invested: float, annual_contribution: float, target: float,
                   rate: float, max_years: int = 80):
    """Iterative search for the first year balance >= target.

    Returns None if it's never reached within max_years (e.g. rate and
    contribution both too low) — don't guess, say so.
    """
    if invested >= target:
        return 0
    bal = invested
    for year in range(1, max_years + 1):
        bal = bal * (1.0 + rate) + annual_contribution
        if bal >= target:
            return year
    return None


def compute(profile: dict, invested: float) -> dict:
    age = int(profile.get("age", 30) or 30)
    retire_age = int(profile.get("coastfire_retire_age", 65) or 65)
    annual_spend = float(profile.get("coastfire_annual_spend", 0) or 0)
    return_pct = float(profile.get("coastfire_return_pct", 7.0) or 7.0)
    monthly_contribution = float(profile.get("coastfire_monthly_contribution", 0) or 0)
    rate = return_pct / 100.0
    annual_contribution = monthly_contribution * 12.0
    target = fire_number(annual_spend)
    years_available = max(0, retire_age - age)

    years = years_to_fire(invested, annual_contribution, target, rate) if target > 0 else None

    projected_at_retirement = invested
    for _ in range(years_available):
        projected_at_retirement = projected_at_retirement * (1.0 + rate) + annual_contribution

    return {
        "enabled": annual_spend > 0,
        "monthlyContribution": round(monthly_contribution),
        "fireNumber": round(target),
        "yearsToFire": years,
        "fireAge": (age + years) if years is not None else None,
        "projectedAtRetirement": round(projected_at_retirement),
        "onTrackForRetireAge": years is not None and years <= years_available,
    }


def monte_carlo(invested: float, annual_contribution: float, years: int, target: float,
                 mean_return: float = 0.07, volatility: float = 0.15, trials: int = 1500) -> dict:
    """% of simulated random-return paths that reach `target` within `years`.

    Smooth compounding at a fixed rate hides sequence-of-returns risk —
    this samples a random annual return each year (normal dist. around
    mean_return) instead, so the result is a probability, not a promise.
    """
    if target <= 0:
        return {"successPct": None, "trials": 0}
    if years <= 0:
        return {"successPct": 100.0 if invested >= target else 0.0, "trials": 0}
    hits = 0
    for _ in range(trials):
        bal = invested
        for _year in range(years):
            r = random.gauss(mean_return, volatility)
            bal = bal * (1.0 + r) + annual_contribution
        if bal >= target:
            hits += 1
    return {"successPct": round(hits / trials * 100.0, 1), "trials": trials}
