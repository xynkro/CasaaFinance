"""The policy audit must grade realised P&L, not the underlying's move.

`signal_outcomes` carries two different measures per row:
  * fwd_return_pct  — the STOCK's move between scan and eval
  * outcome_pnl_pct — realised option P&L (csp_settle_pct / cc_settle_pct)

The strategy table took its win rates from the P&L path (`strategy_outcome`)
and its returns column from the stock path, so the two halves of one table
described different quantities. For CSP that overstated the return by ~60%
(+1.61% stock against +1.01% realised), and it was the number used on
2026-09-26 to argue the wheel had an edge.
"""
from scripts.policy_audit import grade_by_strategy


def _row(strategy, stock, pnl, outcome):
    return {"strategy": strategy, "fwd_return_pct": str(stock),
            "outcome_pnl_pct": str(pnl), "strategy_outcome": outcome}


def test_averages_realised_pnl_not_the_stock_move():
    rows = [_row("CSP", 10.0, 1.0, "WIN"), _row("CSP", 20.0, 2.0, "WIN")]
    got = grade_by_strategy(rows)[0]
    assert got["avg_fwd"] == 1.5          # mean of the P&L column
    assert got["avg_fwd"] != 15.0         # not the stock column


def test_the_two_columns_can_disagree_in_sign():
    """A CSP whose stock fell but whose premium covered it is a WIN.

    Grading off the stock column logs that as a loss — one of the inversions
    csp_settle_pct was written to fix.
    """
    rows = [_row("CSP", -3.0, 0.8, "WIN")]
    got = grade_by_strategy(rows)[0]
    assert got["avg_fwd"] > 0
    assert got["win_pct"] == 100.0


def test_win_rate_still_comes_from_strategy_outcome():
    rows = [_row("CC", 5.0, 1.0, "WIN"), _row("CC", 5.0, -1.0, "LOSS")]
    got = grade_by_strategy(rows)[0]
    assert got["win_pct"] == 50.0


def test_missing_pnl_cells_are_skipped_not_zeroed():
    rows = [_row("CSP", 10.0, 2.0, "WIN"), {"strategy": "CSP",
            "fwd_return_pct": "9.0", "outcome_pnl_pct": "", "strategy_outcome": "WIN"}]
    got = grade_by_strategy(rows)[0]
    assert got["avg_fwd"] == 2.0          # not 1.0 from averaging in a zero
    assert got["n"] == 2


def test_baseline_returns_were_re_derived_from_the_pnl_column():
    from scripts.policy_audit import BASELINE_STRATEGY
    assert BASELINE_STRATEGY["CSP"][1] == 1.01   # realised, not 1.4 (stock)
    assert BASELINE_STRATEGY["CC"][1] == 1.78    # realised, not 2.8 (stock)
