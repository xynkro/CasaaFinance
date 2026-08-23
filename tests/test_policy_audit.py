"""Tests for scripts.policy_audit — the repeatable policy re-check.

Pure functions only (no Sheets I/O). The property that matters: the audit must
reproduce the 2026-08-20 findings when fed 2026-08-20-shaped data, so a future
run genuinely re-tests the policy instead of rubber-stamping it.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.policy_audit import (
    dedupe, grade_alerts, grade_by_strategy, pearson, score_quartiles,
)


# ── pearson ──────────────────────────────────────────────────────────────────
def test_pearson_perfect_positive():
    assert pearson([(1, 1), (2, 2), (3, 3)]) == 1.0


def test_pearson_perfect_negative():
    assert pearson([(1, 3), (2, 2), (3, 1)]) == -1.0


def test_pearson_undefined_cases_return_zero():
    assert pearson([]) == 0.0
    assert pearson([(1, 1)]) == 0.0
    assert pearson([(5, 1), (5, 2), (5, 3)]) == 0.0  # zero variance in x


# ── dedupe ───────────────────────────────────────────────────────────────────
def test_dedupe_collapses_repeat_evaluations():
    r = {"scan_date": "2026-04-17", "eval_date": "2026-05-22", "ticker": "HIMS",
         "strategy": "CSP", "strike": "26", "expiry": "20260522"}
    assert len(dedupe([dict(r), dict(r), dict(r)])) == 1


def test_dedupe_keeps_genuinely_different_rows():
    a = {"scan_date": "2026-04-17", "eval_date": "2026-05-22", "ticker": "HIMS",
         "strategy": "CSP", "strike": "26", "expiry": "20260522"}
    b = dict(a, strike="27")
    assert len(dedupe([a, b])) == 2


# ── grade_by_strategy ────────────────────────────────────────────────────────
def _row(strat, fwd, outcome):
    return {"strategy": strat, "fwd_return_pct": fwd, "strategy_outcome": outcome,
            "scan_date": "d", "eval_date": fwd, "ticker": strat, "strike": fwd,
            "expiry": "e"}


def test_grade_by_strategy_computes_win_rate_and_return():
    rows = [_row("CSP", "2.0", "WIN"), _row("CSP", "1.0", "WIN"),
            _row("CSP", "-3.0", "LOSS"), _row("PCS", "-5.0", "LOSS")]
    got = {g["strategy"]: g for g in grade_by_strategy(rows)}
    assert got["CSP"]["n"] == 3
    assert round(got["CSP"]["win_pct"]) == 67
    assert got["CSP"]["avg_fwd"] == 0.0
    assert got["PCS"]["win_pct"] == 0.0


def test_grade_by_strategy_sorted_by_sample_size():
    rows = [_row("PCS", "1", "WIN")] + [_row("CSP", "1", "WIN") for _ in range(3)]
    assert grade_by_strategy(rows)[0]["strategy"] == "CSP"


def test_grade_by_strategy_survives_missing_fields():
    rows = [{"strategy": "CC"}, {"strategy": "CC", "fwd_return_pct": "junk"}]
    g = grade_by_strategy(rows)[0]
    assert g["n"] == 2 and g["avg_fwd"] is None and g["win_pct"] is None


# ── score_quartiles ──────────────────────────────────────────────────────────
def test_score_quartiles_detects_the_inversion():
    # High score -> negative forward return, the 2026-08-20 finding.
    pairs = [(float(s), float(100 - s)) for s in range(1, 101)]
    q = score_quartiles(pairs)
    assert len(q) == 4
    assert q[0]["avg_score"] < q[-1]["avg_score"]      # ordered by score
    assert q[0]["avg_fwd"] > q[-1]["avg_fwd"]          # inverted payoff
    assert pearson(pairs) < 0


def test_score_quartiles_needs_four_points():
    assert score_quartiles([(1.0, 1.0), (2.0, 2.0)]) == []


# ── grade_alerts ─────────────────────────────────────────────────────────────
def _alert(tk, strat, entry, cur, at="2026-08-01T090000"):
    return {"ticker": tk, "strategy": strat, "entry_price": entry,
            "current_price": cur, "last_alert_at": at}


def test_small_moves_are_noise_not_calls():
    a = grade_alerts([_alert("UNH", "CC", 100, 100.3)])
    assert a == {"right": 0, "wrong": 0, "noise": 1, "wrongs": []}


def test_trim_that_kept_climbing_is_wrong():
    # The real META TRIM failure: told to trim, it rose 4%.
    a = grade_alerts([_alert("META", "TRIM", 610.37, 635.29)])
    assert a["wrong"] == 1 and a["right"] == 0
    assert a["wrongs"][0]["ticker"] == "META"


def test_trim_that_fell_is_right():
    a = grade_alerts([_alert("NVDA", "TRIM", 214.30, 211.14)])
    assert a["right"] == 1 and a["wrong"] == 0


def test_buy_dip_that_kept_falling_is_wrong():
    a = grade_alerts([_alert("XLP", "BUY_DIP", 85.0, 84.06)], band_pct=0.5)
    assert a["wrong"] == 1


def test_buy_dip_that_recovered_is_right():
    a = grade_alerts([_alert("SPY", "BUY_DIP", 700.0, 720.0)])
    assert a["right"] == 1


def test_alerts_with_unusable_prices_are_skipped():
    a = grade_alerts([_alert("X", "CC", "", 10), _alert("Y", "CC", 0, 10)])
    assert a["right"] == a["wrong"] == a["noise"] == 0


def test_reproduces_the_baseline_shape():
    """Fed the real 2026-08-20 alert set, the grader must still say 1/9/8."""
    real = [
        ("SCHD", "BUY_DIP", 31.66, 31.75), ("SCHD", "BUY_DIP", 31.66, 31.75),
        ("NVDA", "TRIM", 214.86, 214.25), ("META", "TRIM", 610.37, 635.29),
        ("META", "TRIM", 635.22, 632.51), ("NVDA", "TRIM", 214.30, 211.14),
        ("META", "TRIM", 600.00, 627.57), ("AMD", "TRIM", 500.00, 511.57),
        ("XLP", "BUY_DIP", 84.50, 83.30), ("SCHD", "BUY_DIP", 31.90, 31.86),
        ("HIMS", "CSP", 35.47, 33.13), ("UNH", "CC", 424.62, 425.19),
        ("UNH", "CC", 424.62, 426.09), ("XLP", "BUY_DIP", 85.00, 84.06),
        ("UNH", "CC", 426.15, 436.35), ("XLP", "BUY_DIP", 85.00, 84.13),
        ("SPY", "BUY_DIP", 746.00, 738.93), ("META", "TRIM", 591.82, 599.12),
    ]
    a = grade_alerts([_alert(*r) for r in real])
    assert (a["right"], a["wrong"], a["noise"]) == (1, 9, 8)
