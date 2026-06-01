"""Tests for F2 — realized-stat Kelly inputs with shrinkage to prior."""
from __future__ import annotations

import pytest


def _rows(strategy, n_win, n_loss, win_pnl=2.0, loss_pnl=-8.0):
    rows = []
    for _ in range(n_win):
        rows.append({"strategy": strategy, "strategy_outcome": "WIN",
                     "outcome_pnl_pct": win_pnl})
    for _ in range(n_loss):
        rows.append({"strategy": strategy, "strategy_outcome": "LOSS",
                     "outcome_pnl_pct": loss_pnl})
    return rows


def test_prior_when_no_data():
    from src.option_scanner import realized_kelly_inputs, KELLY_PRIOR_WIN_RATE
    wr, aw, al, n, src = realized_kelly_inputs("CSP", None)
    assert src == "prior"
    assert wr == KELLY_PRIOR_WIN_RATE
    assert n == 0


def test_prior_yields_positive_subcap_size():
    """Regression (A1): the prior must produce a POSITIVE Kelly size under the
    hard cap — not $0, which would clamp the cap and flag EVERY candidate
    'OVERSIZED' on thin history, making the sizing signal inert."""
    from src.option_scanner import (
        realized_kelly_inputs, _fractional_kelly_size, MAX_POSITION_PCT)
    wr, aw, al, n, src = realized_kelly_inputs("CSP", None)
    assert src == "prior"
    size = _fractional_kelly_size(wr, aw, al, 100_000.0)
    assert size > 0, "prior must yield positive Kelly, not $0"
    assert size <= 100_000 * MAX_POSITION_PCT


def test_prior_when_below_min_samples():
    from src.option_scanner import realized_kelly_inputs
    # Only 5 closed trades — below the 20 min
    wr, aw, al, n, src = realized_kelly_inputs("CSP", _rows("CSP", 4, 1))
    assert src == "prior"
    assert n == 5


def test_prior_when_no_losses():
    """Can't form a payoff ratio without at least one loss → prior."""
    from src.option_scanner import realized_kelly_inputs
    wr, aw, al, n, src = realized_kelly_inputs("CSP", _rows("CSP", 30, 0))
    assert src == "prior"


def test_realized_when_enough_samples():
    from src.option_scanner import realized_kelly_inputs
    # 24 wins, 6 losses → 30 closed, measured win rate 0.80
    wr, aw, al, n, src = realized_kelly_inputs("CSP", _rows("CSP", 24, 6))
    assert src == "realized"
    assert n == 30
    # avg_loss normalised to 1.0 in the realized branch
    assert al == 1.0
    # Blended win rate sits between measured (0.80) and prior (0.70)
    assert 0.70 < wr < 0.80


def test_shrinkage_pulls_toward_prior():
    """More samples → closer to the measured value; fewer → closer to prior."""
    from src.option_scanner import realized_kelly_inputs
    small = realized_kelly_inputs("CSP", _rows("CSP", 40, 10))    # n=50, measured wr 0.80
    large = realized_kelly_inputs("CSP", _rows("CSP", 400, 100))  # n=500, measured wr 0.80
    assert small[4] == "realized" and large[4] == "realized"
    # Both measured at 0.80; large sample should be closer to 0.80 than small
    assert large[0] > small[0]
    assert small[0] >= 0.70  # never below prior when measured is above it


def test_requires_minimum_losses():
    """Plenty of gains but < min_losses → untrustworthy ratio → prior."""
    from src.option_scanner import realized_kelly_inputs
    # 40 gains, only 3 losses → below KELLY_MIN_LOSSES (5)
    wr, aw, al, n, src = realized_kelly_inputs("CSP", _rows("CSP", 40, 3))
    assert src == "prior"


def test_cc_negative_win_pnl_does_not_inflate_size():
    """C1 regression: CC 'WIN' rows carrying NEGATIVE pnl (stock fell, call
    expired OTM) must be partitioned as losses by sign — never inflate Kelly."""
    from src.option_scanner import realized_kelly_inputs, _fractional_kelly_size
    # All 28 'WIN'-labelled rows actually lost money (negative fwd return).
    rows = [{"strategy": "CC", "strategy_outcome": "WIN", "outcome_pnl_pct": -1.5}
            for _ in range(20)]
    rows += [{"strategy": "CC", "strategy_outcome": "WIN", "outcome_pnl_pct": -9.0}
             for _ in range(8)]
    wr, aw, al, n, src = realized_kelly_inputs("CC", rows)
    # Zero positive-pnl trades → no gains → cannot form a ratio → prior.
    assert src == "prior"
    assert aw > 0  # never a negative avg_win that trips the max-size guard
    size = _fractional_kelly_size(wr, aw, al, 100_000.0)
    # Falls back to the (positive, capped) prior — NOT an inflated realized bet.
    prior_size = _fractional_kelly_size(
        *realized_kelly_inputs("CSP", None)[:3], 100_000.0)
    assert size == prior_size
    assert size <= 100_000 * 0.05


def test_cc_mixed_outcomes_size_sanely():
    """Mixed CC history (some real gains, many label-wins that lost) should
    yield a LOW win rate and a small—not inflated—size."""
    from src.option_scanner import realized_kelly_inputs, _fractional_kelly_size
    rows = [{"strategy": "CC", "strategy_outcome": "WIN", "outcome_pnl_pct": 2.0}
            for _ in range(15)]                                   # genuine gains
    rows += [{"strategy": "CC", "strategy_outcome": "WIN", "outcome_pnl_pct": -1.5}
             for _ in range(10)]                                  # label-win, lost
    rows += [{"strategy": "CC", "strategy_outcome": "LOSS", "outcome_pnl_pct": -9.0}
             for _ in range(8)]                                   # real losses
    wr, aw, al, n, src = realized_kelly_inputs("CC", rows)
    assert src == "realized"
    assert n == 33
    assert aw > 0                       # payoff ratio strictly positive
    # Only 15/33 trades actually profitable → blended win rate pulled well below
    # the 0.75 prior (exact value depends on shrinkage weight).
    assert wr < 0.60
    size = _fractional_kelly_size(wr, aw, al, 100_000.0)
    assert size <= 100_000 * 0.05       # never exceeds the hard cap


def test_strategy_filter():
    """Rows for other strategies must be ignored."""
    from src.option_scanner import realized_kelly_inputs
    mixed = _rows("CSP", 24, 6) + _rows("CC", 100, 0)
    wr, aw, al, n, src = realized_kelly_inputs("CSP", mixed)
    assert n == 30  # only CSP rows counted


def test_realized_stats_change_kelly_size():
    """A worse realized payoff ratio should shrink the Kelly position size."""
    from src.option_scanner import realized_kelly_inputs, _fractional_kelly_size
    acct = 100_000.0
    # Prior-based size
    pw, paw, pal, _, _ = realized_kelly_inputs("CSP", None)
    prior_size = _fractional_kelly_size(pw, paw, pal, acct)
    # Realized: same win rate-ish but much worse payoff (tiny wins, big losses)
    rows = _rows("CSP", 21, 9, win_pnl=1.0, loss_pnl=-12.0)  # n=30, wr 0.70
    rw, raw, ral, _, src = realized_kelly_inputs("CSP", rows)
    realized_size = _fractional_kelly_size(rw, raw, ral, acct)
    assert src == "realized"
    # Worse payoff ratio → smaller (or equal-capped) size, never larger
    assert realized_size <= prior_size


def test_scratch_excluded():
    """SCRATCH outcomes don't count toward wins or losses."""
    from src.option_scanner import realized_kelly_inputs
    rows = _rows("CSP", 24, 6)
    rows += [{"strategy": "CSP", "strategy_outcome": "SCRATCH",
              "outcome_pnl_pct": 0.0} for _ in range(50)]
    wr, aw, al, n, src = realized_kelly_inputs("CSP", rows)
    assert n == 30  # scratch excluded


def test_pnl_model_filter():
    """accept_pnl_models gates rows by outcome_pnl_pct semantics version: the
    live path counts ONLY premium-inclusive rows (legacy stock-proxy rows carry
    mis-stated P&L and must never be blended); the default (None) counts all."""
    from src.option_scanner import realized_kelly_inputs, KELLY_ACCEPT_PNL_MODELS
    from src.schema import PNL_MODEL_PREMIUM, PNL_MODEL_LEGACY
    rows = [{"strategy": "CSP", "outcome_pnl_pct": 2.0, "pnl_model": PNL_MODEL_PREMIUM}
            for _ in range(24)]
    rows += [{"strategy": "CSP", "outcome_pnl_pct": -8.0, "pnl_model": PNL_MODEL_PREMIUM}
             for _ in range(6)]
    rows += [{"strategy": "CSP", "outcome_pnl_pct": 2.0, "pnl_model": PNL_MODEL_LEGACY}
             for _ in range(50)]                                   # legacy — skipped
    rows += [{"strategy": "CSP", "outcome_pnl_pct": 2.0} for _ in range(50)]  # unversioned

    # Live filter: only the 30 premium_v2 rows are counted.
    _, _, _, n_filtered, src_filtered = realized_kelly_inputs(
        "CSP", rows, accept_pnl_models=KELLY_ACCEPT_PNL_MODELS)
    assert n_filtered == 30
    assert src_filtered == "realized"

    # No filter (back-compat): every row with a parseable pnl counts.
    _, _, _, n_all, _ = realized_kelly_inputs("CSP", rows)
    assert n_all == 130
