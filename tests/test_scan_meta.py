"""Tests for the scan_meta freshness heartbeat (schema + status classifier)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.schema import ScanMetaRow, scan_status


class TestScanStatus:
    def test_ok_when_candidates(self):
        assert scan_status(130, "STANDARD") == "OK"

    def test_no_candidates_when_clean_zero(self):
        """A clean run that found nothing — the case that freezes scan_results."""
        assert scan_status(0, "STANDARD") == "NO_CANDIDATES"
        assert scan_status(0, "CAUTION") == "NO_CANDIDATES"

    def test_halted_overrides_count(self):
        """Macro HALT is reported as HALTED regardless of candidate count."""
        assert scan_status(0, "HALTED") == "HALTED"
        assert scan_status(5, "halted") == "HALTED"  # case-insensitive

    def test_blank_regime_is_safe(self):
        assert scan_status(0, "") == "NO_CANDIDATES"
        assert scan_status(0, None) == "NO_CANDIDATES"  # type: ignore[arg-type]


class TestScanMetaRow:
    def test_build_sets_status_and_fields(self):
        m = ScanMetaRow.build(run_at="2026-06-09T02:56:51", candidates=130,
                              regime="STANDARD", vix=18.0)
        assert m.status == "OK"
        assert m.candidates == 130
        assert m.regime == "STANDARD"
        assert m.run_at == "2026-06-09T02:56:51"

    def test_build_zero_run_is_no_candidates(self):
        m = ScanMetaRow.build(run_at="2026-06-09T02:56:51", candidates=0,
                              regime="STANDARD", vix=18.0)
        assert m.status == "NO_CANDIDATES"

    def test_to_row_matches_headers(self):
        m = ScanMetaRow.build(run_at="2026-06-09T02:56:51", candidates=0,
                              regime="HALTED", vix=31.4)
        row = m.to_row()
        assert len(row) == len(ScanMetaRow.HEADERS)
        assert row == ["2026-06-09T02:56:51", "0", "HALTED", "31.4", "HALTED"]
