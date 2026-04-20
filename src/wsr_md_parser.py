"""
wsr_md_parser.py — Parse WSR markdown into a structured summary row.

Extracts from the new WSR markdown format:
  - Verdict (the one-liner summary)
  - Confidence (0.0 - 1.0)
  - Regime (e.g. bull_late_cycle)
  - Key actions (trim triggers, watch list, etc.)
  - Options commentary
  - Week lookback events

Output: a single WsrSummaryRow for the sheet, plus any DecisionRows extracted.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


VERDICT_RE = re.compile(r"##\s+Verdict\s*\n+(.+?)(?=\n##|\Z)", re.DOTALL | re.IGNORECASE)
CONFIDENCE_RE = re.compile(r"\*\*Confidence:\*\*\s+([\d.]+)", re.IGNORECASE)
REGIME_RE = re.compile(r"\*\*Regime:\*\*\s+(\w+)", re.IGNORECASE)
DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})|(\d{8})")


def _extract_first_heading_text(md: str, heading_pattern: str) -> str:
    """Extract text under a markdown heading until the next heading."""
    pat = re.compile(
        rf"^##\s+{heading_pattern}\s*\n+(.+?)(?=\n##|\Z)",
        re.MULTILINE | re.IGNORECASE | re.DOTALL,
    )
    m = pat.search(md)
    if not m:
        return ""
    return m.group(1).strip()


def _first_sentence(text: str, max_len: int = 280) -> str:
    """Grab the first sentence or N chars, cleaned of markdown noise."""
    # Strip blockquotes/warnings
    lines = [l for l in text.splitlines() if not l.startswith(">")]
    text = " ".join(l.strip() for l in lines if l.strip())
    # Strip bold/italic markers
    text = re.sub(r"\*{1,3}", "", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # First sentence
    m = re.match(r"^([^.!?]+[.!?])", text)
    if m:
        s = m.group(1).strip()
        if len(s) > max_len:
            return s[:max_len - 3] + "..."
        return s
    return text[:max_len]


def parse_wsr_md(md_path: Path, date: str) -> dict[str, Any]:
    """
    Parse a WSR markdown file into a dict ready for WsrSummaryRow construction.
    """
    text = md_path.read_text()

    # Regime from anywhere in doc
    regime = ""
    m = REGIME_RE.search(text)
    if m:
        regime = m.group(1)

    # Confidence
    confidence = 0.0
    m = CONFIDENCE_RE.search(text)
    if m:
        try:
            confidence = float(m.group(1))
        except ValueError:
            pass

    # Verdict — full paragraph
    verdict_raw = _extract_first_heading_text(text, "Verdict")
    verdict_summary = _first_sentence(verdict_raw, max_len=280)
    # Strip blockquote degraded-run warnings
    verdict_summary = re.sub(r"^\s*⚠.*?\.\s*", "", verdict_summary)

    # Macro regime read — first paragraph
    macro_read = _first_sentence(
        _extract_first_heading_text(text, r"Macro Regime Read"),
        max_len=300,
    )

    # Action plan — pull bullet list or section text
    action_section = _extract_first_heading_text(text, r"(?:Action Plan|This Week|Plan|Primary Actions?|Decisions?)")
    if not action_section:
        # Try the "Primary action this week:" phrase from verdict
        primary_m = re.search(r"[Pp]rimary action.*?(?=\.|\n)", text)
        action_section = primary_m.group(0) if primary_m else ""
    action_summary = _first_sentence(action_section, max_len=300)

    # Options commentary — look for "Options" section or "Options book"
    options_section = _extract_first_heading_text(text, r"Options(?:\s+Book)?")
    if not options_section:
        opts_m = re.search(r"[Oo]ptions book:?\s*(.+?)(?=\.|\n\n)", text)
        options_section = opts_m.group(1) if opts_m else ""
    options_summary = _first_sentence(options_section, max_len=300)

    # Key events from "Week Lookback" table
    events = []
    week_lookback = _extract_first_heading_text(text, r"Week Lookback")
    if week_lookback:
        # Parse markdown table rows
        for line in week_lookback.splitlines():
            # | Mon 14 | Goldman beats... | Sarah: no direct... |
            m = re.match(r"\|\s*([^|]+?)\s*\|\s*(.+?)\s*\|", line)
            if m and "Day" not in m.group(1) and "---" not in m.group(1):
                day = m.group(1).strip()
                event = m.group(2).strip()
                if day and event:
                    events.append(f"{day}: {event}")
        events = events[:5]

    # Strip markdown symbols from all fields
    def _clean(s: str) -> str:
        s = re.sub(r"\*{1,3}", "", s)
        s = re.sub(r"`([^`]+)`", r"\1", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    return {
        "date": date,
        "source": md_path.name,
        "verdict": _clean(verdict_summary),
        "confidence": confidence,
        "regime": regime,
        "macro_read": _clean(macro_read),
        "action_summary": _clean(action_summary),
        "options_summary": _clean(options_summary),
        "week_events": " | ".join(_clean(e) for e in events),
        "raw_md": text[:15000],  # keep full-ish markdown for in-app view
    }


def is_wsr_file(path: Path) -> bool:
    """Heuristic: filename contains 'WSR' and ends in .md, excludes ad-hoc options."""
    name = path.name.lower()
    if not name.endswith(".md"):
        return False
    if "options" in name or "adhoc" in name.replace("wsr", ""):
        return False
    return "wsr" in name


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) < 2:
        print("Usage: wsr_md_parser.py <path> [date]")
        sys.exit(1)
    p = Path(sys.argv[1])
    date = sys.argv[2] if len(sys.argv) > 2 else "2026-01-01"
    print(json.dumps(parse_wsr_md(p, date), indent=2))
