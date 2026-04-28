"""
generate_wsr_full.py — Sunday Monday WSR generator (Sun 19:30 SGT for Mon).

The deepest synthesis of the week. Reads everything: positions, options,
decision queue, exit plans, scan results, all daily briefs from the past
week, the previous Monday WSR. Produces the long-form WSR markdown that
drives Sarah and Caspar's actions for the coming week.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _setup_logging() -> logging.Logger:
    logger = logging.getLogger("wsr-full")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(h)
    return logger


def gather_state(logger: logging.Logger) -> dict:
    """Pull the entire week's data — last 7 days of macro/snapshots, all
    open positions, options, decision queue, last 5 daily briefs, last WSR."""
    from src.sync import load_env
    from src import sheets as sh
    load_env()
    client = sh.authenticate()
    ss = sh._open_sheet(client)

    state: dict = {}

    # Macro: last 7 rows for trend
    rows = ss.worksheet("macro").get_all_values()
    if len(rows) > 1:
        state["macro_history"] = [dict(zip(rows[0], r)) for r in rows[-7:]]
        state["macro_latest"]  = state["macro_history"][-1]

    # Snapshots: last 7 rows
    for tab in ("snapshot_caspar", "snapshot_sarah"):
        rows = ss.worksheet(tab).get_all_values()
        if len(rows) > 1:
            state[f"{tab}_history"] = [dict(zip(rows[0], r)) for r in rows[-7:]]
            state[tab] = state[f"{tab}_history"][-1]

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

    # Latest of: options, exit_plans, options_defense, decision_queue, wheel_next_leg, scan_results, technical_scores, option_recommendations
    for tab in ("options", "exit_plans", "options_defense", "decision_queue",
                "wheel_next_leg", "scan_results", "technical_scores"):
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
            logger.warning(f"{tab} fetch failed: {e}")
            state[tab] = []

    # Latest market_scan recommendations (last 30)
    try:
        rows = ss.worksheet("option_recommendations").get_all_values()
        if len(rows) > 1:
            headers = rows[0]
            data = [dict(zip(headers, r)) for r in rows[1:] if any(r)]
            state["option_recommendations"] = sorted(data, key=lambda r: r.get("date", ""), reverse=True)[:30]
    except Exception as e:
        logger.warning(f"recommendations fetch failed: {e}")

    # Last 5 daily briefs (this week)
    try:
        rows = ss.worksheet("daily_brief_latest").get_all_values()
        if len(rows) > 1:
            headers = rows[0]
            data = [dict(zip(headers, r)) for r in rows[1:] if any(r)]
            state["recent_briefs"] = sorted(data, key=lambda r: r.get("date", ""), reverse=True)[:5]
    except Exception:
        pass

    # Last full WSR (week-over-week comparison)
    try:
        rows = ss.worksheet("wsr_summary").get_all_values()
        if len(rows) > 1:
            headers = rows[0]
            data = [dict(zip(headers, r)) for r in rows[1:] if any(r)]
            full_rows = [r for r in data if r.get("source", "") != "wsr_lite"]
            if full_rows:
                state["last_monday_wsr"] = max(full_rows, key=lambda r: r.get("date", ""))
    except Exception:
        pass

    return state


def build_synthesis_prompt(state: dict, target_iso: str) -> tuple[str, str]:
    from src.trading_rules import all_rules_summary

    system = """You are the weekly strategy brain. Sundays at 19:30 SGT, you
produce the Monday WSR — the deepest synthesis of the week. Sarah and
Caspar's Mon-Fri actions come from this document.

Your output JSON will become a 5000-10000 word markdown document. You write
JUDGEMENT, Sonnet writes the prose.

Critical sections you must populate:
- verdict: 1 paragraph (the week's headline judgement)
- macro_read: VIX/SPX/yields/DXY interpreted as a stack
- regime_classification: confirm or shift the regime, with evidence
- week_lookback: events table + thesis_drift_flags + narrative-price divergence
- technical_landscape: SMA/RSI/MACD for ~15-20 key tickers
- redteam_flags: 5-8 challenges to current posture (each tagged with confidence)
- decision_queue_top5: rank vs last week, mark ACTIONABLE/WATCH
- actionable_entries: per-entry table for each BUY ON PULLBACK name
- caspar / sarah: per-account snapshot, performance vs SPY, options scan, action plan, watch triggers

Output JSON inside a ```json fenced block."""

    rules = all_rules_summary()
    state_text = json.dumps(state, indent=2, default=str)
    if len(state_text) > 50000:
        state_text = state_text[:50000] + "\n... [TRUNCATED — too large]"

    user = f"""Today is Sunday, generating WSR for week of {target_iso}.

## Trading rules
```json
{json.dumps(rules, indent=2)}
```

## Full state (week of data)
```json
{state_text}
```

## Your task

1. Use web_search to gather:
   - Week's SPX/NDX/RUT closing prices, % moves, internals
   - Sector rotation (which sectors led / lagged)
   - Earnings reactions this past week
   - Earnings + macro events upcoming next 5 trading days
   - Geopolitics: Iran, China, Russia, OPEC moves
   - Fed: any speakers, dot plot updates, 2Y/10Y/30Y yield trajectory
   - Commodities: oil, gold, silver, copper

2. For EACH position in positions_caspar and positions_sarah, evaluate:
   - Is it within sizing rules?
   - Has its thesis played out, broken, or carried over?
   - Should it trim/exit/add?

3. For EACH open option, evaluate:
   - Distance to strike, days to expiry, assignment risk
   - Roll candidate? Take profit?

4. Re-rank decision_queue top 5. Note rank changes vs last_monday_wsr.

5. Output JSON matching the WSR Full schema (see prompts/sonnet_format_wsr_full.md
   for the exact target structure). Be EXHAUSTIVE on red-team flags — these
   are the most valuable part of the WSR.
"""
    return system, user


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--skip-web", action="store_true")
    ap.add_argument("--date", default=None,
                    help="Date the WSR is for (typically tomorrow Monday). Default: tomorrow.")
    args = ap.parse_args()

    logger = _setup_logging()
    logger.info("=== generate_wsr_full start ===")
    target_iso = args.date or (date.today() + timedelta(days=1)).isoformat()

    state = gather_state(logger)
    logger.info(f"State: positions_c={len(state.get('positions_caspar', []))}, "
                f"positions_s={len(state.get('positions_sarah', []))}, "
                f"options={len(state.get('options', []))}, "
                f"queue={len(state.get('decision_queue', []))}, "
                f"recent_briefs={len(state.get('recent_briefs', []))}")

    system, user = build_synthesis_prompt(state, target_iso)

    from scripts.generate_daily_brief import call_opus_with_web_search
    # WSR Full uses higher max_tokens because synthesis is bigger
    from src.llm_brain import _client, MODEL_OPUS, _extract_json
    client = _client()
    tools = [] if args.skip_web else [{"type": "web_search_20250305", "name": "web_search", "max_uses": 12}]
    logger.info(f"Calling {MODEL_OPUS} (web_search={'on' if not args.skip_web else 'off'}, max_tokens=8192)")
    resp = client.messages.create(
        model=MODEL_OPUS, max_tokens=8192, temperature=0.5,
        system=system, messages=[{"role": "user", "content": user}], tools=tools,
    )
    text = "\n".join([b.text for b in resp.content if hasattr(b, "text")])
    logger.info(f"Opus usage: in={resp.usage.input_tokens} out={resp.usage.output_tokens}")
    json_text = _extract_json(text)
    if not json_text:
        logger.error(f"Opus did not return JSON: {text[:500]}")
        return 1
    synthesis = json.loads(json_text)

    from src.llm_brain import format_markdown
    markdown = format_markdown(
        template_path="prompts/sonnet_format_wsr_full.md",
        synthesis_json=synthesis,
        max_tokens=16384,
    )
    logger.info(f"Sonnet done: {len(markdown)} chars markdown")

    payload = {
        "type": "wsr_full",
        "date": target_iso,
        "verdict":         synthesis.get("verdict", ""),
        "confidence":      float(synthesis.get("confidence", 0.7)),
        "regime":          synthesis.get("regime", synthesis.get("regime_classification", {}).get("current", "")),
        "macro_read":      synthesis.get("macro_read", {}).get("narrative", "") if isinstance(synthesis.get("macro_read"), dict) else synthesis.get("macro_read", ""),
        "action_summary":  "",  # WSR Full doesn't surface a one-liner — full action plan is in raw_md
        "options_summary": "",
        "redteam_summary": "; ".join(f.get("text", "")[:200] for f in synthesis.get("redteam_flags", [])[:3]),
        "week_events":     "",
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
