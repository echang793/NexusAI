"""CoastFIRE math: standard 25x rule + compound-to-retirement projection.

CoastFIRE = you've saved enough invested assets that, left alone to compound
at an assumed real return, they'll grow to your FIRE number by retirement
age with zero further contributions. "Coast number needed today" actually
RISES each year you age toward retirement — fewer years left to compound
means you need to already be closer to the final number, asymptotically
reaching the FIRE number itself right at retirement. (Correction: an
earlier version of this comment had the direction backwards.) This is
meant to be re-checked yearly as age/invested balance update — if your
invested balance grows exactly at the assumed rate, whether you're
"coasted" is time-invariant; only extra contributions or above-assumption
returns actually close a gap.
"""


def fire_number(annual_spend: float) -> float:
    """Target portfolio size via the 4% rule (25x annual spend)."""
    return annual_spend * 25.0


def coast_number(target: float, years: float, rate: float) -> float:
    """Present value needed today to grow to `target` in `years` at `rate`."""
    if years <= 0:
        return target
    return target / ((1.0 + rate) ** years)


def compute(profile: dict, invested: float) -> dict:
    """Build the full CoastFIRE status block for the dashboard.

    `invested` should be investment-only value (excludes cash/checking) —
    the balance actually left to compound untouched.
    """
    age = int(profile.get("age", 30) or 30)
    retire_age = int(profile.get("coastfire_retire_age", 65) or 65)
    annual_spend = float(profile.get("coastfire_annual_spend", 0) or 0)
    return_pct = float(profile.get("coastfire_return_pct", 7.0) or 7.0)
    rate = return_pct / 100.0
    years = max(0, retire_age - age)

    target = fire_number(annual_spend)
    needed = coast_number(target, years, rate) if target > 0 else 0.0
    projected = invested * ((1.0 + rate) ** years)
    on_track = target > 0 and invested >= needed
    pct_of_coast = (invested / needed * 100.0) if needed > 0 else 0.0

    return {
        "enabled": annual_spend > 0,
        "age": age,
        "retireAge": retire_age,
        "yearsToRetire": years,
        "annualSpend": round(annual_spend),
        "returnPct": return_pct,
        "fireNumber": round(target),
        "coastNumberNeeded": round(needed),
        "invested": round(invested),
        "surplus": round(invested - needed),
        "pctOfCoast": round(pct_of_coast, 1),
        "onTrack": on_track,
        "projectedAtRetirement": round(projected),
        "projectedSurplus": round(projected - target),
        # Fixed seed: the same inputs give the same odds, so month-to-month
        # changes reflect the portfolio, not simulation noise.
        "odds": odds(profile, invested, trials=2000, seed=42),
    }


def odds(profile: dict, invested: float, trials: int = 2000, vol: float = 0.15,
         seed: int | None = None, band_pts: float = 3.0) -> dict:
    """Odds that `invested`, left alone until retirement, reaches the FIRE number.

    compute() answers with one smooth rate (default 7%), which hides how wide
    the real outcomes are. This draws a random annual return each year
    (normal around the assumed rate, std dev `vol`) and reports:
      successPct  - share of paths ending at or above the FIRE number
      p10/p50/p90 - balance at retirement for an unlucky / typical / lucky path
      scenarios   - fixed-rate projections at (rate - band_pts), rate, (rate + band_pts)
    `vol` of 15% suits a broad stock mix; a tech-heavy portfolio runs hotter.
    Seed it for repeatable numbers (tests); leave None in production.
    """
    import random
    age = int(profile.get("age", 30) or 30)
    retire_age = int(profile.get("coastfire_retire_age", 65) or 65)
    annual_spend = float(profile.get("coastfire_annual_spend", 0) or 0)
    return_pct = float(profile.get("coastfire_return_pct", 7.0) or 7.0)
    mean = return_pct / 100.0
    years = max(0, retire_age - age)
    target = fire_number(annual_spend)
    if target <= 0:
        return {"successPct": None, "p10": None, "p50": None, "p90": None, "scenarios": None,
                "trials": 0, "volPct": round(vol * 100, 1)}

    def fixed(rate_pct):
        return round(invested * (1.0 + rate_pct / 100.0) ** years)

    scenarios = {"low": fixed(return_pct - band_pts), "base": fixed(return_pct),
                 "high": fixed(return_pct + band_pts)}
    if years == 0:
        done = 100.0 if invested >= target else 0.0
        return {"successPct": done, "p10": round(invested), "p50": round(invested),
                "p90": round(invested), "scenarios": scenarios, "trials": 0,
                "volPct": round(vol * 100, 1)}

    rng = random.Random(seed)
    finals = []
    for _ in range(trials):
        bal = invested
        for _y in range(years):
            bal *= 1.0 + max(-0.99, rng.gauss(mean, vol))
        finals.append(bal)
    finals.sort()
    pick = lambda q: round(finals[min(trials - 1, int(q * trials))])  # noqa: E731
    hits = sum(1 for b in finals if b >= target)
    return {"successPct": round(hits / trials * 100.0, 1), "p10": pick(0.10), "p50": pick(0.50),
            "p90": pick(0.90), "scenarios": scenarios, "trials": trials,
            "volPct": round(vol * 100, 1)}

