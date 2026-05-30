"""Tests for src/exit_plan.py option exit logic — Tranche 3 (F1 deep-loser
guard + F2 live-underlying intrinsic floor)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.exit_plan import compute_option_exit_plan  # noqa: E402


def _plan(**opt):
    base = {"ticker": "X", "credit": 1.0, "last": 0.5, "dte": 30, "moneyness": "OTM",
            "confidence_pct": 0}
    base.update(opt)
    return compute_option_exit_plan(base, {})


# ── F1: deep-loser stop-roll guard ──────────────────────────────────────────

def test_profit_target_still_fires():
    # credit 2.0, buyback 0.5 -> 75% captured -> close (unchanged behavior)
    p = _plan(credit=2.0, last=0.5)
    assert p["status"] == "PROFIT_TARGET_HIT"


def test_deep_loser_triggers_stop_roll():
    # buyback 2.5 vs credit 1.0 -> profit_capture -1.5 <= -1.0 -> STOP_ROLL
    p = _plan(credit=1.0, last=2.5)
    assert p["status"] == "STOP_ROLL"
    assert "STOP ROLLING" in p["recommendation"]


def test_modest_loss_does_not_stop_roll():
    # buyback 1.5 vs credit 1.0 -> profit_capture -0.5 (not past -1.0) -> not STOP_ROLL
    p = _plan(credit=1.0, last=1.5, moneyness="ITM", dte=5)
    assert p["status"] != "STOP_ROLL"


# ── F2: live-underlying intrinsic floor ─────────────────────────────────────

def test_intrinsic_floor_catches_hidden_gap():
    # Stale mark says 0.30 (looks like a 70% WIN), but the underlying gapped to
    # 96 on a 100-strike short PUT -> intrinsic 4.0 -> real buyback >= 4.0 ->
    # profit_capture (1-4)/1 = -3 -> STOP_ROLL. Without the floor this would
    # have wrongly said "CLOSE for 70% profit".
    p = _plan(credit=1.0, last=0.30, strike=100, underlying_last=96, right="P", moneyness="ITM")
    assert p["status"] == "STOP_ROLL"
    assert p["profit_capture_pct"] < 0


def test_intrinsic_floor_does_not_invent_loss_when_otm():
    # Same stale 0.30 mark, but underlying 110 (put well OTM) -> intrinsic 0 ->
    # floor is a no-op -> the 70% profit reading stands.
    p = _plan(credit=1.0, last=0.30, strike=100, underlying_last=110, right="P", moneyness="OTM")
    assert p["status"] == "PROFIT_TARGET_HIT"
    assert p["profit_capture_pct"] == 70.0


def test_intrinsic_floor_short_call_side():
    # Short CALL, strike 100, underlying gapped to 105 -> intrinsic 5 ->
    # buyback >= 5 vs credit 1.0 -> STOP_ROLL.
    p = _plan(credit=1.0, last=0.20, strike=100, underlying_last=105, right="C", moneyness="ITM")
    assert p["status"] == "STOP_ROLL"


def test_missing_underlying_skips_floor():
    # No strike/underlying supplied -> floor skipped, original behavior intact.
    p = _plan(credit=2.0, last=0.5)
    assert p["status"] == "PROFIT_TARGET_HIT"
