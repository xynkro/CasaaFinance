"""Regression tests for regime_signals_run + RegimeSignalRow.

Two bugs from the 2026-06-11 audit:
  1. parse_ftd read `market_state.quality_score` but ftd-detector emits
     `quality_score` at TOP LEVEL — score was always 0 / label always UNKNOWN,
     and that 0 fed into the exposure-coach composite (CASH_PRIORITY ceiling
     of 4-6% even when FTD was confirmed at quality 95).
  2. raw_json truncation at 5000 chars did a byte-cut that broke `json.loads`
     mid-string — exposure_posture_run silently substituted {} and lost the
     entire regime context. Schema now safe-truncates to a parseable envelope.

These tests pin both behaviors so they don't regress.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.regime_signals_run import (  # noqa: E402
    _compact_raw,
    parse_distribution_day,
    parse_ftd,
    parse_macro_regime,
    parse_market_breadth,
)
from src.schema.macro import (  # noqa: E402
    MAX_JSON_CELL_BYTES,
    ExposurePostureRow,
    RegimeSignalRow,
    _safe_truncate_json,
)


# ---------------- parse_ftd ----------------

def _ftd_payload_confirmed_q95() -> dict:
    """Real-shape FTD detector output: quality_score at TOP LEVEL.

    Mirrors what ftd_detector.py writes (see vendor/skills/ftd-detector/
    scripts/ftd_detector.py around line 191: `analysis = {... "market_state":
    {"combined_state": ...}, "quality_score": quality, ...}`).
    """
    return {
        "metadata": {"generated_at": "2026-06-10 07:42:39"},
        "market_state": {
            "combined_state": "FTD_CONFIRMED",
            "dual_confirmation": True,
            "ftd_index": "QQQ",
        },
        "sp500": {"state": "POST_FTD", "history": [{"date": "2026-06-09", "close": 5300}]},
        "nasdaq": {"state": "POST_FTD", "history": [{"date": "2026-06-09", "close": 18500}]},
        "quality_score": {
            "total_score": 95,
            "signal": "Strong FTD",
            "guidance": "Aggressively increase exposure to 75-100%.",
            "exposure_range": "75-100%",
            "breakdown": {"day_count": 30, "volume": 25, "gap": 20, "strength": 20},
        },
        "post_ftd_distribution": {"distribution_count": 0, "days_monitored": 5},
        "ftd_invalidation": {"invalidated": False},
        "power_trend": {"power_trend": True, "conditions_met": 3},
    }


def test_parse_ftd_reads_top_level_quality_score():
    """The bug: parser was reading market_state.quality_score (always {}).

    Lock in that the parser pulls score=95 from top-level quality_score.
    """
    sig = parse_ftd(_ftd_payload_confirmed_q95())
    assert sig.source == "ftd"
    assert sig.score == 95.0, (
        "FTD score must come from top-level quality_score.total_score, "
        "not market_state.quality_score (which doesn't exist)"
    )


def test_parse_ftd_label_is_combined_state():
    """Label must surface the operational state for the brain + exposure-coach."""
    sig = parse_ftd(_ftd_payload_confirmed_q95())
    assert sig.label == "FTD_CONFIRMED"


def test_parse_ftd_summary_includes_signal_text():
    sig = parse_ftd(_ftd_payload_confirmed_q95())
    assert "Strong FTD" in sig.summary
    assert "75-100%" in sig.summary


def test_parse_ftd_no_quality_score_falls_back_to_unknown():
    """Empty/missing payload yields score=0 + label=UNKNOWN, not a crash."""
    sig = parse_ftd({})
    assert sig.source == "ftd"
    assert sig.score == 0.0
    assert sig.label == "UNKNOWN"


def test_parse_ftd_only_signal_no_combined_state():
    """Label falls back to quality signal when combined_state is absent."""
    sig = parse_ftd({
        "quality_score": {"total_score": 50, "signal": "Moderate FTD",
                          "exposure_range": "50-75%"},
    })
    assert sig.score == 50.0
    assert sig.label == "Moderate FTD"


# ---------------- parse_macro_regime contract ----------------

def test_parse_macro_regime_reads_top_level_composite_and_regime():
    """Macro regime detector emits composite + regime at top level (audit lock)."""
    sig = parse_macro_regime({
        "metadata": {"generated_at": "2026-06-10 07:42:39"},
        "composite": {"composite_score": 72.5, "zone": "Transition Zone (Preparing)"},
        "regime": {
            "current_regime": "concentration",
            "regime_label": "Concentration",
            "confidence": "HIGH",
            "transition_probability": {"probability_range": "30-50%"},
        },
        "components": {},
    })
    assert sig.source == "macro_regime"
    assert sig.score == 72.5
    assert sig.label == "Concentration"


# ---------------- parse_distribution_day contract ----------------

def test_parse_distribution_day_normal_high_severe_mapping():
    """Risk levels map to scores where higher = healthier."""
    base = {"portfolio_action": {"action": "hold", "target_exposure_pct": 80}}
    assert parse_distribution_day({**base, "market_distribution_state": {"overall_risk_level": "NORMAL"}}).score == 80.0
    assert parse_distribution_day({**base, "market_distribution_state": {"overall_risk_level": "HIGH"}}).score == 25.0
    assert parse_distribution_day({**base, "market_distribution_state": {"overall_risk_level": "SEVERE"}}).score == 5.0


# ---------------- parse_market_breadth contract ----------------

def test_parse_market_breadth_reads_composite():
    sig = parse_market_breadth({
        "composite": {
            "composite_score": 46,
            "zone": "Weakening",
            "guidance": "Reduce exposure to 50%.",
            "exposure_guidance": "50% max",
        },
    })
    assert sig.score == 46.0
    assert sig.label == "Weakening"
    assert "50% max" in sig.summary


# ---------------- _compact_raw (per-source compaction) ----------------

def test_compact_raw_ftd_drops_index_history():
    raw = _ftd_payload_confirmed_q95()
    compact = _compact_raw("ftd", raw)
    # The big history arrays are gone…
    assert "history" not in compact["sp500"]
    assert "history" not in compact["nasdaq"]
    # …but everything the brain needs is intact.
    assert compact["market_state"]["combined_state"] == "FTD_CONFIRMED"
    assert compact["quality_score"]["total_score"] == 95
    assert compact["quality_score"]["signal"] == "Strong FTD"


def test_compact_raw_distribution_day_drops_per_dd_arrays():
    raw = {
        "market_distribution_state": {
            "overall_risk_level": "HIGH",
            "index_results": [
                {
                    "symbol": "QQQ",
                    "d25_count": 6,
                    "active_distribution_days": [{"date": f"2026-05-{i:02d}"} for i in range(1, 26)],
                    "removed_distribution_days": [{"date": f"2026-04-{i:02d}"} for i in range(1, 30)],
                    "risk_level": "HIGH",
                },
            ],
        },
        "portfolio_action": {"action": "reduce", "target_exposure_pct": 50},
        "audit": {"skipped_sessions": [{"date": "x"}] * 50},
    }
    compact = _compact_raw("distribution_day", raw)
    idx = compact["market_distribution_state"]["index_results"][0]
    assert idx["d25_count"] == 6
    assert idx["risk_level"] == "HIGH"
    assert "active_distribution_days" not in idx
    assert "removed_distribution_days" not in idx
    assert "skipped_sessions" not in compact["audit"]


def test_compact_raw_market_breadth_is_passthrough():
    raw = {"composite": {"composite_score": 46, "zone": "Weakening"}}
    assert _compact_raw("market_breadth", raw) == raw


def test_compact_raw_handles_non_dict_input():
    """Defensive: don't raise if a future payload shape doesn't match."""
    assert _compact_raw("ftd", None) is None
    assert _compact_raw("ftd", "not a dict") == "not a dict"


# ---------------- _safe_truncate_json ----------------

def test_safe_truncate_passthrough_when_under_limit():
    payload = json.dumps({"composite_score": 95, "label": "FTD_CONFIRMED"})
    assert _safe_truncate_json(payload, 25_000) == payload


def test_safe_truncate_emits_parseable_envelope_when_over_limit():
    """The hard requirement: downstream json.loads must NEVER break.

    The pre-fix truncation cut at 5000 chars and appended '...[truncated]',
    producing strings like `{"big_field": "lorem ipsum...[truncated]` that
    blew up exposure_posture_run's json.loads call.
    """
    huge = json.dumps({"composite_score": 88, "long_string": "x" * 30_000})
    truncated = _safe_truncate_json(huge, 25_000, source="ftd", score=88, label="FTD_CONFIRMED")
    # Must be valid JSON.
    parsed = json.loads(truncated)
    assert parsed["_truncated"] is True
    assert parsed["_orig_size"] == len(huge)
    # Envelope extras (score/label/source) are surfaced so the brain still
    # has something to read.
    assert parsed["source"] == "ftd"
    assert parsed["score"] == 88
    assert parsed["label"] == "FTD_CONFIRMED"
    # Envelope itself fits under the limit.
    assert len(truncated) <= 25_000


def test_safe_truncate_preview_not_truncated_mid_string():
    """No '...[truncated]' suffix that breaks downstream parsers."""
    huge = "x" * 30_000
    truncated = _safe_truncate_json(huge, 25_000)
    # Must be parseable.
    json.loads(truncated)
    assert "[truncated]" not in truncated  # no half-string suffix


# ---------------- RegimeSignalRow.to_row roundtrip ----------------

def test_regime_signal_row_compact_payload_passes_through():
    """Compact payloads (the typical case after _compact_raw) round-trip
    through to_row and stay parseable."""
    raw_compact = json.dumps({"quality_score": {"total_score": 95},
                              "market_state": {"combined_state": "FTD_CONFIRMED"}})
    row = RegimeSignalRow(
        date="2026-06-10",
        source="ftd",
        score=95,
        label="FTD_CONFIRMED",
        summary="Strong FTD | 75-100%",
        raw_json=raw_compact,
    )
    cells = row.to_row(audit=False)
    # raw_json cell is at index 5 (last column).
    parsed = json.loads(cells[5])
    assert parsed["quality_score"]["total_score"] == 95


def test_regime_signal_row_oversized_payload_replaced_with_envelope():
    """If a future payload bloats past 25KB, the cell stays parseable."""
    bloated_raw = json.dumps({"junk": "x" * 30_000})
    row = RegimeSignalRow(
        date="2026-06-10",
        source="distribution_day",
        score=5,
        label="SEVERE",
        summary="risk=SEVERE",
        raw_json=bloated_raw,
    )
    cells = row.to_row(audit=False)
    parsed = json.loads(cells[5])
    assert parsed["_truncated"] is True
    assert parsed["source"] == "distribution_day"
    assert parsed["score"] == 5
    assert parsed["label"] == "SEVERE"
    assert len(cells[5]) <= MAX_JSON_CELL_BYTES


def test_exposure_posture_row_oversized_components_replaced_with_envelope():
    """Same safe-truncate guarantee for the components_json cell."""
    bloated = json.dumps({"x": "y" * 30_000})
    row = ExposurePostureRow(
        date="2026-06-10",
        exposure_ceiling_pct=4,
        bias="NEUTRAL",
        participation="NARROW",
        recommendation="CASH_PRIORITY",
        confidence="LOW",
        rationale="degraded",
        components_json=bloated,
    )
    cells = row.to_row(audit=False)
    parsed = json.loads(cells[7])
    assert parsed["_truncated"] is True
    assert parsed["recommendation"] == "CASH_PRIORITY"
    assert len(cells[7]) <= MAX_JSON_CELL_BYTES


# ---------------- end-to-end: bug scenario ----------------

def test_end_to_end_ftd_confirmed_propagates_to_row():
    """Full pipeline: real FTD payload → parser → compaction → row.

    Pre-fix: this row would have been written as score=0 / label=UNKNOWN /
    summary=UNKNOWN regardless of how strong the FTD was. The cell-level
    raw_json was the only evidence of the truth (combined_state=FTD_CONFIRMED,
    quality_score 95) — and downstream readers couldn't reach it because the
    score column drove the exposure-coach composite.
    """
    payload = _ftd_payload_confirmed_q95()
    sig = parse_ftd(payload)
    compact = _compact_raw(sig.source, payload)
    row = RegimeSignalRow(
        date="2026-06-10",
        source=sig.source,
        score=sig.score,
        label=sig.label,
        summary=sig.summary[:500],
        raw_json=json.dumps(compact, default=str),
    )
    cells = row.to_row(audit=False)
    # Column 2 is score (post-fix: 95.0, not 0.0).
    assert cells[2] == "95.0"
    # Column 3 is label (post-fix: FTD_CONFIRMED, not UNKNOWN).
    assert cells[3] == "FTD_CONFIRMED"
    # raw_json column round-trips and preserves what the brain needs.
    parsed = json.loads(cells[5])
    assert parsed["market_state"]["combined_state"] == "FTD_CONFIRMED"
    assert parsed["quality_score"]["total_score"] == 95


def test_end_to_end_pre_fix_extraction_would_have_been_zero():
    """Sanity check the audit narrative: the OLD parser (nested key path)
    would yield score=0 against this same payload. We verify the new parser
    avoids that trap."""
    payload = _ftd_payload_confirmed_q95()

    # Re-create the pre-fix extraction logic inline.
    old_quality = payload.get("market_state", {}).get("quality_score", {})
    old_score = float(old_quality.get("total_score", 0) or 0)
    assert old_score == 0.0  # documents the bug

    # New parser correctly extracts 95.
    new_sig = parse_ftd(payload)
    assert new_sig.score == 95.0
