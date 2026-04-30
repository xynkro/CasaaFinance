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

### 6. Format and push (TWO writes — markdown + unified decision queue)

The WSR Full writes to **TWO** places: the `wsr_summary` sheet (markdown for
the Home Weekly card) and the `decision_queue` sheet (the unified weekly
action queue the PWA Decisions tab reads). Both share-entry ideas (BUY_DIP /
TRIM) AND option-entry ideas (CSP / CC / PMCC / LONG_CALL / LONG_PUT) live in
the same `decision_queue` JSON now — the brain emits one queue, not two.

The legacy `option_recommendations` sheet (formerly "Strategy Notes") is no
longer written by the brain. The PWA Options › Ideas tab was removed in
Phase D — the unified `decision_queue` is now the single surface for both
share + option ideas. The brain still READS the last 30 rows of
`option_recommendations` as historical context (see §2 state-gather) — that
sheet keeps accumulating from `market_scan.py` and `daily_options_scan.py`.

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

**6c — push the unified decision_queue (share + option entries together):**

Build ONE JSON containing every actionable idea for the week — both share
entries (BUY_DIP / TRIM) AND option entries (CSP / CC / PMCC / LONG_CALL /
LONG_PUT). Each entry carries the strategic 1-liner (`thesis_1liner`) AND
the multi-sentence brain `thesis`. Option entries also carry strike /
expiry / premium / delta / yield / breakeven / cash / IV rank.

```json
{
  "date": "<target_iso>",
  "decisions": [
    {
      "ticker":            "MDT",
      "account":           "sarah",
      "bucket":            "quality",
      "thesis_1liner":     "Wide-moat medical at SMA50 support. Entry $84 → target $96 (15% upside, 8% to stop).",
      "conv":              4,
      "entry":             84.00,
      "target":            96.00,
      "status":            "pending",
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
      "thesis":            "<2-4 sentence brain thesis: WHY this entry, WHY now (catalysts/levels), WHAT cancels (stop levels), WHAT to watch (news/data)>",
      "source":            "wsr_full"
    },
    {
      "ticker":            "AAPL",
      "account":           "sarah",
      "bucket":            "blue_chip",
      "thesis_1liner":     "AAPL CSP $250P 35DTE — collect premium in low-IV regime.",
      "conv":              4,
      "entry":             250.00,
      "target":            245.50,
      "status":            "pending",
      "strategy":          "CSP",
      "right":             "P",
      "strike":            250.00,
      "expiry":            "20260619",
      "premium_per_share": 4.50,
      "delta":             0.20,
      "annual_yield_pct":  14.0,
      "breakeven":         245.50,
      "cash_required":     25000,
      "iv_rank":           28,
      "thesis_confidence": 0.65,
      "thesis":            "<brain thesis>",
      "source":            "wsr_full"
    }
  ]
}
```

Save to `/tmp/wsr_decisions.json` and run:
```bash
python3 scripts/push_decisions.py --json-file /tmp/wsr_decisions.json
rm /tmp/wsr_decisions.json
```

**Upsert key:** `(date, account, ticker, strategy, strike)`. This means you
CAN emit BOTH a `BUY_DIP MDT` row AND a `CSP MDT $80P` row in the same week
without one clobbering the other — strategy + strike differentiate them.

**Status values:** `pending` (live entry, ready to act), `watching` (price
not yet in zone), `filled` (already executed), `killed` (thesis broken),
`expired` (DTE elapsed without action).

**Strategy values:** `BUY_DIP` (share entry on pullback), `TRIM` (share
exit), `CSP`, `CC`, `PMCC`, `LONG_CALL`, `LONG_PUT`. For share entries:
use `""` (empty string) for `right` and `expiry`, and 0 for `strike` /
premium / delta / yield / breakeven / iv_rank. Always populate ALL
fields — use 0 / "" for inapplicable ones, never omit a key.

**Empty week:** if you have zero actionable entries this week, SKIP §6c
entirely (do not invoke push_decisions.py with an empty `decisions[]`
array — the script will error and the run reports a false negative).

**🚨 CC ELIGIBILITY RULE (non-negotiable):**

Before writing ANY `"strategy": "CC"` row, check `cc_eligible_buckets` in
the trading rules. The brain MUST NOT recommend covered calls on:
- `core` bucket (SCHD, broad ETFs) — wheeling away interrupts the
  compounding/dividend plan. SCHD especially is the income engine being
  built toward 100 shares — being called away before that milestone is a
  thesis violation.
- `blue_chip` bucket (AAPL, MSFT, GOOGL, MA, V, JPM) — only if strike ≥
  115% of cost basis. Below that, just hold the stock.
- `leveraged_etf` (TQQQ, SSO) — assignment + decay = compounded losses.

CC IS appropriate on `quality_growth` (AMD, NVDA, META — when you'd accept
exit at strike), `spec_growth` (OPEN, RDDT, SOFI), `lottery` (BBAI, BTBT),
and `commodity_etf` (SLV, GLD on strength).

CSP is the OPPOSITE — `core` and `blue_chip` are the BEST CSP targets
because assignment = paid to acquire the compounder/quality at your price.

If you find yourself drafting a CC on SCHD / SPY / VOO / QQQ / VTI /
AAPL / MSFT etc., STOP and revise. Suggest CSP instead, OR no options
trade and accumulation only.

**Thesis content rule:** the `thesis` field is what the user sees when
they tap a Decisions card. It MUST be brain synthesis, not rule-filter
math. Include: WHY the trade, WHY now (catalysts/levels), WHAT cancels
the thesis (stop levels), WHAT to watch (news/data). The `thesis_1liner`
is the glanceable summary; `thesis` is the deep version.

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
