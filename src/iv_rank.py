"""
iv_rank.py — Robust IV Rank and IV Percentile computation.

IV Rank = (current - 52w_low) / (52w_high - 52w_low) * 100
IV Percentile = % of days in lookback where IV was below current

IV Percentile is more robust (not distorted by single extreme).
Both require sufficient history (MIN_HISTORY_DAYS).
"""
from __future__ import annotations

MIN_HISTORY_DAYS = 30


def compute_iv_rank(iv_current: float, iv_history: list[float]) -> float:
    """
    IV Rank: where current sits in 52w range.
    Returns 0-100 or -1.0 if insufficient data.
    """
    clean = [v for v in iv_history if v and v > 0]
    if len(clean) < MIN_HISTORY_DAYS or iv_current <= 0:
        return -1.0
    lo, hi = min(clean), max(clean)
    if hi <= lo:
        return 50.0
    return round((iv_current - lo) / (hi - lo) * 100, 1)


def compute_iv_percentile(iv_current: float, iv_history: list[float]) -> float:
    """
    IV Percentile: % of days IV was below current. More robust than rank.
    Returns 0-100 or -1.0 if insufficient data.
    """
    clean = [v for v in iv_history if v and v > 0]
    if len(clean) < MIN_HISTORY_DAYS or iv_current <= 0:
        return -1.0
    below = sum(1 for v in clean if v < iv_current)
    return round(below / len(clean) * 100, 1)
