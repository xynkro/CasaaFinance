"""Tests for the premium-selling digest overlay.

Per user directive 2026-06-30 this is NO LONGER a gate: it never drops a
premium-selling idea. Under a caution flag (GEX SELL_CAUTION / posture
CASH_PRIORITY) it only returns a heads-up banner — the ideas still flow and the
user decides.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.daily_options_scan import gate_digest_candidates


def _cands():
    return [
        {"ticker": "NVDA", "strategy": "PCS"},
        {"ticker": "AAPL", "strategy": "CSP"},
        {"ticker": "MSFT", "strategy": "CC"},
        {"ticker": "AMD", "strategy": "IC"},
        {"ticker": "PLTR", "strategy": "LONG_CALL"},
    ]


class TestDigestOverlay:
    def test_calm_tape_passes_through_no_banner(self):
        kept, banner = gate_digest_candidates(_cands(), {})
        assert len(kept) == 5
        assert banner is None

    def test_sell_caution_keeps_all_ideas_with_headsup_banner(self):
        kept, banner = gate_digest_candidates(_cands(), {"sell_caution": True})
        assert len(kept) == 5  # nothing suppressed
        assert banner is not None
        assert "GEX SELL_CAUTION" in banner
        assert "your call" in banner

    def test_cash_priority_keeps_all_ideas_with_headsup_banner(self):
        kept, banner = gate_digest_candidates(_cands(), {"cash_priority": True})
        assert len(kept) == 5  # low cash never hides ideas
        assert "CASH_PRIORITY" in banner
        assert "your call" in banner

    def test_both_flags_named_in_banner_still_no_suppression(self):
        kept, banner = gate_digest_candidates(
            _cands(), {"sell_caution": True, "cash_priority": True})
        assert len(kept) == 5
        assert "GEX SELL_CAUTION" in banner and "CASH_PRIORITY" in banner

    def test_no_premium_candidates_means_no_banner(self):
        only_long = [{"ticker": "PLTR", "strategy": "LONG_CALL"}]
        kept, banner = gate_digest_candidates(only_long, {"sell_caution": True})
        assert kept == only_long
        assert banner is None

    def test_premium_ideas_always_survive_under_caution(self):
        prem = [{"ticker": "NVDA", "strategy": "PCS"},
                {"ticker": "AAPL", "strategy": "HARVEST_CSP"}]
        kept, banner = gate_digest_candidates(prem, {"sell_caution": True})
        assert kept == prem  # both survive — user decides
        assert "Showing all 2" in banner
