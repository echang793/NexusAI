"""Investor profile persistence: risk tolerance, horizon, goals, planning inputs."""

import copy
import datetime
import json
import math
import os
import re

PROFILE_FILE = os.getenv("PROFILE_FILE", "profile.json")

DEFAULTS = {
    "name": "",
    "risk_tolerance": "moderate",
    "horizon_years": 10,
    "goals": ["retirement"],
    "age": 35,
    "income_stability": "stable",
    "emergency_fund": True,
    "notes": "",
    # CoastFIRE / full-FIRE tracking — annual_spend of 0 means "not set up
    # yet", keeps those cards invisible until the user opts in via Settings.
    "coastfire_retire_age": 65,
    "coastfire_annual_spend": 0,
    "coastfire_return_pct": 7.0,
    "coastfire_monthly_contribution": 0,
    # Contribution-limit tracker — YTD $ actually contributed this year,
    # entered manually (no transaction feed exists to derive this).
    "contrib_401k_ytd": 0,
    "contrib_hsa_ytd": 0,
    "contrib_roth_ytd": 0,
    # Rebalance drift target (% of invested assets in "stock" vs safe/cash).
    "target_stock_pct": 90.0,
    # Tax-loss harvesting scan threshold, as a negative % (e.g. -10 = flag
    # anything down 10% or more).
    "tlh_threshold_pct": -10.0,
    # Emergency-fund coverage — monthly expense; 0 falls back to
    # coastfire_annual_spend / 12 at compute time.
    "monthly_expense": 0,
    # Savings goals [{id, name, target, date, linked: [account names], extra}] and
    # a monthly budget {PLAID_CATEGORY: amount}; both edited from the Planning tab.
    "savings_goals": [],
    "budget": {},
}

MAX_GOALS = 20
MAX_BUDGET_CATEGORIES = 40
_CATEGORY_KEY = re.compile(r"^[A-Z][A-Z_]{0,39}$")

VALID_RISK = {"conservative", "moderate", "aggressive"}
VALID_GOALS = {"retirement", "wealth_building", "income", "preservation"}
VALID_STABILITY = {"stable", "variable", "uncertain"}

# (field, min, max) for simple clamped-float fields handled generically.
_FLOAT_FIELDS = [
    ("coastfire_annual_spend", 0.0, None),
    ("coastfire_return_pct", 0.0, 20.0),
    ("coastfire_monthly_contribution", 0.0, None),
    ("contrib_401k_ytd", 0.0, None),
    ("contrib_hsa_ytd", 0.0, None),
    ("contrib_roth_ytd", 0.0, None),
    ("target_stock_pct", 0.0, 100.0),
    ("tlh_threshold_pct", -100.0, 0.0),
    ("monthly_expense", 0.0, None),
]


def load_profile(path=None):
    """Load profile from JSON. Returns dict with defaults if missing/invalid."""
    path = path or PROFILE_FILE
    if not os.path.exists(path):
        return copy.deepcopy(DEFAULTS)
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return _coerce(data)
    except Exception:
        return copy.deepcopy(DEFAULTS)


def save_profile(profile, path=None):
    """Persist profile to JSON. Returns the cleaned dict."""
    path = path or PROFILE_FILE
    clean = _coerce(profile)
    with open(path, "w") as f:
        json.dump(clean, f, indent=2)
    return clean


def _clamped_float(p, field, lo, hi):
    try:
        v = float(p.get(field, DEFAULTS[field]))
    except (TypeError, ValueError):
        v = DEFAULTS[field]
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


def _finite_float(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _clean_goals(raw):
    goals, used = [], set()
    for g in (raw if isinstance(raw, list) else []):
        if not isinstance(g, dict) or len(goals) >= MAX_GOALS:
            continue
        name = str(g.get("name") or "").strip()[:60]
        target = _finite_float(g.get("target"))
        if not name or target is None or target <= 0:
            continue
        date = str(g.get("date") or "")
        try:
            datetime.date.fromisoformat(date)
        except ValueError:
            date = ""
        extra = _finite_float(g.get("extra"))
        linked = [str(n).strip()[:80] for n in (g.get("linked") or []) if str(n).strip()][:10]
        base = re.sub(r"[^a-z0-9]+", "-", str(g.get("id") or name).lower()).strip("-")[:40] or "goal"
        gid, n = base, 2
        while gid in used:
            gid, n = f"{base}-{n}", n + 1
        used.add(gid)
        goals.append({"id": gid, "name": name, "target": min(target, 1e9), "date": date,
                      "linked": linked, "extra": max(0.0, extra or 0.0)})
    return goals


def _clean_budget(raw):
    out = {}
    for k, v in (raw.items() if isinstance(raw, dict) else []):
        amount = _finite_float(v)
        if isinstance(k, str) and _CATEGORY_KEY.match(k) and amount is not None and amount >= 0 \
                and len(out) < MAX_BUDGET_CATEGORIES:
            out[k] = amount
    return out


def _coerce(p):
    """Validate and clamp profile fields to safe ranges."""
    p = p or {}

    risk = str(p.get("risk_tolerance", DEFAULTS["risk_tolerance"])).strip().lower()
    if risk not in VALID_RISK:
        risk = DEFAULTS["risk_tolerance"]

    try:
        horizon = int(p.get("horizon_years", DEFAULTS["horizon_years"]))
    except (TypeError, ValueError):
        horizon = DEFAULTS["horizon_years"]
    horizon = max(1, min(40, horizon))

    raw_goals = p.get("goals", DEFAULTS["goals"])
    if isinstance(raw_goals, str):
        raw_goals = [raw_goals]
    goals = [g for g in (raw_goals or []) if g in VALID_GOALS]
    if not goals:
        goals = list(DEFAULTS["goals"])

    try:
        age = int(p.get("age", DEFAULTS["age"]))
    except (TypeError, ValueError):
        age = DEFAULTS["age"]
    age = max(18, min(100, age))

    stability = str(p.get("income_stability", DEFAULTS["income_stability"])).strip().lower()
    if stability not in VALID_STABILITY:
        stability = DEFAULTS["income_stability"]

    emergency = bool(p.get("emergency_fund", DEFAULTS["emergency_fund"]))
    notes = str(p.get("notes", "")).strip()
    name = str(p.get("name", DEFAULTS["name"])).strip()

    try:
        cf_retire_age = int(p.get("coastfire_retire_age", DEFAULTS["coastfire_retire_age"]))
    except (TypeError, ValueError):
        cf_retire_age = DEFAULTS["coastfire_retire_age"]
    cf_retire_age = max(18, min(100, cf_retire_age))

    out = {
        "name": name,
        "risk_tolerance": risk,
        "horizon_years": horizon,
        "goals": goals,
        "age": age,
        "income_stability": stability,
        "emergency_fund": emergency,
        "notes": notes,
        "coastfire_retire_age": cf_retire_age,
    }
    for field, lo, hi in _FLOAT_FIELDS:
        out[field] = _clamped_float(p, field, lo, hi)
    out["savings_goals"] = _clean_goals(p.get("savings_goals"))
    out["budget"] = _clean_budget(p.get("budget"))
    return out


def profile_summary(profile):
    """One-line summary for sidebar display."""
    risk = (profile or {}).get("risk_tolerance", "?").title()
    horizon = (profile or {}).get("horizon_years", "?")
    return f"{risk} · {horizon}yr horizon"
