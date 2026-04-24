"""
wsr_lite_md_parser.py — Parse WSR Lite markdown into a WsrSummaryRow.

WSR Lite runs Wed + Fri. It has 6 strict sections:
  1. Trigger Audit
  2. Options Book Traffic Lights
  3. Regime Drift
  4. Decision Queue Status
  5. Catalyst Calendar — Next 3 Trading Days
  6. Bottom Line

We store source="wsr_lite" so the frontend can distinguish from Monday WSR.
The full raw_md is stored verbatim; client-side parse extracts the 6 sections.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


_BOTTOM_LINE_RE = re.compile(
    r"##\s+Bottom\s+Line\s*\n+(.+?)(?=\n##|\Z)", re.DOTALL | re.IGNORECASE
)
_CONFIDENCE_RE = re.compile(r"[Cc]onfidence[:\s]+([\d.]+)")
_REGIME_UNCHANGED_RE = re.compile(r"REGIME\s+UNCHANGED", re.IGNORECASE)
_REGIME_LABEL_RE = re.compile(r"`(\w+_\w+[_\w]*)`")
_DATE_IN_HEADING_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def is_wsr_lite_file(path: Path) -> bool:
    """True for files like 20260424_WSR_lite.md"""
    name = path.name.lower()
    return name.endswith(".md") and "wsr" in name and "lite" in name


def parse_wsr_lite_md(path: Path, date: str) -> dict[str, Any]:
    """
    Parse WSR Lite markdown into a dict matching WsrSummaryRow fields.
    source is always "wsr_lite".
    """
    md = path.read_text(encoding="utf-8")

    # Bottom Line → verdict
    bl_match = _BOTTOM_LINE_RE.search(md)
    bottom_line_text = bl_match.group(1).strip() if bl_match else ""
    # Strip markdown bold/italic
    verdict = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", bottom_line_text).strip()
    # First sentence
    m = re.match(r"^(.+?[.!?])", verdict)
    verdict = m.group(1).strip() if m else verdict[:280]

    # Confidence
    conf_m = _CONFIDENCE_RE.search(bottom_line_text)
    confidence = conf_m.group(1) if conf_m else "0.70"

    # Regime
    regime_unchanged = bool(_REGIME_UNCHANGED_RE.search(md))
    label_m = _REGIME_LABEL_RE.search(md)
    regime = label_m.group(1) if label_m else ("neutral" if not regime_unchanged else "bull_late_cycle")

    # Date from heading if not provided
    if not date:
        date_m = _DATE_IN_HEADING_RE.search(md)
        date = date_m.group(1) if date_m else ""

    return {
        "date": date,
        "source": "wsr_lite",
        "verdict": verdict,
        "confidence": confidence,
        "regime": regime,
        "macro_read": "REGIME UNCHANGED" if regime_unchanged else "REGIME DRIFT",
        "action_summary": "",   # extracted client-side from raw_md
        "options_summary": "",  # extracted client-side from raw_md
        "redteam_summary": "",
        "week_events": "",
        "raw_md": md,
    }
