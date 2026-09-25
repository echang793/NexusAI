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
    }
