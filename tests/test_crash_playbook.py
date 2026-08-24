"""Tests for scripts.crash_playbook — pre-committed drawdown response.

Pure functions only. The properties that matter: tiers must escalate in the
right order, and hedge drift must catch the real 2026-08-24 finding (VIXM at
1.6% against a 5% target) rather than reporting the sleeve as fine.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from scripts.crash_playbook import drawdown_pct, hedge_drift, tier_for


# ── drawdown ────────────────────────────────────────────────────────────────
def test_drawdown_from_trailing_high():
    assert drawdown_pct([100, 120, 108]) == pytest.approx(-10.0)


def test_at_the_high_is_flat():
    assert drawdown_pct([100, 110, 110]) == 0.0


def test_ignores_zeros_and_blanks():
    assert drawdown_pct([0, 100, 0, 90]) == pytest.approx(-10.0)


def test_empty_series_is_zero_not_a_crash():
    assert drawdown_pct([]) == 0.0
    assert drawdown_pct([0, 0]) == 0.0


# ── tiers ───────────────────────────────────────────────────────────────────
def test_tier_ladder():
    assert tier_for(0.0)["name"] == "NORMAL"
    assert tier_for(-3.0)["name"] == "NORMAL"
    assert tier_for(-5.0)["name"] == "PULLBACK"
    assert tier_for(-7.5)["name"] == "PULLBACK"
    assert tier_for(-10.0)["name"] == "CORRECTION"
    assert tier_for(-19.9)["name"] == "CORRECTION"
    assert tier_for(-20.0)["name"] == "BEAR"
    assert tier_for(-45.0)["name"] == "BEAR"


def test_every_tier_carries_a_pre_committed_action():
    for dd in (0, -5, -10, -20, -60):
        assert tier_for(dd)["action"].strip()


# ── hedge drift ─────────────────────────────────────────────────────────────
def test_catches_the_real_vixm_shortfall():
    """The 2026-08-24 book: VIXM $140 of $8,842 = 1.6% against a 5% target."""
    held = {"VIXM": 140.0, "IEF": 186.0, "TLT": 574.0, "GLDM": 457.0, "SCHD": 3687.0}
    d = {x["slot"]: x for x in hedge_drift(held, 8842.0)}
    assert d["VIXM"]["status"] == "LIGHT"
    assert round(d["VIXM"]["have_pct"], 1) == 1.6
    assert d["VIXM"]["gap_pct"] < -3.0


def test_proxies_count_toward_their_slot():
    held = {"IEF": 186.0, "TLT": 574.0, "GLDM": 457.0}
    d = {x["slot"]: x for x in hedge_drift(held, 8842.0)}
    assert d["IEF"]["status"] == "OK"        # IEF+TLT = 8.6% vs 6% target
    assert d["GLD"]["status"] == "OK"        # GLDM alone = 5.2% vs 4% target
    assert "TLT" in d["IEF"]["via"] and "GLDM" in d["GLD"]["via"]


def test_absent_slot_is_flagged_absent_not_light():
    d = {x["slot"]: x for x in hedge_drift({"SCHD": 1000.0}, 1000.0)}
    assert d["VIXM"]["status"] == "ABSENT"
    assert d["VIXM"]["have_usd"] == 0.0


def test_at_target_is_ok():
    held = {"VIXM": 50.0, "IEF": 60.0, "GLD": 40.0}
    d = {x["slot"]: x for x in hedge_drift(held, 1000.0)}
    assert all(v["status"] == "OK" for v in d.values())


def test_zero_book_does_not_divide_by_zero():
    d = hedge_drift({}, 0.0)
    assert all(x["have_pct"] == 0.0 for x in d)
