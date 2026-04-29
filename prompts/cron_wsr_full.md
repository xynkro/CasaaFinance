# Weekly Strategy Review (Monday) — Opus 4.7 Deep Synthesis

You run **Sundays at 19:30 SGT** to produce the full Monday WSR. This is the longest, deepest output of the week — the brain reviews every position, every option, every decision-queue entry, and every red-team flag. Sarah and Caspar's actions Mon-Fri come from this document.

## Your job — 7 steps

### 1. Date & context

- Today is `$(date +%Y-%m-%d)` (should be Sunday).
- The WSR is dated for the **upcoming Monday**, not today.
- Read the previous Monday's WSR for continuity (decision queue rank changes, thesis carry-over).

### 2. Gather complete state

This is the most data-intensive cron. Pull EVERYTHING:

```python
# Use the existing data layer
from src.sync import load_env
from src import sheets as sh
load_env()
client = sh.authenticate()
ss = sh._open_sheet(client)

# All required tabs:
# - macro (last 7 rows for week trend)
# - snapshot_caspar, snapshot_sarah (last 7 rows for WoW deltas)
# - positions_caspar, positions_sarah (latest snapshot only)
# - options (all open positions)
# - option_recommendations (latest market_scan output)
# - scan_results (latest IBKR scan if TWS was on)
# - exit_plans (latest)
# - options_defense (latest)
# - decision_queue (latest)
# - technical_scores (latest)
# - daily_brief_latest (last 5 rows for week lookback)
# - wsr_summary (last full WSR for thesis-carry-over)
```

### 3. Web research — week's macro & news

Search broadly for:
- Week's SPX/NDX/RUT moves and 50/200 SMA position
- Earnings calendar next 5 days for major names
- Fed events: FOMC, speakers, dot-plot updates
- Geopolitics: Iran/Hormuz, China/Taiwan, US-China trade
- Commodity macro: oil OPEC actions, gold/silver narrative
- Sector rotation: which sectors lead/lag last week
- Yields curve: 2Y/10Y/30Y movement

Look up specific tickers on the decision queue + watchlist for week-defining catalysts (earnings, FDA dates, regulatory).

### 4. Apply trading rules

Reference `src/trading_rules.py`:
- `regime_max_leverage(regime)` — current cap
- `regime_cash_floor(regime)` — minimum cash
- For each position, call `position_action(p, regime)` to get HOLD/TRIM/EXIT recommendation
- For options book, check ROLL_RULES delta thresholds

Document any rule breaches in the red-team flags.

### 5. Synthesize the deep JSON

Output a JSON matching `prompts/sonnet_format_wsr_full.md`'s schema. This is the LARGEST synthesis — but still keep YOUR output as JSON (Sonnet expands the prose).

Aim for ~1500-2000 tokens of JSON synthesis. Sonnet will turn this into 5000-10000 token markdown.

Critical sections:

**Verdict (1 paragraph):** What did the market do this week? What does it mean? What's the one thing to do this week?

**Macro read (2 paragraphs):** VIX/SPX/yields/DXY/USD-SGD reading. Interpret the stack — bull, bear, mixed signals?

**Regime classification:** Confirm or change the regime. List evidence for and against.

**Week lookback:** Each daily brief contributed something. What were the events Mon-Fri? What positions were affected?

**Thesis drift flags:** For each position with a stated thesis, did this week confirm or break it? Flag any thesis still active but unresolved.

**Technical landscape:** SMA/RSI/MACD for ~15-20 key tickers (positions + queue + watchlist).

**Red-team flags:** 5-8 flags challenging current posture. Each tagged with confidence.

**Decision queue (top 5):** Re-rank vs last week. Note promotions/demotions. Mark which are ACTIONABLE vs WATCH.

**Actionable entries:** For each "BUY ON PULLBACK" name, give entry/target/stop/catalysts.

**For Caspar / For Sarah:** Per-account snapshot, performance, options scan, action plan, watch triggers.

### 6. Format and push (THREE writes, not one)

The WSR Full now writes to **THREE** places so the structured PWA tabs
(Decisions, Strategy Notes) get brain content, not stale legacy or
rule-filter math.

**6a — Sonnet expands JSON to markdown:**

```
Agent({
  description: "Format WSR Full JSON to markdown",
  subagent_type: "general-purpose",
  model: "sonnet",
  prompt: <contents of prompts/sonnet_format_wsr_full.md> + "\n\n```json\n" + <synthesis JSON> + "\n```"
})
```

**6b — push the WSR markdown to wsr_summary + Drive:**

Save to `/tmp/wsr_full_payload.json` and run:
```bash
python3 scripts/push_brief.py --json-file /tmp/wsr_full_payload.json
rm /tmp/wsr_full_payload.json
```

**6c — push structured Decision Queue rows to decision_queue sheet:**

For EACH entry in your `decision_queue_top5` synthesis, plus any other
named entries you discussed (e.g. "MDT BUY ON PULLBACK"), build:

```json
{
  "date": "<target_iso>",
  "decisions": [
    {
      "ticker":         "MDT",
      "account":        "sarah",
      "bucket":         "quality",
      "thesis_1liner":  "Wide-moat medical, dividend aristocrat, at SMA50 support. Entry $84 → target $96 (15% upside, 8% to stop).",
      "conv":           4,
      "entry":          84.00,
      "target":         96.00,
      "status":         "pending"
    }
  ]
}
```

Save to `/tmp/wsr_decisions.json` and run:
```bash
python3 scripts/push_decisions.py --json-file /tmp/wsr_decisions.json
rm /tmp/wsr_decisions.json
```

**status** values: `"pending"` (live entry), `"watching"` (price not yet
in zone), `"filled"` (already executed), `"killed"` (thesis broken).

**6d — push structured Strategy Notes to option_recommendations sheet:**

For each "Actionable Entry" + each open option position with brain
judgement, build:

```json
{
  "date": "<target_iso>",
  "source": "wsr_full",
  "recommendations": [
    {
      "ticker": "MDT",
      "account": "sarah",
      "strategy": "BUY_DIP",
      "right": "",
      "strike": 84.00,
      "expiry": "",
      "premium_per_share": 0,
      "delta": 0,
      "annual_yield_pct": 0,
      "breakeven": 84.00,
      "cash_required": 8400,
      "iv_rank": 0,
      "thesis_confidence": 0.70,
      "thesis": "<2-4 sentence brain thesis — WHY this entry, WHY now, WHAT cancels it, WHAT to watch>",
      "status": "proposed"
    },
    {
      "ticker": "AAPL",
      "account": "sarah",
      "strategy": "CSP",
      "right": "P",
      "strike": 250.00,
      "expiry": "20260619",
      "premium_per_share": 4.50,
      "delta": 0.20,
      "annual_yield_pct": 14.0,
      "breakeven": 245.50,
      "cash_required": 25000,
      "iv_rank": 28,
      "thesis_confidence": 0.65,
      "thesis": "<brain thesis>",
      "status": "proposed"
    }
  ]
}
```

Save to `/tmp/wsr_recs.json` and run:
```bash
python3 scripts/push_recommendations.py --json-file /tmp/wsr_recs.json
rm /tmp/wsr_recs.json
```

**Strategy values:** `BUY_DIP` (share entry), `CSP`, `CC`, `PMCC`,
`LONG_CALL`, `LONG_PUT`. Use empty string for `right` when it's a share
entry (no option contract).

**Thesis content rule:** the thesis field is what the user sees when
they tap a Strategy Notes card. It MUST be brain synthesis, not
rule-filter math. Include: WHY the trade, WHY now (catalysts/levels),
WHAT cancels the thesis (stop levels), WHAT to watch (news/data).

### 7. Generate watch-trigger list for the coming week

These get auto-checked by the Wed/Fri WSR Lite cron. Make sure they're crisp, e.g.:
- TQQQ $52+ → trim 3 shares
- AAPL earnings April 29 pre-market → close $225 CSP if > 50% profit
- MDT $84 → enter Sarah CSP $80P (4% below entry, 35DTE, target 18%/yr)
- SPX 7000 → reassess if SPX > 7,250 (FOMO add) or < 6,950 (regime shift)

Embed in the WSR's Caspar/Sarah action plans + watch_triggers fields.

## Cost discipline

- WSR Full will be your most expensive run — ~$1.50 in mixed Opus+Sonnet, 1-2 minutes runtime.
- Worth it because it sets the week's strategy. But be efficient: synthesise tightly, let Sonnet expand.
- Total Opus turns: aim for 12-15 (more data gathering and research than other crons).

## Done when

- `wsr_summary` sheet has a fresh row with `source="{YYYYMMDD}_WSR.md"` for today
- `Weekly Strategy Review/` Drive folder has the markdown archive
- `wsr_archive` sheet has a row pointing to the new Drive file
- The PWA Weekly tab refreshes within 15 min and shows your output
