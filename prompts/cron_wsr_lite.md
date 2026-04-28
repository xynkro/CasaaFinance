# WSR Lite — Opus 4.7 Mid-Week Pulse

You run **Wed and Fri at 19:30 SGT** (just before US market open). This is the mid-week check-in — shorter than Monday's WSR, but full of trigger audits and decision-queue updates. The PWA Mid-Week Pulse card shows your output.

## Your job — 5 steps

### 1. Date & context

- Today is `$(date +%Y-%m-%d)`. It's a `$(date +%A)` (should be Wed or Fri).
- US markets closed yesterday. Current week's WSR (Monday) lives in the `wsr_summary` sheet — read it for context.

### 2. Gather state

```bash
cd /Users/xynkro/Documents/Trading/FinancePWA && source .venv/bin/activate

# Read latest Monday WSR — your reference for triggers, decision queue, options book
python3 -c "
from src.sync import load_env
from src import sheets as sh
load_env()
client = sh.authenticate()
ss = sh._open_sheet(client)
ws = ss.worksheet('wsr_summary')
rows = ws.get_all_values()
# Latest non-lite (full WSR)
full_rows = [r for r in rows[1:] if r[1] != 'wsr_lite']
if full_rows:
    latest = max(full_rows, key=lambda r: r[0])
    print('LATEST FULL WSR:', latest[0])
    print('VERDICT:', latest[2][:300])
    print('REGIME:', latest[4])
    print('---')
    print('RAW_MD (first 2000 chars):')
    print(latest[10][:2000])
"
```

Also pull positions, options, exit_plans, decision_queue, scan_results, technical_scores, latest macro, and option_recommendations — same pattern as the daily brief.

### 3. Check trigger states (the most important section)

For every trigger from the Monday WSR (TQQQ $52, SSO $60, MSFT $405, etc.):
- HIT — current price is past the trigger level
- CLOSE — within 3% of trigger
- DORMANT — not near trigger

Also check options book — for each open option position:
- 🟢 — Safe (>10% OTM, low assignment risk)
- 🟡 — Drifting (5-10% OTM, watch)
- 🔴 — In trouble (ITM or imminent assignment)

Use the rules from `src/trading_rules.py` — particularly `ROLL_RULES` for delta thresholds.

### 4. Synthesize JSON (compact — Sonnet expands later)

Output a JSON matching this schema (pass to Sonnet template at `prompts/sonnet_format_wsr_lite.md`):

```json
{
  "type": "wsr_lite",
  "date": "YYYY-MM-DD",
  "regime": "bull_late_cycle",
  "regime_unchanged": true|false,
  "regime_drift_text": "1-2 paragraphs synthesising the past 2-3 days",
  "trigger_audit": [...],
  "options_book": [...],
  "decision_queue": [...],
  "catalysts": [...],
  "bottom_line": {
    "text": "1-3 sentence imperative — what to do this morning",
    "confidence": 0.85,
    "tag": "Synthesis"
  },
  "verdict": "same as bottom_line.text — single line",
  "confidence": 0.85,
  "macro_read": "very short, since this is the mid-week pulse",
  "action_summary": "what to do today",
  "options_summary": "options book status one-liner",
  "redteam_summary": "any new red-team flag since Monday",
  "week_events": ""
}
```

The `verdict`, `confidence`, etc. are flat fields used by `push_brief.py` for the sheet schema. The nested `trigger_audit`, `options_book`, etc. feed into Sonnet's formatter.

### 5. Format and push

Same pattern as daily brief:

**5a — Sonnet expands:**

```
Agent({
  description: "Format WSR Lite JSON to markdown",
  subagent_type: "general-purpose",
  model: "sonnet",
  prompt: <contents of prompts/sonnet_format_wsr_lite.md> + "\n\n```json\n" + <synthesis JSON> + "\n```"
})
```

**5b — combine and push:**

```python
payload = {
  "type": "wsr_lite",
  "date": "...",
  "verdict": "...",        # from your synthesis
  "confidence": 0.85,
  "regime": "...",
  "macro_read": "...",
  "action_summary": "...",
  "options_summary": "...",
  "redteam_summary": "...",
  "week_events": "",
  "raw_md": <markdown from sonnet>
}
```

Save to `/tmp/wsr_lite_payload.json`, then:

```bash
python3 scripts/push_brief.py --json-file /tmp/wsr_lite_payload.json
rm /tmp/wsr_lite_payload.json
```

## Cost discipline

- ~600-800 tokens of synthesis JSON max.
- Trigger audit and options book are the meat — give those structure, not prose.
- Sonnet will expand into ~3000-token markdown.

## Failure modes

- **No Monday WSR exists yet**: still produce a Lite based on what's in the sheets. Note this in `redteam_summary`.
- **Position data is stale (>24h)**: degrade the trigger audit — flag with "data is {N}h stale" in each row's note.

## Done when

- `wsr_summary` sheet has a fresh row with `source="wsr_lite"` for today's date
- `WSR Lite/` Drive folder has `{YYYYMMDD}_WSR_lite.md`
- The PWA Mid-Week Pulse card refreshes within 15 min and shows your output
