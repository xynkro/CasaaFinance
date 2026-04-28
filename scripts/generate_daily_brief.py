"""
generate_daily_brief.py — Cloud-native daily brief generator.

End-to-end pipeline:
  1. Gather state from Sheets (positions, snapshots, macro, options book)
  2. Opus 4.7 synthesises (with web_search tool for overnight news)
  3. Sonnet 4.6 formats the JSON into markdown
  4. push_brief.py writes to daily_brief_latest sheet + Drive/Daily Briefs/

Runs in GitHub Actions on weekdays at 07:00 SGT. Mac-independent.

Required env vars:
  ANTHROPIC_API_KEY       — for the brain
  OAUTH_TOKEN_JSON        — Google Sheets/Drive OAuth (or GOOGLE_SERVICE_ACCOUNT_JSON)
  SHEET_ID, DRIVE_FOLDER_ID — sheet + drive root

Usage:
  python scripts/generate_daily_brief.py           # full live run
  python scripts/generate_daily_brief.py --dry     # synthesize but don't write
  python scripts/generate_daily_brief.py --skip-web # don't call web_search (cheaper test)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _setup_logging() -> logging.Logger:
    logger = logging.getLogger("daily-brief")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(h)
    # Also keep a state log file when filesystem is writable
    try:
        log_path = ROOT / ".state" / "daily-brief-cron.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_path)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(fh)
    except OSError:
        pass
    return logger


def gather_sheet_state(logger: logging.Logger) -> dict:
    """Read the slow-moving state — positions, snapshots, macro, options book —
    from Sheets so the brain has full context."""
    from src.sync import load_env
    from src import sheets as sh
    load_env()
    client = sh.authenticate()
    ss = sh._open_sheet(client)

    state: dict[str, Any] = {}

    # Macro
    try:
        rows = ss.worksheet("macro").get_all_values()
        if len(rows) > 1:
            state["macro_latest"] = dict(zip(rows[0], rows[-1]))
            state["macro_yesterday"] = dict(zip(rows[0], rows[-2])) if len(rows) > 2 else None
    except Exception as e:
        logger.warning(f"macro fetch failed: {e}")
        state["macro_latest"] = None

    # Snapshots (last row each)
    for tab in ("snapshot_caspar", "snapshot_sarah"):
        try:
            rows = ss.worksheet(tab).get_all_values()
            if len(rows) > 1:
                state[tab] = dict(zip(rows[0], rows[-1]))
        except Exception as e:
            logger.warning(f"{tab} fetch failed: {e}")

    # Latest positions (latest-date group)
    for tab in ("positions_caspar", "positions_sarah"):
        try:
            rows = ss.worksheet(tab).get_all_values()
            if len(rows) < 2:
                state[tab] = []
                continue
            headers = rows[0]
            data = [dict(zip(headers, r)) for r in rows[1:] if any(r)]
            latest_date = max(r.get("date", "") for r in data)
            state[tab] = [r for r in data if r.get("date") == latest_date]
        except Exception as e:
            logger.warning(f"{tab} fetch failed: {e}")
            state[tab] = []

    # Open options
    try:
        rows = ss.worksheet("options").get_all_values()
        if len(rows) > 1:
            headers = rows[0]
            data = [dict(zip(headers, r)) for r in rows[1:] if any(r)]
            latest_date = max(r.get("date", "") for r in data)
            state["options_book"] = [r for r in data if r.get("date") == latest_date]
        else:
            state["options_book"] = []
    except Exception as e:
        logger.warning(f"options fetch failed: {e}")
        state["options_book"] = []

    # Decision queue (latest)
    try:
        rows = ss.worksheet("decision_queue").get_all_values()
        if len(rows) > 1:
            headers = rows[0]
            data = [dict(zip(headers, r)) for r in rows[1:] if any(r)]
            latest_date = max(r.get("date", "") for r in data)
            state["decision_queue"] = [r for r in data if r.get("date") == latest_date]
        else:
            state["decision_queue"] = []
    except Exception as e:
        logger.warning(f"decision_queue fetch failed: {e}")
        state["decision_queue"] = []

    # Latest market_scan recommendations (top 10)
    try:
        rows = ss.worksheet("option_recommendations").get_all_values()
        if len(rows) > 1:
            headers = rows[0]
            data = [dict(zip(headers, r)) for r in rows[1:] if any(r)]
            recs = sorted(data, key=lambda r: r.get("date", ""), reverse=True)[:10]
            state["recent_recommendations"] = recs
    except Exception as e:
        logger.warning(f"recommendations fetch failed: {e}")
        state["recent_recommendations"] = []

    return state


def build_synthesis_prompt(state: dict, today_iso: str) -> tuple[str, str]:
    """Return (system, user) prompts for Opus synthesis."""
    from src.trading_rules import all_rules_summary

    system = """You are a swing-trader's research brain. You produce daily briefs
for Caspar (smaller, more aggressive) and Sarah (larger, quality + income).

Singapore tax context: no capital gains tax — so cutting losers fast matters
less than for US traders, but trim discipline on winners still matters.

You will be given:
- Sheet state (positions, snapshots, macro, options book, decision queue)
- Trading rules (sizing limits, stop levels, options thresholds)
- Web research access (use it for overnight US close + Asia open)

You will return a JSON object matching the daily-brief schema. Be CONCISE
in synthesis. Do not write prose paragraphs — Sonnet will expand later.

Output the JSON inside a ```json fenced block. Nothing outside the fence."""

    rules = all_rules_summary()
    state_compact = json.dumps(state, indent=2, default=str)
    rules_compact = json.dumps(rules, indent=2)

    user = f"""Today is {today_iso}. Generate today's daily brief.

## Trading rules to apply

```json
{rules_compact}
```

## Current sheet state

```json
{state_compact}
```

## Your task

1. Use web_search to gather:
   - US market close yesterday (SPX, NDX, RUT — direction, key levels, internals)
   - After-hours earnings of major names
   - Asia session today (if applicable)
   - Macro events in last 24h (Fed speakers, CPI/jobs/PMI)
   - Geopolitics moving markets
   - Commodities >2% moves

2. Cross-reference vs trading rules:
   - Any position over its sizing cap?
   - Any trim trigger (TQQQ $52, SSO $60, etc.) breached?
   - Regime still `bull_late_cycle`? Any drift?

3. Output JSON in this exact schema:

```json
{{
  "type": "daily",
  "date": "{today_iso}",
  "headline": "one-line summary capturing today's dominant theme",
  "sentiment": "bullish|bearish|neutral",
  "regime": "bull_late_cycle|...",
  "verdict": "trader-facing one-liner: what to do today",
  "overnight_bullets":   ["...", "..."],
  "premarket_bullets":   ["..."],
  "catalysts_bullets":   ["..."],
  "commodities_bullets": ["..."],
  "posture_change":      "string or empty",
  "watch_bullets":       ["TQQQ $52+ = trim trigger live", "..."],
  "key_takeaways":       ["bullet 1", "bullet 2", "bullet 3"]
}}
```

CONSTRAINTS:
- All bullets must be short (under 25 words each).
- key_takeaways must be exactly 3 items, ranked by importance.
- watch_bullets are RULE-BASED triggers (price levels, RSI), not vibes.
- Be opinionated — pick a side when evidence supports it. No "could be either way".
"""
    return system, user


def call_opus_with_web_search(system: str, user: str, logger: logging.Logger,
                              skip_web: bool = False) -> dict:
    """Call Opus with web_search tool enabled. Returns parsed JSON synthesis."""
    from src.llm_brain import _client, MODEL_OPUS
    client = _client()

    tools = [] if skip_web else [{
        "type": "web_search_20250305",
        "name": "web_search",
        "max_uses": 8,
    }]

    logger.info(f"Calling {MODEL_OPUS} (web_search={'on' if not skip_web else 'off'})")
    resp = client.messages.create(
        model=MODEL_OPUS,
        max_tokens=4096,
        temperature=0.5,
        system=system,
        messages=[{"role": "user", "content": user}],
        tools=tools,
    )

    # Sum text across all content blocks (web_search produces tool_use + text mix)
    text_parts = [b.text for b in resp.content if hasattr(b, "text")]
    text = "\n".join(text_parts)

    logger.info(
        f"Opus usage: in={resp.usage.input_tokens} out={resp.usage.output_tokens} "
        f"stop_reason={resp.stop_reason}"
    )

    from src.llm_brain import _extract_json
    json_text = _extract_json(text)
    if not json_text:
        raise ValueError(f"Opus did not return JSON. Response:\n{text[:1000]}")
    return json.loads(json_text)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry", action="store_true", help="Synthesize but don't write to Sheets/Drive")
    ap.add_argument("--skip-web", action="store_true", help="Skip web_search (for cheap testing)")
    ap.add_argument("--date", default=None, help="Override date (YYYY-MM-DD); default = today UTC")
    args = ap.parse_args()

    logger = _setup_logging()
    logger.info("=== generate_daily_brief start ===")

    today_iso = args.date or date.today().isoformat()

    # Step 1: gather state
    logger.info("Gathering sheet state...")
    state = gather_sheet_state(logger)
    logger.info(f"State gathered: macro={state.get('macro_latest') is not None}, "
                f"caspar_positions={len(state.get('positions_caspar', []))}, "
                f"sarah_positions={len(state.get('positions_sarah', []))}, "
                f"options={len(state.get('options_book', []))}")

    # Step 2: Opus synthesis
    system, user = build_synthesis_prompt(state, today_iso)
    synthesis = call_opus_with_web_search(system, user, logger, skip_web=args.skip_web)
    logger.info(f"Opus synthesis ok: headline={synthesis.get('headline', '?')!r}")

    # Step 3: Sonnet format
    from src.llm_brain import format_markdown
    markdown = format_markdown(
        template_path="prompts/sonnet_format_daily.md",
        synthesis_json=synthesis,
    )
    logger.info(f"Sonnet format ok: {len(markdown)} chars markdown")

    # Step 4: build payload + push
    payload = {
        "type": "daily",
        "date": today_iso,
        "headline":   synthesis.get("headline", ""),
        "sentiment":  synthesis.get("sentiment", "neutral"),
        "verdict":    synthesis.get("verdict", ""),
        "bullets":    synthesis.get("key_takeaways", [])[:3],
        "overnight":  " | ".join(synthesis.get("overnight_bullets", [])),
        "premarket":  " | ".join(synthesis.get("premarket_bullets", [])),
        "catalysts":  " | ".join(synthesis.get("catalysts_bullets", [])),
        "commodities":" | ".join(synthesis.get("commodities_bullets", [])),
        "posture":    synthesis.get("posture_change", ""),
        "watch":      " | ".join(synthesis.get("watch_bullets", [])),
        "raw_md":     markdown,
    }

    if args.dry:
        logger.info("[DRY] Would push payload:")
        print(json.dumps(payload, indent=2)[:2000])
        return 0

    from scripts.push_brief import push_brief
    result = push_brief(payload, no_drive=False)
    logger.info(f"push_brief result: {result}")

    if not result.get("ok"):
        logger.error(f"push failed: {result.get('error')}")
        return 1

    logger.info("=== generate_daily_brief done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
