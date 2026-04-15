"""
Parse daily news brief MD/txt files into rich sidecar JSONs and sync them to the Sheet.

Usage:
  python scripts/backfill_briefs.py           # re-parse and re-sync all briefs
  python scripts/backfill_briefs.py 20260414  # just one date

Parses sections:
  headline  — line 2 (the summary one-liner)
  overnight — OVERNIGHT section (bullet lines joined)
  premarket — PRE-MARKET section
  catalysts — TODAY'S CATALYSTS section
  posture   — POSTURE CHANGE? section
  watch     — WATCH section

Also keeps the existing keys: bullets (3 distilled), verdict (one-liner), sentiment.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

BRIEF_DIR = Path.home() / "Documents" / "Trading" / "Daily News Brief"
SECTIONS = [
    ("OVERNIGHT", "overnight"),
    ("PRE-MARKET", "premarket"),
    ("TODAY'S CATALYSTS", "catalysts"),
    ("YOUR POSITIONS", "_positions"),
    ("POSTURE CHANGE", "posture"),
    ("WATCH", "watch"),
]


def strip_leading_bullet(s: str) -> str:
    return re.sub(r"^\s*[-•]\s*", "", s).strip()


def parse_brief(text: str) -> dict:
    """Parse an MD/txt brief into a structured dict."""
    raw_md = text  # preserve full original for in-app detail view
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return {}

    # Date: look for YYYY-MM-DD in first line
    date_match = re.search(r"(\d{4}-\d{2}-\d{2})", lines[0] if lines else "")
    date = date_match.group(1) if date_match else ""

    # Headline: line 2 (the summary prose)
    headline = lines[1] if len(lines) > 1 else ""

    # Walk lines, collect sections
    out: dict[str, list[str]] = {name: [] for _, name in SECTIONS if not name.startswith("_")}
    out["_positions"] = []
    current = None
    for ln in lines[2:]:
        # Section header detection — case-insensitive, strips trailing "(...)" and "?"
        upper = ln.upper()
        matched = None
        for header, key in SECTIONS:
            if upper.startswith(header):
                matched = key
                break
        if matched:
            current = matched
            # For POSTURE CHANGE? YES/NO, capture the verdict on the same line
            if matched == "posture":
                m = re.search(r"POSTURE CHANGE\??\s*[:—-]?\s*(.+)$", ln, re.IGNORECASE)
                if m and m.group(1).strip():
                    out["posture"].append(m.group(1).strip())
            continue

        if current is None:
            continue

        # Accumulate bullet content
        if current == "_positions":
            continue  # we don't store positions here — positions come from IBKR grab
        content = strip_leading_bullet(ln)
        if content:
            out[current].append(content)

    # Derive "bullets" = best 3 key takeaways:
    # Priority: first premarket item, first catalyst, first watch item — or fall back
    bullets = []
    if headline:
        bullets.append(headline.split(".")[0].strip() + ".")  # first sentence of headline
    for key in ("premarket", "catalysts", "watch"):
        if out.get(key) and len(bullets) < 3:
            bullets.append(out[key][0])
    while len(bullets) < 3:
        bullets.append("")
    bullets = bullets[:3]

    # Verdict: from posture section (first sentence) or first WATCH item
    posture_text = " ".join(out.get("posture", [])) if out.get("posture") else ""
    verdict = ""
    if posture_text:
        # Strip "YES" / "NO" prefix
        pt = re.sub(r"^(YES|NO)[\.\s:—-]*", "", posture_text, flags=re.IGNORECASE).strip()
        verdict = pt.split(". ")[0].strip().rstrip(".") + "."
    if not verdict and headline:
        parts = [p.strip() for p in headline.split("—") if p.strip()]
        verdict = (parts[-1] if parts else headline) or ""

    # Sentiment — heuristic from headline keywords
    headline_lower = headline.lower()
    bearish_words = ["blockade", "sell", "exposed", "risk-off", "panic", "shock", "tighten", "hawkish"]
    bullish_words = ["ceasefire", "risk-on", "retreating", "easing", "recovery", "momentum", "green"]
    sentiment = "neutral"
    if any(w in headline_lower for w in bearish_words):
        sentiment = "bearish"
    elif any(w in headline_lower for w in bullish_words):
        sentiment = "bullish"

    return {
        "date": date,
        "headline": headline,
        "sentiment": sentiment,
        "verdict": verdict,
        "bullets": bullets,
        "overnight": out.get("overnight", []),
        "premarket": out.get("premarket", []),
        "catalysts": out.get("catalysts", []),
        "posture": posture_text,
        "watch": out.get("watch", []),
        "raw_md": raw_md,
    }


def find_source_files(target_date: str | None = None) -> list[Path]:
    """Find NewsBrief.md or .txt files in BRIEF_DIR. Optional date filter like '20260414'."""
    files: list[Path] = []
    for f in BRIEF_DIR.iterdir():
        name = f.name
        if not re.match(r"\d{8}_NewsBrief\.(md|txt)", name):
            continue
        if target_date and not name.startswith(target_date):
            continue
        files.append(f)
    return sorted(files)


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else None
    files = find_source_files(target)
    if not files:
        print(f"No brief files found in {BRIEF_DIR}" + (f" matching {target}" if target else ""))
        return

    for f in files:
        print(f"\n=== Parsing {f.name} ===")
        parsed = parse_brief(f.read_text())
        if not parsed.get("date"):
            print(f"  skipped — no date found")
            continue

        # Write sidecar JSON next to the source file
        date_compact = parsed["date"].replace("-", "")
        sidecar = f.parent / f"{date_compact}_brief.json"
        sidecar.write_text(json.dumps(parsed, indent=2))
        print(f"  wrote sidecar: {sidecar}")
        print(f"  headline: {parsed['headline'][:80]}")
        print(f"  sentiment: {parsed['sentiment']}")
        print(f"  overnight: {len(parsed['overnight'])} items")
        print(f"  premarket: {len(parsed['premarket'])} items")
        print(f"  catalysts: {len(parsed['catalysts'])} items")
        print(f"  watch: {len(parsed['watch'])} items")


if __name__ == "__main__":
    main()
