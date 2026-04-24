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


def _full_paragraph(text: str, max_len: int = 1200, max_paragraphs: int = 3) -> str:
    """
    Grab multiple paragraphs cleaned of markdown noise. Preserves sentence
    structure so the user gets the full strategic context, not just a
    one-liner.
    """
    if not text:
        return ""
    # Strip blockquotes/warnings lines but keep normal content
    lines = [l for l in text.splitlines() if not l.strip().startswith(">")]

    # Group into paragraphs (split on blank lines or table rows starting with |)
    paragraphs: list[str] = []
    buf: list[str] = []
    for line in lines:
        stripped = line.strip()
        is_table = stripped.startswith("|") or stripped.startswith("---")
        is_bullet_heading = stripped.startswith("#") or stripped.startswith("**Confidence:")
        if not stripped or is_table or is_bullet_heading:
            if buf:
                paragraphs.append(" ".join(buf))
                buf = []
        else:
            buf.append(stripped)
    if buf:
        paragraphs.append(" ".join(buf))

    # Strip markdown inline formatting
    cleaned: list[str] = []
    for p in paragraphs[:max_paragraphs]:
        p = re.sub(r"\*{1,3}", "", p)
        p = re.sub(r"`([^`]+)`", r"\1", p)
        # Collapse the trailing (Judgement, 0.75) / (Synthesis) citations for brevity
        p = re.sub(r"\s*\((?:Judgement|Synthesis)(?:,\s*[\d.]+)?\)", "", p)
        p = re.sub(r"\s+", " ", p).strip()
        if p:
            cleaned.append(p)

    out = "\n\n".join(cleaned)
    if len(out) > max_len:
        out = out[:max_len - 3] + "..."
    return out


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

    # Verdict — full paragraph (this is the synthesis)
    verdict_raw = _extract_first_heading_text(text, "Verdict")
    verdict_summary = _full_paragraph(verdict_raw, max_len=1200, max_paragraphs=2)
    # Strip any leading ⚠ degraded-run warning at the start
    verdict_summary = re.sub(r"^\s*⚠.*?\n\n", "", verdict_summary)

    # Macro regime read — up to 2 paragraphs of regime/macro commentary
    macro_read = _full_paragraph(
        _extract_first_heading_text(text, r"Macro Regime Read"),
        max_len=900, max_paragraphs=2,
    )

    # Action plan — pull bullet list or section text
    action_section = _extract_first_heading_text(
        text,
        r"(?:Action Plan|This Week['\u2019]?s Plan|Primary Actions?|Decisions? Queue|Plan this Week)",
    )
    if not action_section:
        # Try the "Primary action this week:" phrase from verdict
        primary_m = re.search(r"[Pp]rimary action.*?(?=\.\s|\n)", text)
        action_section = primary_m.group(0) if primary_m else ""
    action_summary = _full_paragraph(action_section, max_len=900, max_paragraphs=3)

    # Options commentary — look for "Options" section or "Options book"
    options_section = _extract_first_heading_text(text, r"Options(?:\s+(?:Book|Positions?))?")
    if not options_section:
        opts_m = re.search(r"[Oo]ptions book:?\s*(.+?)(?=\n\n|\n##)", text, re.DOTALL)
        options_section = opts_m.group(1) if opts_m else ""
    options_summary = _full_paragraph(options_section, max_len=800, max_paragraphs=2)

    # Red-team / risk flags
    redteam_section = _extract_first_heading_text(text, r"Red[-\s]?Team(?:\s+Flags?)?")
    redteam_summary = _full_paragraph(redteam_section, max_len=900, max_paragraphs=2)

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

    # Strip residual markdown symbols from single-line fields (preserve paragraph breaks in longer fields)
    def _clean_inline(s: str) -> str:
        s = re.sub(r"\*{1,3}", "", s)
        s = re.sub(r"`([^`]+)`", r"\1", s)
        s = re.sub(r"[ \t]+", " ", s)
        return s.strip()

    return {
        "date": date,
        "source": md_path.name,
        "verdict": _clean_inline(verdict_summary),
        "confidence": confidence,
        "regime": regime,
        "macro_read": _clean_inline(macro_read),
        "action_summary": _clean_inline(action_summary),
        "options_summary": _clean_inline(options_summary),
        "redteam_summary": _clean_inline(redteam_summary),
        "week_events": " | ".join(_clean_inline(e) for e in events),
        "raw_md": text[:20000],
    }


def is_wsr_file(path: Path) -> bool:
    """Heuristic: filename contains 'WSR' and ends in .md, excludes ad-hoc options and WSR Lite."""
    name = path.name.lower()
    if not name.endswith(".md"):
        return False
    if "options" in name or "adhoc" in name.replace("wsr", ""):
        return False
    if "lite" in name:  # WSR Lite has its own parser; don't clobber Monday WSR
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
