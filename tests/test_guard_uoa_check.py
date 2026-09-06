"""Tests for the UOA-quality half of the sheet invariant guard.

Bug 2 (2026-09-06) ran for 12 days writing aggressor=UNKNOWN / quality=0 for
every alert, because the values were dropped crossing UoaAlert -> UoaAlertRow.
Nothing errored and nothing watched it. This check is the watcher; these tests
pin its behaviour, especially the cases where it must NOT cry wolf.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.dupe_guard import check_uoa_quality

TODAY = "2026-09-10"
LIVE = "2026-09-06"


def _a(date, quality=0, aggressor="UNKNOWN"):
    return {"date": date, "quality": str(quality), "aggressor": aggressor}


def test_flags_the_real_bug_all_defaults():
    alerts = [_a("2026-09-09") for _ in range(20)]
    p = check_uoa_quality(alerts, TODAY, live_from=LIVE)
    assert p and "default aggressor=UNKNOWN" in p


def test_healthy_when_quality_is_populated():
    alerts = [_a("2026-09-09", quality=70) for _ in range(20)]
    assert check_uoa_quality(alerts, TODAY, live_from=LIVE) is None


def test_healthy_when_aggressor_readable_even_if_quality_low():
    """A readable side is real output even if the score is modest."""
    alerts = [_a("2026-09-09", quality=0, aggressor="SELL_INITIATED") for _ in range(20)]
    assert check_uoa_quality(alerts, TODAY, live_from=LIVE) is None


def test_partial_population_is_healthy():
    """Some UNKNOWN is normal — bad quotes exist. Only ALL-default is a failure."""
    alerts = [_a("2026-09-09") for _ in range(18)] + [_a("2026-09-09", quality=55)]
    assert check_uoa_quality(alerts, TODAY, live_from=LIVE) is None


def test_small_sample_does_not_cry_wolf():
    """Weekend / thin scan: too few alerts to judge is NOT a failure."""
    alerts = [_a("2026-09-09") for _ in range(3)]
    assert check_uoa_quality(alerts, TODAY, live_from=LIVE) is None


def test_no_recent_alerts_is_not_a_failure():
    assert check_uoa_quality([], TODAY, live_from=LIVE) is None


def test_pre_fix_alerts_are_excluded():
    """Alerts written before the layer went live legitimately carry defaults."""
    alerts = [_a("2026-08-28") for _ in range(50)]
    assert check_uoa_quality(alerts, TODAY, live_from=LIVE) is None


def test_lookback_window_bounds_the_check():
    """Old-but-post-live alerts outside the window don't trigger it."""
    alerts = [_a("2026-09-06") for _ in range(20)]
    assert check_uoa_quality(alerts, "2026-09-30", live_from=LIVE, lookback_days=3) is None


def test_unparseable_clock_fails_open():
    alerts = [_a("2026-09-09") for _ in range(20)]
    assert check_uoa_quality(alerts, "not-a-date", live_from=LIVE) is None


def test_junk_quality_values_do_not_crash():
    alerts = [{"date": "2026-09-09", "quality": "abc", "aggressor": "UNKNOWN"}
              for _ in range(20)]
    assert check_uoa_quality(alerts, TODAY, live_from=LIVE) is not None
