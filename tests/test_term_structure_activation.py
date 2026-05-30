"""Tests for F3 — term_structure signal activation in the daily scan."""
from __future__ import annotations

from datetime import date, timedelta
import pytest


def _exp(days: int) -> str:
    return (date.today() + timedelta(days=days)).strftime("%Y-%m-%d")


def test_longer_expiry_picks_separated_expiry():
    """_longer_expiry should pick an expiry well beyond the near one."""
    from scripts.daily_options_scan import _longer_expiry
    expiries = (_exp(7), _exp(35), _exp(63), _exp(120))
    # near_dte ~35 → floor = 55 → candidates are 63 and 120, target 65 → pick 63
    chosen = _longer_expiry(expiries, near_dte=35)
    assert chosen == _exp(63)


def test_longer_expiry_none_when_no_separation():
    """If no expiry is far enough out, return None (skip term structure)."""
    from scripts.daily_options_scan import _longer_expiry
    expiries = (_exp(7), _exp(35), _exp(40))
    # near_dte 35 → floor 55 → nothing qualifies
    assert _longer_expiry(expiries, near_dte=35) is None


def test_ts_slope_flows_into_term_structure_signal():
    """ts_slope injected into the indicator dict must move the CSP score
    via the term_structure signal (weight +4)."""
    from src.technical_score import compute_scores

    base = {"close": 100.0, "rsi_14": 50.0, "sma_20": 100.0,
            "sma_50": 99.0, "sma_200": 95.0, "volatility_annual": 0.30}
    flat = compute_scores(dict(base))
    contango = compute_scores({**base, "ts_slope": 0.4})       # long IV > short
    backwardation = compute_scores({**base, "ts_slope": -0.4})  # stress

    # Contango should lift the CSP score vs flat; backwardation should drop it.
    assert contango["CSP"] > flat["CSP"]
    assert backwardation["CSP"] < flat["CSP"]


def test_compute_ts_slope_sign_matches_signal():
    """Sanity: compute_ts_slope sign matches what the signal expects."""
    from src.term_structure import compute_ts_slope
    from src.technical_score import _sig_term_structure
    # Contango: 25% short, 30% long → positive slope → positive signal
    slope = compute_ts_slope(0.25, 0.30, 35, 65)
    assert slope > 0
    assert _sig_term_structure(slope) > 0
