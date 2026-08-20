"""Tests for the repeat-alert cooldown (2026-08-20 audit fix).

Why: `decision_key` embeds the DATE, so every new day minted a fresh key with no
memory of yesterday's page. That is how META TRIM fired 3x while META climbed,
XLP BUY_DIP fired 3x into a falling knife, and UNH CC fired 3x — six of the nine
genuinely-wrong pushes were just three names repeating.

The cooldown keys on (account, ticker, strategy) WITHOUT the date, so a name that
already paged cannot re-page for `cooldown_days`.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.trigger_alerts import cooldown_blocker


def _ledger(*rows):
    """Build a prior_alerts dict like load_alert_state returns."""
    out = {}
    for n, (tk, acct, strat, at) in enumerate(rows):
        out[f"2026-08-{n + 1:02d}|{acct}|{tk}|{strat}|0.00"] = {
            "ticker": tk, "account": acct, "strategy": strat,
            "last_alert_at": at, "last_alert_state": "act_now" if at else "",
        }
    return out


TODAY = "2026-08-20"


def test_blocks_a_repeat_within_the_window():
    led = _ledger(("META", "caspar", "TRIM", "2026-08-17T101500"))
    assert cooldown_blocker("META", "caspar", "TRIM", led, TODAY, cooldown_days=7) == "2026-08-17"


def test_allows_once_the_window_has_passed():
    led = _ledger(("META", "caspar", "TRIM", "2026-08-01T101500"))
    assert cooldown_blocker("META", "caspar", "TRIM", led, TODAY, cooldown_days=7) is None


def test_boundary_is_inclusive_of_the_last_day():
    led = _ledger(("XLP", "caspar", "BUY_DIP", "2026-08-13T090000"))
    # exactly 7 days ago → still inside a 7-day cooldown
    assert cooldown_blocker("XLP", "caspar", "BUY_DIP", led, TODAY, cooldown_days=7) == "2026-08-13"
    assert cooldown_blocker("XLP", "caspar", "BUY_DIP", led, TODAY, cooldown_days=6) is None


def test_different_ticker_is_not_blocked():
    led = _ledger(("META", "caspar", "TRIM", "2026-08-19T101500"))
    assert cooldown_blocker("AMD", "caspar", "TRIM", led, TODAY, cooldown_days=7) is None


def test_different_strategy_is_not_blocked():
    led = _ledger(("UNH", "caspar", "CC", "2026-08-19T101500"))
    assert cooldown_blocker("UNH", "caspar", "CSP", led, TODAY, cooldown_days=7) is None


def test_different_account_is_not_blocked():
    # Caspar and Sarah hold separately; Sarah's page shouldn't mute Caspar's.
    led = _ledger(("UNH", "sarah", "CC", "2026-08-19T101500"))
    assert cooldown_blocker("UNH", "caspar", "CC", led, TODAY, cooldown_days=7) is None


def test_case_insensitive_matching():
    led = _ledger(("meta", "CASPAR", "trim", "2026-08-18T101500"))
    assert cooldown_blocker("META", "caspar", "TRIM", led, TODAY, cooldown_days=7) == "2026-08-18"


def test_rows_that_never_alerted_do_not_block():
    led = _ledger(("META", "caspar", "TRIM", ""))
    assert cooldown_blocker("META", "caspar", "TRIM", led, TODAY, cooldown_days=7) is None


def test_most_recent_alert_wins():
    led = _ledger(("META", "caspar", "TRIM", "2026-07-01T090000"),
                  ("META", "caspar", "TRIM", "2026-08-18T090000"))
    assert cooldown_blocker("META", "caspar", "TRIM", led, TODAY, cooldown_days=7) == "2026-08-18"


def test_fails_open_on_unparseable_timestamp():
    # A bad timestamp must never silence alerts — better a dupe than silence.
    led = _ledger(("META", "caspar", "TRIM", "not-a-date"))
    assert cooldown_blocker("META", "caspar", "TRIM", led, TODAY, cooldown_days=7) is None


def test_zero_days_disables_the_cooldown():
    led = _ledger(("META", "caspar", "TRIM", "2026-08-20T090000"))
    assert cooldown_blocker("META", "caspar", "TRIM", led, TODAY, cooldown_days=0) is None


def test_the_real_meta_repeat_would_have_been_blocked():
    """Regression: the actual 28 May / 4 Jun / 10 Aug META TRIM sequence."""
    led = _ledger(("META", "caspar", "TRIM", "2026-05-28T101500"))
    # 4 Jun is 7 days after 28 May → blocked by a 7-day cooldown
    assert cooldown_blocker("META", "caspar", "TRIM", led, "2026-06-04", cooldown_days=7) == "2026-05-28"
