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

**5b — push the WSR Lite markdown to wsr_summary + Drive:**

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

**5c — refresh the unified decision_queue with mid-week reality:**

The Mid-Week Pulse should refresh both the share-entry queue (status
transitions: `watching` → `pending` if price hit the zone, `pending` →
`filled` if user executed, anything → `killed` if thesis broke) AND the
open options book (each held CSP / CC / PMCC reported as a `filled`
decision row with the thesis updated to current proximity / IV / DTE).

Build ONE JSON. Both share AND option entries — same unified shape as
WSR Full §6c, but with `"source": "wsr_lite"`.

```json
{
  "date": "<today_iso>",
  "decisions": [
    {
      "ticker":            "MDT",
      "account":           "sarah",
      "bucket":            "quality",
      "thesis_1liner":     "Now $86, 2.4% above entry — CLOSE but not yet ACTIONABLE. Watch for pullback to $84.",
      "conv":              4,
      "entry":             84.00,
      "target":            96.00,
      "status":            "watching",
      "strategy":          "BUY_DIP",
      "right":             "",
      "strike":            0,
      "expiry":            "",
      "premium_per_share": 0,
      "delta":             0,
      "annual_yield_pct":  0,
      "breakeven":         0,
      "cash_required":     8400,
      "iv_rank":           0,
      "thesis_confidence": 0.70,
      "thesis":            "<2-4 sentence brain thesis updated for mid-week price action>",
      "source":            "wsr_lite"
    },
    {
      "ticker":            "AAPL",
      "account":           "sarah",
      "bucket":            "blue_chip",
      "thesis_1liner":     "AAPL $250P 19% OTM (was 17% Mon), safe to expiry — collect full $4.50 premium.",
      "conv":              4,
      "entry":             250.00,
      "target":            245.50,
      "status":            "filled",
      "strategy":          "CSP",
      "right":             "P",
      "strike":            250.00,
      "expiry":            "20260619",
      "premium_per_share": 4.50,
      "delta":             0.18,
      "annual_yield_pct":  14.0,
      "breakeven":         245.50,
      "cash_required":     25000,
      "iv_rank":           26,
      "thesis_confidence": 0.70,
      "thesis":            "<mid-week reality — proximity, IV change, DTE remaining, what to do at expiry>",
      "source":            "wsr_lite"
    }
  ]
}
```

Save to `/tmp/wsr_lite_decisions.json` and run:
```bash
python3 scripts/push_decisions.py --json-file /tmp/wsr_lite_decisions.json
rm /tmp/wsr_lite_decisions.json
```

**Upsert key:** `(date, account, ticker, strategy, strike)`. The lite run
re-emits the same week's entries with refreshed thesis — re-running
overwrites by design. You CAN emit BOTH a `BUY_DIP MDT` AND a `CSP MDT
$80P` in the same week without collision.

**Status values:** `pending` / `watching` / `filled` / `killed` /
`expired`. Use `filled` for currently-held option positions whose thesis
you're refreshing for mid-week.

**Strategy values:** `BUY_DIP`, `TRIM`, `CSP`, `CC`, `PMCC`, `LONG_CALL`,
`LONG_PUT`. For share entries: use `""` (empty string) for `right` and
`expiry`, and 0 for `strike` / premium / delta / yield / breakeven /
iv_rank. Always populate ALL fields — never omit a key.

**Empty week:** if you have zero actionable entries (no held options,
no new ideas), SKIP §5c entirely (do not invoke push_decisions.py with
an empty `decisions[]` array — the script will error).

The legacy `option_recommendations` sheet is no longer written by the brain.
The PWA Options › Ideas tab was removed in Phase D — the unified
`decision_queue` is now the single surface for both share + option ideas.
The brain still READS the last 30 rows of `option_recommendations` as
historical context (see §2) — that sheet keeps accumulating from
`market_scan.py` and `daily_options_scan.py`.

**🚨 CC ELIGIBILITY RULE (non-negotiable):**

NEVER recommend `"strategy": "CC"` on `core` (SCHD, broad ETFs),
`leveraged_etf` (TQQQ, SSO), or `blue_chip` unless strike ≥ 115% cost.
Wheeling SCHD specifically is a thesis violation — interrupting the
100-share milestone for a small premium kills the long-term compounder
plan. See `cc_eligible_buckets` in the trading rules dict.

CSP on those names IS appropriate — paid to maybe acquire the compounder.

**Thesis content rule:** the `thesis` field is what the user sees when
they tap a Decisions card. It MUST be brain synthesis, not rule-filter
math. The `thesis_1liner` is the glanceable summary; `thesis` is the
deep version.

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
