"""Retirement-account contribution-limit tracking.

No transaction feed exists, so "YTD contributed" is a manual number the
user enters in Settings — this module just compares it to the limit.
Limits below are 2025 IRS figures (single filer, under 50, HSA self-only
coverage); they're constants rather than editable because they're policy
numbers, not personal data — bump them here when the IRS updates annually.
"""

LIMITS = {
    "401k": 23500.0,
    "hsa": 4300.0,
    "roth": 7000.0,
}

LABELS = {
    "401k": "401(k)",
    "hsa": "HSA",
    "roth": "Roth IRA",
}


def compute(profile: dict) -> dict:
    ytd = {
        "401k": float(profile.get("contrib_401k_ytd", 0) or 0),
        "hsa": float(profile.get("contrib_hsa_ytd", 0) or 0),
        "roth": float(profile.get("contrib_roth_ytd", 0) or 0),
    }
    out = {}
    for key, limit in LIMITS.items():
        used = ytd[key]
        room = max(0.0, limit - used)
        pct_used = (used / limit * 100.0) if limit else 0.0
        out[key] = {
            "label": LABELS[key],
            "limit": limit,
            "ytd": round(used, 2),
            "room": round(room, 2),
            "pctUsed": round(min(pct_used, 999.0), 1),
            "maxed": used >= limit,
        }
    return out
