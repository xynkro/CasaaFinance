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
    small = realized_kelly_inputs("CSP", _rows("CSP", 16, 4))   # n=20, measured wr 0.80
    large = realized_kelly_inputs("CSP", _rows("CSP", 160, 40)) # n=200, measured wr 0.80
    # Both measured at 0.80; large sample should be closer to 0.80 than small
    assert large[0] > small[0]
    assert small[0] >= 0.70  # never below prior when measured is above it


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
