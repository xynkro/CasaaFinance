"""Tests for A3 — Phase-2 empirical weight calibration."""
from __future__ import annotations

import pytest


_SIG_COLS = [
    "sig_rsi", "sig_macd", "sig_macd_cross", "sig_bb_pct_b", "sig_bb_squeeze",
    "sig_wvf", "sig_trend", "sig_momentum", "sig_volume_spike", "sig_divergence",
    "sig_candle", "sig_fib_support", "sig_volatility", "sig_vol_regime",
    "sig_iv_rv_ratio", "sig_term_structure",
]


def _make_rows(n=40, strategy="CSP"):
    """Deterministic rows: outcome ramps with the index;
      sig_rsi    = +ramp  → strong POSITIVE corr (CSP rsi weight is -4 → SIGN-FLIP)
      sig_macd   = +ramp  → strong POSITIVE corr (CSP macd weight is +3 → confirmed)
      sig_candle = 0       → zero variance → noise
      others     = 0       → noise
    """
    rows = []
    for i in range(n):
        base = (i - n / 2) / (n / 2)   # ~[-1, 1]
        row = {"strategy": strategy, "outcome_pnl_pct": base * 5.0}
        for c in _SIG_COLS:
            row[c] = 0.0
        row["sig_rsi"] = base       # +corr
        row["sig_macd"] = base      # +corr
        rows.append(row)
    return rows


def test_calibrate_skips_thin_strategy():
    from scripts.signal_feedback import calibrate_weights
    res = calibrate_weights(_make_rows(n=10))
    assert res["CSP"]["skipped"] is not None
    assert res["CSP"]["signals"] == []


def test_calibrate_detects_confirmed_and_flip():
    from scripts.signal_feedback import calibrate_weights
    res = calibrate_weights(_make_rows(n=40))["CSP"]
    assert res["n"] == 40
    byname = {s["signal"]: s for s in res["signals"]}
    # macd: CSP weight +3, corr strongly positive → confirmed
    assert byname["macd"]["corr"] > 0.9
    assert byname["macd"]["verdict"] == "confirmed"
    assert byname["macd"]["suggested"] > 0
    # rsi: CSP weight -4 but corr strongly positive → SIGN-FLIP
    assert byname["rsi"]["corr"] > 0.9
    assert byname["rsi"]["verdict"] == "SIGN-FLIP"
    assert "rsi" in res["flips"]


def test_calibrate_flags_noise():
    from scripts.signal_feedback import calibrate_weights
    res = calibrate_weights(_make_rows(n=40))["CSP"]
    # candle is constant 0 → zero variance → noise
    assert "candle" in res["noise"]
    byname = {s["signal"]: s for s in res["signals"]}
    assert byname["candle"]["verdict"] == "noise"
    assert byname["candle"]["suggested"] == 0.0


def test_calibrate_reports_r2():
    from scripts.signal_feedback import calibrate_weights
    res = calibrate_weights(_make_rows(n=40))["CSP"]
    # rsi/macd perfectly track the outcome → R² near 1
    assert res["r2"] is not None
    assert res["r2"] > 0.9


def test_suggested_preserves_total_budget():
    """Suggested weights should redistribute, roughly preserving total |weight|."""
    from scripts.signal_feedback import calibrate_weights
    from src.technical_score import STRATEGY_WEIGHTS
    res = calibrate_weights(_make_rows(n=40))["CSP"]
    cur_total = sum(abs(w) for w in STRATEGY_WEIGHTS["CSP"].values())
    sug_total = sum(abs(s["suggested"]) for s in res["signals"])
    # Only 2 signals carry correlation here, so suggested concentrates on them,
    # but total should be in the same ballpark as the current budget (not blown up).
    assert sug_total <= cur_total + 1.0


def test_format_report_renders():
    from scripts.signal_feedback import calibrate_weights, format_calibration_report
    txt = format_calibration_report(calibrate_weights(_make_rows(n=40)))
    assert "CSP" in txt
    assert "SIGN-FLIP" in txt
    assert "Calibration" in txt


def test_empty_input():
    from scripts.signal_feedback import calibrate_weights, format_calibration_report
    assert calibrate_weights([]) == {}
    assert "No signal_outcomes" in format_calibration_report({})
