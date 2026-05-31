"""Tests for scripts/tail_hedge_run.py — the convex tail-hedge layer."""
import sys
from pathlib import Path
import importlib.util

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_spec = importlib.util.spec_from_file_location(
    "tail_hedge_run",
    Path(__file__).resolve().parent.parent / "scripts" / "tail_hedge_run.py")
th = importlib.util.module_from_spec(_spec)
sys.modules["tail_hedge_run"] = th
_spec.loader.exec_module(th)


# ── budget sizing ────────────────────────────────────────────────────────────

def test_budget_standard_is_one_percent():
    assert th.hedge_budget_pct("STANDARD", 16, True) == 0.010


def test_budget_leans_in_when_regime_sours():
    assert th.hedge_budget_pct("REDUCE_ONLY", 16, True) == 0.016
    assert th.hedge_budget_pct("STANDARD", 16, False) == 0.016   # weak trend


def test_budget_trims_in_dead_calm_bull():
    assert th.hedge_budget_pct("STANDARD", 12, True) == 0.006


def test_budget_does_not_chase_a_vol_spike():
    # already spiked → halved (don't overpay for insurance after the fire starts)
    assert th.hedge_budget_pct("REDUCE_ONLY", 30, True) == round(0.016 * 0.5, 4)


def test_budget_capped_at_2pct():
    assert th.hedge_budget_pct("HALT", 10, False) <= th.HEDGE_CAP_PCT


# ── structure ────────────────────────────────────────────────────────────────

def test_put_spread_strikes():
    short, long_ = th.put_spread_strikes(500.0)
    assert short == 475.0 and long_ == 440.0 and short > long_


def test_spread_debit_is_sane():
    short, long_ = th.put_spread_strikes(500.0)
    debit = th.spread_debit_per_contract(500.0, short, long_, 16.0, 60)
    # a 5%/12% OTM SPY put spread, 60d, 16 vol — order of a few hundred dollars
    assert 100 < debit < 1500


# ── account-aware hedge selection ────────────────────────────────────────────

def test_small_account_falls_back_to_vix_etf():
    # $9k account: one SPY spread blows the 2% cap → VIXM fractional sleeve.
    h = th.build_hedge(9000, 500, 16, "REDUCE_ONLY", True)
    assert h and h["type"] == "vol_etf" and h["ticker"] == "VIXM"
    assert h["dollars"] > 0 and h["budget_pct"] == 0.016


def test_larger_account_gets_convex_put_spread():
    # $45k account: budget fits >=1 SPY put-spread → convex hedge.
    h = th.build_hedge(45000, 500, 16, "REDUCE_ONLY", True)
    assert h and h["type"] == "put_spread" and h["qty"] >= 1
    assert h["max_payoff"] > h["cost"]          # convex: payoff >> cost


def test_zero_nlv_returns_none():
    assert th.build_hedge(0, 500, 16, "STANDARD", True) is None


def test_no_spot_still_hedges_via_etf():
    # SPX feed missing (spot=0) → can't build a spread, but still recommend VIXM.
    h = th.build_hedge(45000, 0, 16, "STANDARD", True)
    assert h and h["type"] == "vol_etf"
