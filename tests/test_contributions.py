"""Contribution limits are keyed by tax year; a year with no published table
falls back to the latest known one and says so (never silently stale)."""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import contributions as ct  # noqa: E402


def test_2026_limits_match_irs_figures():
    lim = ct.limits_for(2026)[0]
    assert lim == {"401k": 24500.0, "hsa": 4400.0, "roth": 7500.0}


def test_2025_limits_still_available():
    assert ct.limits_for(2025)[0] == {"401k": 23500.0, "hsa": 4300.0, "roth": 7000.0}


def test_future_year_falls_back_to_latest_known_and_is_flagged():
    lim, used_year, estimated = ct.limits_for(2031)
    assert used_year == max(ct.LIMITS_BY_YEAR) and estimated is True
    assert lim == ct.LIMITS_BY_YEAR[used_year]


def test_known_year_is_not_flagged_estimated():
    assert ct.limits_for(2026)[2] is False


def test_year_before_any_table_uses_earliest():
    assert ct.limits_for(2001)[1] == min(ct.LIMITS_BY_YEAR)


def test_compute_uses_the_year_and_reports_it():
    out = ct.compute({"contrib_401k_ytd": 10000, "contrib_hsa_ytd": 4400, "contrib_roth_ytd": 0}, year=2026)
    assert out["401k"]["limit"] == 24500.0 and out["401k"]["room"] == 14500.0
    assert out["hsa"]["maxed"] is True
    assert out["roth"]["limit"] == 7500.0
    assert out["401k"]["limitsYear"] == 2026 and out["401k"]["limitsEstimated"] is False


def test_compute_defaults_to_current_year():
    import datetime
    out = ct.compute({})
    assert out["roth"]["limitsYear"] == min(datetime.date.today().year, max(ct.LIMITS_BY_YEAR))
