"""Retirement-account contribution-limit tracking.

"YTD contributed" is entered in Settings (no transaction feed feeds it yet);
this module compares it to the limit for the current tax year.
Limits are IRS figures (single filer, under 50, HSA self-only coverage),
keyed by year. Sources: 2025 and 2026 401(k)/IRA from IRS news releases,
HSA from Rev. Proc. 2024-25 and 2025-19. Add the next year's row when the IRS
announces it (mid-November); until then the latest known year is used and the
result is flagged `limitsEstimated` so a stale table is visible, not silent.
"""

import datetime

LIMITS_BY_YEAR = {
    2025: {"401k": 23500.0, "hsa": 4300.0, "roth": 7000.0},
    2026: {"401k": 24500.0, "hsa": 4400.0, "roth": 7500.0},
}


def limits_for(year: int):
    """(limits, year_used, estimated). Falls back to the nearest known year."""
    if year in LIMITS_BY_YEAR:
        return LIMITS_BY_YEAR[year], year, False
    known = sorted(LIMITS_BY_YEAR)
    used = max((y for y in known if y <= year), default=known[0])
    return LIMITS_BY_YEAR[used], used, True


LABELS = {
    "401k": "401(k)",
    "hsa": "HSA",
    "roth": "Roth IRA",
}


def compute(profile: dict, year: int | None = None, detected: dict | None = None) -> dict:
    """`detected` = YTD contributions found in synced Fidelity transactions
    (investment_flows.limit_ytd). A number typed in Settings always wins; the
    detected one only fills in when nothing was typed."""
    limits, used_year, estimated = limits_for(year or datetime.date.today().year)
    manual = {
        "401k": float(profile.get("contrib_401k_ytd", 0) or 0),
        "hsa": float(profile.get("contrib_hsa_ytd", 0) or 0),
        "roth": float(profile.get("contrib_roth_ytd", 0) or 0),
    }
    detected = detected or {}
    out = {}
    for key, limit in limits.items():
        if manual[key] > 0:
            used, source = manual[key], "manual"
        elif (detected.get(key) or 0) > 0:
            used, source = float(detected[key]), "fidelity"
        else:
            used, source = 0.0, "none"
        room = max(0.0, limit - used)
        pct_used = (used / limit * 100.0) if limit else 0.0
        out[key] = {
            "label": LABELS[key],
            "limit": limit,
            "ytd": round(used, 2),
            "room": round(room, 2),
            "pctUsed": round(min(pct_used, 999.0), 1),
            "maxed": used >= limit,
            "limitsYear": used_year,
            "limitsEstimated": estimated,
            "source": source,
            # A 401(k) "contribution" can include employer match, which does not
            # count toward the employee limit; HSA employer money does count.
            "mayIncludeEmployer": key == "401k" and source == "fidelity",
        }
    return out
