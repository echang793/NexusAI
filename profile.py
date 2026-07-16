"""Investor profile persistence: risk tolerance, horizon, goals, etc."""

import json
import os

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
}

VALID_RISK = {"conservative", "moderate", "aggressive"}
VALID_GOALS = {"retirement", "wealth_building", "income", "preservation"}
VALID_STABILITY = {"stable", "variable", "uncertain"}


def load_profile(path=None):
    """Load profile from JSON. Returns dict with defaults if missing/invalid."""
    path = path or PROFILE_FILE
    if not os.path.exists(path):
        return dict(DEFAULTS)
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return _coerce(data)
    except Exception:
        return dict(DEFAULTS)


def save_profile(profile, path=None):
    """Persist profile to JSON. Returns the cleaned dict."""
    path = path or PROFILE_FILE
    clean = _coerce(profile)
    with open(path, "w") as f:
        json.dump(clean, f, indent=2)
    return clean


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

    return {
        "name": name,
        "risk_tolerance": risk,
        "horizon_years": horizon,
        "goals": goals,
        "age": age,
        "income_stability": stability,
        "emergency_fund": emergency,
        "notes": notes,
    }


def profile_summary(profile):
    """One-line summary for sidebar display."""
    risk = (profile or {}).get("risk_tolerance", "?").title()
    horizon = (profile or {}).get("horizon_years", "?")
    return f"{risk} · {horizon}yr horizon"
