"""
generate_wsr_lite.py — Mid-week WSR Lite generator (Wed/Fri 19:30 SGT).

Cloud-native: gathers state from Sheets, runs Opus 4.7 synthesis (with web
research), Sonnet 4.6 formatting, writes to wsr_summary sheet + Drive.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _setup_logging() -> logging.Logger:
    logger = logging.getLogger("wsr-lite")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(h)
    return logger


def gather_state(logger: logging.Logger) -> dict:
    """Pull EVERYTHING needed for a mid-week pulse — positions, options book,
    decision queue, exit plans, scan results, latest WSR Monday for context."""
    from src.sync import load_env
    from src import sheets as sh
    load_env()
    client = sh.authenticate()
    ss = sh._open_sheet(client)

    state: dict = {}

    # Latest macro
    rows = ss.worksheet("macro").get_all_values()
    state["macro_latest"] = dict(zip(rows[0], rows[-1])) if len(rows) > 1 else None

    # Snapshots
    for tab in ("snapshot_caspar", "snapshot_sarah"):
        rows = ss.worksheet(tab).get_all_values()
        state[tab] = dict(zip(rows[0], rows[-1])) if len(rows) > 1 else None

    # Latest positions
    for tab in ("positions_caspar", "positions_sarah"):
        rows = ss.worksheet(tab).get_all_values()
        if len(rows) > 1:
            headers = rows[0]
            data = [dict(zip(headers, r)) for r in rows[1:] if any(r)]
            latest_date = max(r.get("date", "") for r in data)
            state[tab] = [r for r in data if r.get("date") == latest_date]
        else:
            state[tab] = []

    # Open options + exit plans + decision queue
    for tab in ("options", "exit_plans", "options_defense", "decision_queue", "wheel_next_leg", "scan_results"):
        try:
            rows = ss.worksheet(tab).get_all_values()
            if len(rows) > 1:
                headers = rows[0]
                data = [dict(zip(headers, r)) for r in rows[1:] if any(r)]
                latest_date = max(r.get("date", "") for r in data)
                state[tab] = [r for r in data if r.get("date") == latest_date]
            else:
                state[tab] = []
        except Exception as e:
            logger.warning(f"{tab} missing: {e}")
            state[tab] = []

    # Last full WSR for thesis-carry-over
    try:
        rows = ss.worksheet("wsr_summary").get_all_values()
        if len(rows) > 1:
            headers = rows[0]
            data = [dict(zip(headers, r)) for r in rows[1:] if any(r)]
            full_rows = [r for r in data if r.get("source", "") != "wsr_lite"]
            if full_rows:
                state["last_monday_wsr"] = max(full_rows, key=lambda r: r.get("date", ""))
    except Exception as e:
        logger.warning(f"wsr_summary fetch failed: {e}")

    # Recent daily briefs (last 3 — covers this week so far)
    try:
        rows = ss.worksheet("daily_brief_latest").get_all_values()
        if len(rows) > 3:
            headers = rows[0]
            data = [dict(zip(headers, r)) for r in rows[1:] if any(r)]
            state["recent_briefs"] = sorted(data, key=lambda r: r.get("date", ""), reverse=True)[:5]
    except Exception as e:
        logger.warning(f"daily_brief fetch failed: {e}")

    return state


def build_synthesis_prompt(state: dict, today_iso: str) -> tuple[str, str]:
    from src.trading_rules import all_rules_summary

    system = """You are the mid-week trading brain. Wed and Fri at 19:30 SGT,
you produce a WSR Lite — a 6-section pulse that audits triggers, options book,
decision queue, and regime drift since Monday's WSR.

You are NOT writing prose — Sonnet expands later. Your job is the JUDGEMENT:
- Which triggers are HIT, CLOSE, DORMANT?
- Which option positions are 🟢 (safe), 🟡 (watch), 🔴 (defend)?
- Has regime drifted since Monday?
- Which decision-queue entries are now ACTIONABLE?
- What 3 catalysts matter most in the next 3 trading days?
- Bottom line: 1-3 sentence imperative — what to do tomorrow morning.

Output JSON inside a ```json fenced block. Be opinionated."""

    rules = all_rules_summary()

    user = f"""Today is {today_iso}. Generate the WSR Lite mid-week pulse.

## Trading rules
```json
{json.dumps(rules, indent=2)}
```

## Current state (positions, options, queue, last Monday WSR for context)
```json
{json.dumps(state, indent=2, default=str)[:30000]}
```

## Your task

1. Use web_search to gather:
   - This week's SPX/NDX moves vs trigger levels
   - Earnings already reported this week + reactions
   - Earnings still upcoming next 3 trading days
   - Macro events this week (Fed, CPI, jobs)

2. Compute trigger_audit, options_book_status, decision_queue_status using the rules.

3. Output JSON in this schema:

```json
{{
  "type": "wsr_lite",
  "date": "{today_iso}",
  "regime": "bull_late_cycle",
  "regime_unchanged": true,
  "regime_drift_text": "1-2 paragraphs on what's changed (or hasn't) since Monday",
  "trigger_audit": [
    {{"ticker": "TQQQ", "price": "$58.59", "status": "HIT|CLOSE|DORMANT",
      "trigger_value": "$52", "action": "Trim 5 shares on next bounce"}}
  ],
  "options_book": [
    {{"ticker": "AAPL", "strategy": "CSP", "strike": "$225", "dte": 21,
      "underlying": "$270", "proximity": "16% OTM",
      "flag": "🟢", "note": "Safe — collect to expiry"}}
  ],
  "decision_queue": [
    {{"rank": 1, "ticker": "SCHD", "entry": "$30.40", "last": "$31.10",
      "distance_pct": "+2.3%", "status": "ACTIONABLE|CLOSE|WAIT",
      "status_note": "always accumulating"}}
  ],
  "catalysts": [
    {{"day": "Mon", "bullets": ["NFLX earnings", "Consumer confidence"]}}
  ],
  "bottom_line": {{
    "text": "1-3 sentence synthesis",
    "confidence": 0.85,
    "tag": "Synthesis"
  }},
  "verdict": "single-line — same as bottom_line.text",
  "confidence": 0.85,
  "macro_read": "very short, mid-week",
  "action_summary": "what to do tomorrow morning",
  "options_summary": "options book one-liner",
  "redteam_summary": "any new red-team flag since Monday",
  "week_events": ""
}}
```

CONSTRAINTS:
- trigger_audit MUST contain every trigger from the last Monday WSR
- options_book MUST contain every open option position
- decision_queue MUST be the top 5 entries from the last decision queue
- catalysts MUST cover next 3 trading days
"""
    return system, user


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--skip-web", action="store_true")
    ap.add_argument("--date", default=None)
    args = ap.parse_args()

    logger = _setup_logging()
    logger.info("=== generate_wsr_lite start ===")
    today_iso = args.date or date.today().isoformat()

    state = gather_state(logger)
    logger.info(f"State: caspar={len(state.get('positions_caspar', []))}, "
                f"sarah={len(state.get('positions_sarah', []))}, "
                f"options={len(state.get('options', []))}, "
                f"queue={len(state.get('decision_queue', []))}")

    system, user = build_synthesis_prompt(state, today_iso)

    # Reuse the Opus+web_search call from daily brief
    from scripts.generate_daily_brief import call_opus_with_web_search
    synthesis = call_opus_with_web_search(system, user, logger, skip_web=args.skip_web)
    logger.info(f"Opus done: {synthesis.get('verdict', '?')[:80]}")

    from src.llm_brain import format_markdown
    markdown = format_markdown(
        template_path="prompts/sonnet_format_wsr_lite.md",
        synthesis_json=synthesis,
    )
    logger.info(f"Sonnet done: {len(markdown)} chars markdown")

    payload = {
        "type": "wsr_lite",
        "date": today_iso,
        "verdict":         synthesis.get("verdict", ""),
        "confidence":      float(synthesis.get("confidence", 0.7)),
        "regime":          synthesis.get("regime", ""),
        "macro_read":      synthesis.get("macro_read", ""),
        "action_summary":  synthesis.get("action_summary", ""),
        "options_summary": synthesis.get("options_summary", ""),
        "redteam_summary": synthesis.get("redteam_summary", ""),
        "week_events":     synthesis.get("week_events", ""),
        "raw_md":          markdown,
    }

    if args.dry:
        logger.info("[DRY] payload preview:")
        print(json.dumps(payload, indent=2)[:2000])
        return 0

    from scripts.push_brief import push_brief
    result = push_brief(payload, no_drive=False)
    logger.info(f"push_brief result: {result}")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
