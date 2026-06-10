"""Tests for the SELL_CAUTION / CASH_PRIORITY Telegram digest gate."""
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


class TestDigestGate:
    def test_calm_tape_passes_through(self):
        kept, banner = gate_digest_candidates(_cands(), {})
        assert len(kept) == 5
        assert banner is None

    def test_sell_caution_suppresses_premium_selling(self):
        kept, banner = gate_digest_candidates(_cands(), {"sell_caution": True})
        assert [c["strategy"] for c in kept] == ["LONG_CALL"]
        assert banner is not None
        assert "4 premium-selling ideas suppressed" in banner
        assert "GEX SELL_CAUTION" in banner

    def test_cash_priority_also_gates(self):
        kept, banner = gate_digest_candidates(_cands(), {"cash_priority": True})
        assert [c["strategy"] for c in kept] == ["LONG_CALL"]
        assert "posture CASH_PRIORITY" in banner

    def test_both_flags_named_in_banner(self):
        _, banner = gate_digest_candidates(
            _cands(), {"sell_caution": True, "cash_priority": True})
        assert "GEX SELL_CAUTION" in banner and "posture CASH_PRIORITY" in banner

    def test_no_premium_candidates_means_no_banner(self):
        """Nothing to suppress → no banner even when the flags fire."""
        only_long = [{"ticker": "PLTR", "strategy": "LONG_CALL"}]
        kept, banner = gate_digest_candidates(only_long, {"sell_caution": True})
        assert kept == only_long
        assert banner is None

    def test_all_suppressed_keeps_banner_for_visible_silence(self):
        """Everything suppressed → empty list + banner (the digest still sends)."""
        prem = [{"ticker": "NVDA", "strategy": "PCS"},
                {"ticker": "AAPL", "strategy": "HARVEST_CSP"}]
        kept, banner = gate_digest_candidates(prem, {"sell_caution": True})
        assert kept == []
        assert "2 premium-selling ideas suppressed" in banner
