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

### 6. Format and push

```
Agent({
  description: "Format WSR Full JSON to markdown",
  subagent_type: "general-purpose",
  model: "sonnet",
  prompt: <contents of prompts/sonnet_format_wsr_full.md> + "\n\n```json\n" + <synthesis JSON> + "\n```"
})
```

Build payload, save to `/tmp/wsr_full_payload.json`, run:

```bash
python3 scripts/push_brief.py --json-file /tmp/wsr_full_payload.json
rm /tmp/wsr_full_payload.json
```

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
