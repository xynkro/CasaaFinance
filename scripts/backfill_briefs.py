"""
Parse daily news brief MD/txt files into rich sidecar JSONs and push them
straight to the Sheet so the PWA can render them.

By default this script is *incremental*:
  - walks ~/Documents/Trading/Daily News Brief/
  - processes any MD/txt file that has no sidecar, OR whose sidecar is older
    than the source file
  - writes the sidecar JSON next to the source
  - then pushes the parsed brief to the `daily_brief_latest` sheet tab so it
    shows up in the PWA immediately — you never need to touch the sidecar JSON
    yourself

Usage:
  python scripts/backfill_briefs.py                # pick up anything new/stale
  python scripts/backfill_briefs.py --all          # re-parse & re-sync every brief
  python scripts/backfill_briefs.py 20260414       # just one date
  python scripts/backfill_briefs.py --no-sync      # parse only, skip the sheet push

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

import argparse
import json
import logging
import re
import sys
from pathlib import Path

# Make imports work whether run as `python scripts/backfill_briefs.py` or as a module.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BRIEF_DIR = Path.home() / "Documents" / "Trading" / "Daily News Brief"
SECTIONS = [
    ("OVERNIGHT", "overnight"),
    ("PRE-MARKET", "premarket"),
    ("TODAY'S CATALYSTS", "catalysts"),
    ("COMMODITIES", "commodities"),
    # Position sections (any wording) are handled by IBKR grab — skip content here
    ("YOUR POSITIONS", "_positions"),
    ("CASPAR'S POSITIONS", "_positions"),
    ("SARAH'S POSITIONS", "_positions"),
    ("SENTIMENT", "_skip"),  # Sentiment subsection we don't surface yet
    ("POSTURE CHANGE", "posture"),
    ("WATCH", "watch"),
]


def strip_leading_bullet(s: str) -> str:
    return re.sub(r"^\s*[-•]\s*", "", s).strip()


def _is_divider(ln: str) -> bool:
    """Detect visual divider lines like `── TIER 1: PHONE GLANCE ──` or `──────`."""
    s = ln.strip()
    if not s:
        return True
    # Lines composed mostly of box-drawing / dash characters (optionally with
    # a `TIER N: …` label in the middle) are decorative and should be skipped.
    if re.match(r"^[─━\-=]{3,}", s):
        return True
    if re.match(r"^─+\s*TIER\b", s, re.IGNORECASE):
        return True
    return False


def parse_brief(text: str) -> dict:
    """Parse an MD/txt brief into a structured dict.

    Supports two formats:
      1. Legacy — line 1 title, line 2 headline prose, then OVERNIGHT/…/WATCH sections
      2. Tiered — line 1 title, then `── TIER 1: PHONE GLANCE ──` divider with
         bracketed tags `[VERDICT]:`, `[NUMBERS]:`, `[ACTION]:`, then
         `── TIER 2: ANALYSIS ──` and the usual sections.
    """
    raw_md = text  # preserve full original for in-app detail view
    # Keep every non-blank line, but drop decorative dividers so section-walking
    # doesn't get distracted.
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip() and not _is_divider(ln)]
    if not lines:
        return {}

    # Date: look for YYYY-MM-DD in first line
    date_match = re.search(r"(\d{4}-\d{2}-\d{2})", lines[0] if lines else "")
    date = date_match.group(1) if date_match else ""

    # ---- Tiered [TAG]: extraction ----
    tag_values: dict[str, str] = {}

    def _tag(name: str) -> str:
        return tag_values.get(name, "")

    body_start_idx = 1  # default: treat line 2 as headline (legacy)
    body_lines = lines[1:]

    # Scan lines 1..onwards for bracket tags; collect until an OVERNIGHT section
    # or similar is hit.
    content_section_headers = {h for h, _ in SECTIONS}
    content_section_headers.add("COMMODITIES")

    tag_re = re.compile(r"^\[(VERDICT|NUMBERS|ACTION)\]\s*:\s*(.+)$", re.IGNORECASE)
    for i, ln in enumerate(lines[1:], start=1):
        upper = ln.upper()
        if any(upper.startswith(h) for h in content_section_headers):
            body_start_idx = i
            break
        m = tag_re.match(ln)
        if m:
            key = m.group(1).upper()
            tag_values.setdefault(key, m.group(2).strip())
    else:
        body_start_idx = len(lines)

    body_lines = lines[body_start_idx:]

    # Headline:
    #   - If tiered format provided a [VERDICT] tag, use it.
    #   - Else use the first non-tag line between the title and the first section.
    headline = _tag("VERDICT")
    if not headline:
        # Walk lines[1..body_start_idx] for first non-tag, non-empty line
        for ln in lines[1:body_start_idx]:
            if not tag_re.match(ln):
                headline = ln
                break

    # Walk sections
    out: dict[str, list[str]] = {name: [] for _, name in SECTIONS if not name.startswith("_")}
    out["_positions"] = []
    out["_skip"] = []
    current = None
    for ln in body_lines:
        upper = ln.upper()
        matched = None
        for header, key in SECTIONS:
            if upper.startswith(header):
                matched = key
                break
        if matched:
            current = matched
            if matched == "posture":
                m = re.search(r"POSTURE CHANGE\??\s*[:—-]?\s*(.+)$", ln, re.IGNORECASE)
                if m and m.group(1).strip():
                    out["posture"].append(m.group(1).strip())
            continue

        if current is None:
            continue
        if current in ("_positions", "_skip"):
            continue
        content = strip_leading_bullet(ln)
        if content:
            out[current].append(content)

    # Posture text — folded with [ACTION] if both exist
    posture_text = " ".join(out.get("posture", [])) if out.get("posture") else ""
    action_text = _tag("ACTION")
    numbers_text = _tag("NUMBERS")

    # Verdict — ordered fallback chain: ACTION tag → posture → headline fragment
    verdict = ""
    if action_text:
        verdict = action_text.split(". ")[0].strip().rstrip(".") + "."
    elif posture_text:
        pt = re.sub(r"^(YES|NO)[\.\s:—-]*", "", posture_text, flags=re.IGNORECASE).strip()
        verdict = pt.split(". ")[0].strip().rstrip(".") + "."
    if not verdict and headline:
        parts = [p.strip() for p in headline.split("—") if p.strip()]
        verdict = (parts[-1] if parts else headline) or ""

    # Bullets — best 3 key takeaways
    bullets: list[str] = []
    if headline:
        first = headline.split(".")[0].strip()
        if first:
            bullets.append(first + ".")
    if action_text and action_text not in bullets:
        bullets.append(action_text)
    for key in ("premarket", "catalysts", "watch"):
        if out.get(key) and len(bullets) < 3:
            bullets.append(out[key][0])
    while len(bullets) < 3:
        bullets.append("")
    bullets = bullets[:3]

    # If the legacy "overnight" is empty but we have [NUMBERS], use that as a
    # summary line so the Overnight section on the PWA isn't blank.
    overnight = out.get("overnight", [])
    if not overnight and numbers_text:
        overnight = [numbers_text]

    # Sentiment — scan headline + verdict + action for tone words
    tone_text = " ".join([headline, verdict, action_text, posture_text]).lower()
    bearish_words = ["blockade", "sell", "exposed", "risk-off", "panic", "shock",
                     "tighten", "hawkish", "selloff", "collapse", "stagflation"]
    bullish_words = ["ceasefire", "risk-on", "retreating", "easing", "recovery",
                     "momentum", "green", "rally", "beat", "optimism", "ath"]
    sentiment = "neutral"
    if any(w in tone_text for w in bearish_words):
        sentiment = "bearish"
    if any(w in tone_text for w in bullish_words):
        # Give bullish signals priority when both appear (recovery-from-risk-off)
        sentiment = "bullish"

    return {
        "date": date,
        "headline": headline,
        "sentiment": sentiment,
        "verdict": verdict,
        "bullets": bullets,
        "overnight": overnight,
        "premarket": out.get("premarket", []),
        "catalysts": out.get("catalysts", []),
        "commodities": out.get("commodities", []),
        "posture": posture_text or action_text,
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


def needs_processing(md_path: Path) -> bool:
    """True if there's no sidecar yet, or MD has been edited since the sidecar was written."""
    date_compact = md_path.name[:8]  # 'YYYYMMDD'
    sidecar = md_path.parent / f"{date_compact}_brief.json"
    if not sidecar.exists():
        return True
    return md_path.stat().st_mtime > sidecar.stat().st_mtime


def sync_to_sheet(sidecar_path: Path) -> bool:
    """Push a parsed sidecar to the daily_brief_latest tab."""
    # Lazy import — avoids requiring gspread for --no-sync parse-only runs.
    from src import sync as sync_mod
    from src import schema as S
    from src import sheets as sh

    sync_mod.load_env()
    logger = sync_mod.setup_logging()
    logging.getLogger("sync").setLevel(logging.WARNING)

    sidecar = json.loads(sidecar_path.read_text())
    date = str(sidecar.get("date", ""))
    if not date:
        print(f"    sheet push skipped — sidecar missing date")
        return False

    try:
        daily_row = S.daily_from_sidecar(sidecar)
        client = sh.authenticate()
        sh.ensure_headers(client, S.DailyBriefRow.TAB_NAME, S.DailyBriefRow.HEADERS)
        sh.append_row(client, S.DailyBriefRow.TAB_NAME, daily_row.to_row())
        logger.info(f"backfill: pushed {date} to {S.DailyBriefRow.TAB_NAME}")
        return True
    except Exception as e:
        print(f"    sheet push failed: {e}")
        return False


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("date", nargs="?", help="Optional YYYYMMDD to process just one day")
    ap.add_argument("--all", action="store_true", help="Re-parse & re-sync every brief (default is incremental)")
    ap.add_argument("--no-sync", action="store_true", help="Write sidecars only, don't push to the sheet")
    args = ap.parse_args()

    files = find_source_files(args.date)
    if not files:
        print(f"No brief files found in {BRIEF_DIR}" + (f" matching {args.date}" if args.date else ""))
        return

    # Incremental filter — skip anything with an up-to-date sidecar
    if not args.all and not args.date:
        before = len(files)
        files = [f for f in files if needs_processing(f)]
        skipped = before - len(files)
        if skipped:
            print(f"Skipping {skipped} brief(s) with up-to-date sidecars (use --all to force)")

    if not files:
        print("Nothing to do — all briefs already parsed.")
        return

    parsed_sidecars: list[Path] = []
    for f in files:
        print(f"\n=== Parsing {f.name} ===")
        parsed = parse_brief(f.read_text())
        if not parsed.get("date"):
            print(f"  skipped — no date found")
            continue

        date_compact = parsed["date"].replace("-", "")
        sidecar = f.parent / f"{date_compact}_brief.json"
        sidecar.write_text(json.dumps(parsed, indent=2))
        print(f"  wrote sidecar: {sidecar.name}")
        print(f"  headline: {parsed['headline'][:80]}")
        print(f"  sentiment: {parsed['sentiment']}")
        print(f"  overnight: {len(parsed['overnight'])} items")
        print(f"  premarket: {len(parsed['premarket'])} items")
        print(f"  catalysts: {len(parsed['catalysts'])} items")
        print(f"  watch: {len(parsed['watch'])} items")
        parsed_sidecars.append(sidecar)

    if args.no_sync:
        print(f"\n--no-sync — parse only. Drop the flag to push these to the sheet.")
        return

    if not parsed_sidecars:
        return

    print(f"\n=== Pushing {len(parsed_sidecars)} brief(s) to the sheet ===")
    ok = 0
    for sidecar in parsed_sidecars:
        print(f"  • {sidecar.name}")
        if sync_to_sheet(sidecar):
            ok += 1
    print(f"\nDone — {ok}/{len(parsed_sidecars)} synced to sheet.")


if __name__ == "__main__":
    main()
