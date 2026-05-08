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
# - positions_caspar, positions_sarah (latest snapshot only,
#     refreshed hourly by yahoo-grab.yml cloud cron)
# - options (all open positions, refreshed every 30 min during US
#     market hours by options-refresh.yml — moneyness, DTE,
#     assignment_risk, trend_risk, momentum_5d, sigma, RSI, SMAs are
#     all yfinance-derivable and stay fresh even when the Mac is off.
#     New positions are still discovered nightly by Mac ibkr-grab.)
# - option_recommendations (latest market_scan output)
# - scan_results (latest IBKR scan if TWS was on)
# - exit_plans (latest)
# - options_defense (latest)
# - decision_queue (latest — INCLUDES auto-generated rows with
#     source="risk_parity" emitted by scripts/risk_parity_recommend.py
#     for every UNDERWEIGHT asset_class. Treat these as proposals to
#     VALIDATE / REFINE; you may upgrade or downgrade conviction by 1
#     and rewrite thesis prose.)
# - technical_scores (latest)
# - daily_brief_latest (last 5 rows for week lookback)
# - wsr_summary (last full WSR for thesis-carry-over)
# - regime_signals (LAST 7 DAYS, ALL SOURCES — market_breadth, ftd,
#     distribution_day, macro_regime; produced by Agent 1's regime cron)
# - exposure_posture (LATEST ROW ONLY — exposure-coach output: ceiling,
#     bias, participation, recommendation, confidence)
# - screen_candidates (LAST 30 DAYS, BOTH SOURCES — vcp + canslim
#     weekly fresh-blood ticker pool)
# - options_yield_candidates (LATEST 30 — top 20 ranked CSP/CC setups
#     by annualized yield, IV rank, and spread quality. Sunday cron at
#     12:00 UTC writes a fresh batch every week. Read these to propose
#     NEW CSP/CC entries — not just refresh existing positions.)
# - tv_signals (LATEST per ticker, ALL THREE intervals — 1h + 1d + 1W —
#     TradingView's 26-indicator consensus: STRONG_BUY/BUY/NEUTRAL/SELL/
#     STRONG_SELL plus all underlying indicator values. Use 1h to flag
#     intraday traps when 1d says BUY but 1h says SELL.)
# - risk_parity_audit (LATEST 16 — asset class diversification check
#     for both accounts: capital_pct, vol_pct, risk_contribution_pct,
#     target_pct, delta_pct, rebalance_action, rebalance_amount_usd)
# - earnings_calendar (NEXT 30 DAYS, FILTERED TO PORTFOLIO + WATCHLIST —
#     date, ticker, hour BMO/AMC/DMH, eps_estimate, eps_actual,
#     surprise_pct. Read this BEFORE proposing CSPs/CCs — earnings
#     inside option DTE = HARD veto unless you explicitly accept the
#     gamma risk. Brain MUST cite earnings date in thesis when
#     proposing options on a ticker reporting in DTE.)
# - economic_calendar (NEXT 14 DAYS, MEDIUM+HIGH IMPACT, US/EU/CN/JP/SG —
#     date, time, country, event, impact, forecast, actual. Use to
#     anchor week-ahead macro section + flag risk-off windows like
#     CPI/NFP/FOMC days.)
# - news_sentiment (LAST 14 DAYS PER TICKER — id, datetime, ticker,
#     headline, summary, sentiment_score, sentiment_label, source,
#     url. Brain reads to detect sentiment shifts since last WSR. The
#     score is a heuristic — TRUST YOUR OWN SEMANTIC READING of the
#     headline + summary over the score.)
# - insider_transactions (LAST 90 DAYS PER TICKER — date, ticker, name,
#     side buy/sell/grant/exercise, shares, value_usd. Aggregate per
#     ticker per side over last 7 days; flag any ticker with net side=buy
#     >$1M or net side=sell >$5M.)
# - analyst_consensus (LATEST per ticker — strong_buy/buy/hold/sell/
#     strong_sell counts, consensus_score [-2..+2], consensus_label.
#     Use as a Wall St anchor in Decision thesis: "Wall St 42-buy/4-hold/
#     1-sell consensus BUY" gives the user a quick "vs consensus"
#     reference. Compare against last WSR to detect upgrades/downgrades.)
# - watchlist universe: read prompts/watchlist.yaml — categorized
#     ticker pool the brain should consider beyond just held + queue.
#     Categories: held, stock_positions_sarah, decision_queue_active,
#     defensive_etfs, commodity, volatility, blue_chip_dividend,
#     speculative_growth, high_iv_wheel_targets. Use src.watchlist
#     get_universe(client) to resolve the live ticker lists; tv_signals
#     should already cover all of these on the 1h + 1d + 1W consensus.
```

### 3. Web research — supplement only

Most of what you used to web-search now lives in structured Sheet tabs.
Use `WebSearch` to fill ONLY the narrative gaps:

- Week's SPX/NDX/RUT moves and 50/200 SMA position (interpretation, not
  fact-finding — facts in `macro` + `tv_signals` 1W rows)
- Geopolitics: Iran/Hormuz, China/Taiwan, US-China trade — never in our
  feeds
- Commodity macro: oil OPEC actions, gold/silver narrative — narrative
  layer over the macro row prices
- Sector rotation read (the underlying sector ETFs are in tv_signals
  1d + 1W; web-search just for the narrative)
- Pre-FOMC dot-plot expectations or pre-CPI consensus (narrative; the
  date itself is in `economic_calendar`)

**Do NOT** web-search for:
- Earnings dates → `earnings_calendar` has them
- FOMC/CPI/NFP dates → `economic_calendar` has them
- Per-ticker headlines → `news_sentiment` has them
- Insider buying/selling → `insider_transactions` has them
- Analyst targets → `analyst_consensus` has them
- TV indicator values → `tv_signals` has them across 1h + 1d + 1W

This is non-negotiable. Web-searching for data we already have in
sheets makes the brain SLOW and INCONSISTENT (web pages may lag
reality by minutes; structured pulls are guaranteed-fresh).

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

**Regime classification (quant-anchored, NOT vibes):**

Read the latest `regime_signals` rows for all sources. Use them as PRIMARY regime input. Do NOT vibes-classify regime from price action. Specifically:
- `market_breadth.score` < 50 → bias toward defensive
- `distribution_day.label == "HIGH"` or `"SEVERE"` → regime is contracting
- `ftd.label == "FTD_CONFIRMED"` → regime is recovering
- `macro_regime.label` → use as the regime tag in your synthesis JSON

If signals conflict, default to the more conservative interpretation. Do not override quant signals with vibe.

Confirm or change the regime. List evidence for and against. Cite the four scores explicitly in your reasoning.

**TradingView consensus (multi-timeframe confluence check):**

For each held position AND each pending decision_queue entry, read the
latest tv_signals rows on 1d and 1W intervals. Cite explicitly in the
thesis when:
- Daily and weekly DISAGREE (one BUY, other SELL) → flag as "TF divergence"
  in red-team flags. Don't propose new entries on TF-divergent names.
- Daily AND weekly both STRONG_BUY → consensus tailwind, fine to add.
- Daily SELL on a position we hold → flag in defense, consider trim.
- RSI > 75 on weekly + daily → overbought; flag in red-team.
- RSI < 30 on weekly + daily AND we hold a CSP → assignment risk rising.

Do NOT mechanically follow TV recommendation — it's one input among
many. Use it as a sanity-check on your own thesis.

For NEW BUY_DIP candidates from screen_candidates, REQUIRE:
  - daily TV recommendation in {BUY, STRONG_BUY}
  - weekly TV recommendation NOT in {SELL, STRONG_SELL}
If neither holds, demote to status=watching with note "TV signal
weak — wait for confluence."

For swing-trading entry/exit pattern recognition, see `prompts/swing_playbook.md`.
Cite the named pattern in your thesis when applicable (e.g. "Pullback to 20EMA",
"VCP", "Liquidity sweep", "Breakout retest").

**Screen candidates (fresh-blood ingestion):**

Read the last 30 days of `screen_candidates` rows. For each ticker NOT already in your decision_queue:
- Cross-check against your trading_rules.py bucket assignment
- If it fits a bucket you can size into AND `exposure_posture` allows new entries: consider proposing as `BUY_DIP` candidate
- If exposure is constrained: add as `status: watching` with the screen's trigger_price as entry

The vcp-screener feeds Minervini-style breakout candidates. canslim-screener feeds O'Neil growth candidates. Treat them as fresh-blood inputs.

**Options yield candidates (fresh CSP/CC ingestion):**

Read the latest `options_yield_candidates` rows. For each top-5 candidate
NOT already in your decision_queue:
- Cross-check against your trading_rules.py bucket assignment.
- Cross-check exposure_posture: if NEW_ENTRY_ALLOWED → consider as
  pending CSP/CC; if REDUCE_ONLY → propose as watching with explicit
  re-entry trigger; if CASH_PRIORITY → still mention top 2 candidates
  in the redteam_summary as "what we're watching for when conditions
  loosen."

Per-WSR-run minimum: at least ONE new CSP or CC candidate must be
proposed (or explicitly skipped with a reason). The brain has been
limiting itself to refreshing existing positions — this rule forces
fresh option-strategy proposals.

**Risk Parity LITE hygiene check (NEW, REQUIRED):**

Read the latest `risk_parity_audit` rows for both accounts (16 rows
total, 8 asset classes × 2 accounts). Surface in your synthesis:

- Cite the TOP 2 OVERWEIGHT asset classes per account (delta > 5pp,
  most positive deltas first) in `redteam_summary` as concentration
  risk. Use the format:
  "Caspar concentration: equity_us_dividend +37pp ($2,793 over target —
   SCHD 42% of NLV alone)."

- Cite the TOP 2 UNDERWEIGHT asset classes per account (delta < -5pp,
  most negative deltas first) in `action_summary`. These are
  diversification gaps the wheel strategy is hiding. Format:
  "Caspar gap: bond_long 0% vs 15% target (-$1,118 starter add)."

**HARD RULE — Underweight class proposal quota:**

For each account, at least ONE proposed entry per WSR run must be
in an UNDERWEIGHT asset class — preferably the most underweight one.
This is the "Risk Parity LITE quota."

Allowed forms:
- Stock BUY_DIP in the underweight class (e.g. TLT 5sh starter)
- CSP/CC on a ticker in the underweight class
- An aggressive-watch entry with explicit re-entry trigger if regime
  blocks new entries

The `risk_parity_recommend` script auto-generates specific
`decision_queue` rows with `source="risk_parity"` for every
underweight class. When you synthesize the WSR, READ those
auto-generated rows first and:
- Confirm or refine the conviction (you may upgrade/downgrade by 1)
- Refine the thesis prose to be more precise
- Cross-check against your current TV signals + regime view
- The "REQUIRED at least one underweight-class proposal" rule is now
  AUTOMATICALLY satisfied — you just need to validate (or override
  with a kill reason) the auto-generated rows.

If you genuinely cannot propose anything in any underweight class for
a given account (e.g. all classes have no good candidate this week),
you MUST emit a row with `status: watching`, `bucket: <underweight_class>`,
`thesis: "Risk-parity quota waived — no quality candidate in <class>
this week. Re-evaluate next WSR."` This is the explicit-skip path.

**Sizing guidance:**

The audit's `rebalance_amount_usd` column is the THEORETICAL full-fill
to hit target. Don't propose that full amount in one shot. Use it as
a UPPER BOUND. Propose 25-50% of that as a starter position — leaves
room to scale into the position if regime confirms.

**Allocation > stock-picking:**

When asset class A is underweight by 15pp and asset class B is
underweight by 3pp, prefer a candidate in A even if the B candidate
looks like a "better" stock. Diversification beats stock-picking when
correlation is the problem. Risk parity is a correlation/concentration
check, not a return-maximizer.

**Update `regime_anchor` JSON to include risk parity status:**

Add this field to your `regime_anchor` object:
"risk_parity": {
  "caspar_top_overweight": "equity_us_dividend +37pp",
  "caspar_top_underweight": "bond_long -15pp",
  "sarah_top_overweight": "equity_us +30pp",
  "sarah_top_underweight": "bond_long -12pp"
}

This forces an explicit read during Sonnet's format step.

**Universe expansion (forced):** before synthesizing, sweep the
watchlist categories from `prompts/watchlist.yaml` that match the
current regime:
- Defensive regime (CASH_PRIORITY / REDUCE_ONLY) → defensive_etfs +
  commodity + volatility + blue_chip_dividend
- Neutral regime → all categories
- Bullish regime → +speculative_growth +high_iv_wheel_targets

For each ticker in the relevant categories with daily TV BUY signal
NOT in your decision_queue, evaluate as a potential new entry. Don't
silently skip — at minimum mention 2-3 names you considered and
explain why you didn't propose them (e.g. "Considered XLV (defensive
ETF) — daily NEUTRAL on TV, weekly BUY but exposure ceiling at 50%
already; will revisit if posture loosens"). This is the user's
explicit instruction — the brain previously vibes-limited itself to
~28 tickers (held + decision_queue) and missed defensive/spec
opportunities outside the existing book.

**Strategy-class signals (for awareness, not auto-execution):** when the named pattern is observed, propose appropriately. The user has these skills available; you don't run them but you can reference them in thesis text:
- **Breakout entry** (`breakout-trade-planner` style): tight handle, low-volume contraction, breakout on > 1.5x volume → propose `BUY_DIP` near pivot
- **PEAD setup** (`pead-screener` style): post-earnings gap > 5% with high volume → propose `BUY_DIP` near closing day-of-print price
- **Earnings analyzer**: 5-factor scoring (gap size, volume, sector strength, fundamental quality, technical setup) → cite if you use it in a thesis
- **Pair trade** (`pair-trade-screener`): only relevant if you find a high-correlation pair with diverged spreads — propose as a paired action across two decision rows
- **Parabolic short** (`parabolic-short-trade-planner`): vertical move > 50% in 30 days, RSI > 80, exhaustion candle → DO NOT propose as a long, but flag in `redteam_summary` if you see this pattern in a name we hold
- **Position sizer**: when proposing a new entry, reference your sizing logic ("4% of NLV at $X stop = N shares")

**Defensive Expansion (REQUIRED — regardless of regime):**

Even in CASH_PRIORITY / REDUCE_ONLY regimes, the brain MUST propose a
minimum of 3-5 DEFENSIVE expansion ideas. These are positions APPROPRIATE
FOR the current regime — not "ignore the regime and add risk." Examples
that fit a defensive regime:

- **Protective puts** on held positions (long puts on TQQQ, SSO if
  the user holds them; AAPL/AMD if held)
- **Gold/silver** — GLD, SLV, GDX as Concentration-regime hedges
- **Defensive sector ETFs** — XLP, XLV, XLU
- **Volatility products** — VIXM (NOT VIX spot), small allocation
- **Quality dividend names** — KO, JNJ, PG at oversold RSI
- **CSPs on quality at deep OTM** — collect premium without commitment

Each defensive expansion proposal MUST include:
- Why it fits the current regime (cite breadth/distribution_day/macro
  signals explicitly)
- Position sizing within exposure ceiling (suggest ≤1% NLV for new
  defensive entries when exposure is constrained)
- Specific entry trigger and stop level

If you cannot find 3 defensive expansions, you must explicitly explain
WHY (e.g., "all defensive sectors are themselves overbought").

**Aggressive Watch Lane (parallel pipeline):**

Ideas that FAIL the current regime gates but are otherwise high-quality
should not be silently dropped. Capture them in an "aggressive watch"
queue with explicit re-entry triggers. Emit them as decision_queue rows
with `status: "watching"` and a clear trigger condition in the thesis.

Format:
```
"AMZN BUY_DIP @ $215 — currently failing breadth gate (33/100 < 50).
Re-evaluate when breadth_score ≥ 50 AND (daily TV ≥ BUY OR distribution
days drop below SEVERE). Current setup: post-earnings flag, 50% retrace
of November rally."
```

Per-WSR run: at least 2-3 aggressive watch entries. These represent
"things we'd act on in a different regime" — preserves the brain's
creative output and gives the user a list to monitor for regime change.

Aggressive watch entries are EXPLICITLY DIFFERENT from your defensive
expansions — they fail the current gate. The PWA Decisions tab will
show them in the watching section with the trigger explicit.

**Minimum Idea Quota (per-WSR-run REQUIRED):**

Each WSR Full run MUST produce:
- ≥4 NEW decision rows (status: pending OR watching) NOT in the existing
  queue (i.e. fresh additions, not refreshes of existing positions)
- Of those 4+: ≥1 new CSP or CC candidate (from options_yield_candidates
  if available, else from your own analysis)
- Of those 4+: ≥1 defensive expansion idea (per the rule above)
- Of those 4+: ≥1 aggressive watch entry (per the rule above)

If the brain genuinely cannot meet the quota, it must include in
`redteam_summary` an explicit explanation of WHY no fresh ideas are
available — citing specific gates (breadth, exposure, TV signals)
that blocked each candidate considered.

This rule prevents the brain from defaulting to "refresh existing
positions only" mode. Even in tight regimes, fresh ideas should
flow — they just go to the right queue (defensive expansion, watching
with trigger, etc.).

**Week lookback:** Each daily brief contributed something. What were the events Mon-Fri? What positions were affected?

**Thesis drift flags:** For each position with a stated thesis, did this week confirm or break it? Flag any thesis still active but unresolved.

**Technical landscape:** SMA/RSI/MACD for ~15-20 key tickers (positions + queue + watchlist).

**Red-team flags:** 5-8 flags challenging current posture. Each tagged with confidence.

**Decision queue (top 5):** Re-rank vs last week. Note promotions/demotions. Mark which are ACTIONABLE vs WATCH.

**Actionable entries:** For each "BUY ON PULLBACK" name, give entry/target/stop/catalysts.

**For Caspar / For Sarah:** Per-account snapshot, performance, options scan, action plan, watch triggers.

**Regime anchor (REQUIRED top-level JSON field):** Always emit a `regime_anchor` object at top level of the synthesis JSON so Sonnet can surface it explicitly during the format step:

```json
{
  ...
  "regime_anchor": {
    "breadth_score": 33,
    "distribution_label": "CAUTION",
    "ftd_label": "NO_SIGNAL",
    "macro_regime": "Concentration",
    "exposure_ceiling": 50,
    "exposure_recommendation": "REDUCE_ONLY",
    "risk_parity": {
      "caspar_top_overweight": "equity_us_dividend +37pp",
      "caspar_top_underweight": "bond_long -15pp",
      "sarah_top_overweight": "equity_us +30pp",
      "sarah_top_underweight": "bond_long -12pp"
    }
  }
}
```

Pull each field from the latest `regime_signals`, `exposure_posture`, and `risk_parity_audit` rows. If a source hasn't reported (sheet empty or cron not yet run), emit `null` for that field — Sonnet renders "—" for nulls. The `risk_parity` sub-object is the diversification hygiene summary: per account, the `top_overweight` and `top_underweight` are formatted `"<asset_class> <signed_delta>pp"` strings pulled from the audit's max +delta_pct and min -delta_pct rows.

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
      "source":            "wsr_full",
      "qty":               100,
      "accumulation_plan": "33sh now | 33sh in 30d | 34sh on -5% pullback to $79.80",
      "gates":             ["exposure:NEW_ENTRY_ALLOWED"]
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
      "source":            "wsr_full",
      "qty":               3,
      "accumulation_plan": "1 CSP @ $250P 35DTE now | 1 CSP @ $245P if AAPL pulls to $255 | 1 CSP +14d at next expiry if IV stays >25",
      "gates":             ["exposure:NEW_ENTRY_ALLOWED", "tv_daily:BUY", "earnings_clear"]
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

**🟢 ACCUMULATION-PLAN RULE (every entry — non-negotiable)**: EVERY
recommendation (share OR option) MUST carry both `qty` (total planned
shares-or-contracts as integer) AND `accumulation_plan` (pipe-separated
tranche string). The plan answers two questions explicitly: **how much
to deploy total** and **how to phase the deployment**. You may NOT emit
ANY rec with `qty: 0` or empty `accumulation_plan` — if you can't
specify size and timing, the rec doesn't belong in the queue.

**🟢 GATES RULE (every WATCHING entry — non-negotiable)**: When a row's
`status` is `"watching"`, you MUST emit a `gates` array enumerating
EVERY precondition that must clear before the trigger fires. The PWA's
TriggerBadge reads this list verbatim — leave anything out and the
"ACT NOW" pill will fire prematurely. Format: array of `"<type>:<value>"`
strings. Recognised types:

  - `"exposure:NEW_ENTRY_ALLOWED"` — block until exposure_posture clears the cash-priority gate
  - `"tv_daily:BUY"` — block until TV 1d consensus is BUY or STRONG_BUY (same for `tv_weekly:BUY`)
  - `"tv_daily:SELL"` — for TRIM/CC entries — block until TV 1d flips bearish
  - `"earnings_clear"` — informational marker that you've already filtered DTE conflicts (no further check)

For PENDING / FILLED / KILLED rows, leave `gates` as an empty array `[]`
(the queue uses these only for `watching` rows). For unconditional
"act-immediately" recs, also emit `[]`.

Tranche format — pipe-separated segments. Use the right unit per strategy:
- **Share strategies (BUY_DIP / TRIM)**: `<N>sh <when>`
  - Calendar: `5sh now`, `5sh in 30d`, `5sh in 60d`
  - Conditional: `5sh on -5% pullback to $79.20`, `5sh on TV daily=BUY confirm`, `5sh on NEW_ENTRY_ALLOWED`
  - Combined: `5sh in 60d or on -5% to $79.20`
  - Watching/CASH_PRIORITY equity: `0sh now (watching) | Nsh on NEW_ENTRY_ALLOWED at $X | Nsh +30d after T2 fills`
  - Single tranche (qty<3): `2sh now`
- **Option strategies (CSP / CC / PMCC / LONG_CALL / LONG_PUT)**: `<N> <strategy> @ $<strike><right> <DTE>DTE <when>`
  - Single contract: `1 CSP @ $250P 35DTE now`
  - Laddered by spot: `1 CSP @ $250P 35DTE now | 1 CSP @ $245P if AAPL -2% to $255`
  - Laddered by time: `1 CC @ $90C 30DTE now | 1 CC +30d at next expiry if T1 expires worthless`
  - Laddered by IV: `1 CSP now | 1 CSP +14d if IV stays >25`
  - Wheel-stacking when shares-on-hand allow N CCs: `2 CCs @ $32C 30DTE now` (deploy max immediately if conviction high)

Tranche philosophy:
- **Shares — conv 4-5 + defensive class (bond/gold/vol)**: front-load 50/30/20 — hedge can't wait
- **Shares — conv 4-5 + growth class**: balanced 33/33/34
- **Shares — conv 3**: 33% now / 33% on confirm / 34% +60d or -5%
- **Shares — conv 1-2**: toehold 25% / 50% on confirm / 25% on -8%
- **Shares — status=watching (CASH_PRIORITY equity)**: `0sh now` first, then conditional triggers
- **Options — conv 4-5**: deploy 50% now, ladder remainder on spot/time/IV triggers
- **Options — conv 3**: deploy 33% now, ladder on confirmation
- **Options — conv 1-2**: 1 contract now (toehold), wait for confirmation before adding
- **Options — status=filled** (already-held position being refreshed mid-week): keep `qty` = current contract count, plan = "FILLED — current ladder" or describe what to do at expiry

NEVER set `qty: 1, accumulation_plan: ""` on a multi-contract opportunity
— if conviction is high and the user has the cash/shares to write 2-3
contracts, ladder them. The default for low-conviction options is `qty:
1, accumulation_plan: "1 contract now"` (single tranche).

**Milestone-reached share positions** (e.g. SCHD already at 100sh target,
BTC core position at full size): If you're tracking a held share position
to flag the next DCA pulse, set `qty` = NEXT-tranche size (not the held
size, not zero), `status` = `watching`, and the plan describes the held
position FIRST then the next tranche conditions. Example:
`"qty": 10, "accumulation_plan": "100sh @ $29.40 FILLED (milestone reached) | 10sh on SCHD <$31 OR scheduled monthly DCA"`.
NEVER emit `qty: ""` (empty) on a share row — every share rec has a
quantifiable next action even if it's "0sh now (waiting on regime)".

**Status values:** `pending` (live entry, ready to act), `watching` (price
not yet in zone), `filled` (already executed), `killed` (thesis broken),
`expired` (DTE elapsed without action).

The unified queue now mixes 4 row types (use `status` to differentiate):
- `pending` — actionable this week, fits exposure budget
- `watching` — aggressive watch (trigger condition in thesis) OR
  share entry awaiting price (existing meaning)
- `filled` — held position, brain's mid-period thesis update
- `killed` / `expired` — historical; don't re-emit unless re-validating

Defensive expansions go in `pending` if they fit ≤1% NLV cap, or
`watching` if exposure is too tight even for that.

**Strategy values:** `BUY_DIP` (share entry on pullback), `TRIM` (share
exit), `CSP`, `CC`, `PMCC`, `LONG_CALL`, `LONG_PUT`. For share entries:
use `""` (empty string) for `right` and `expiry`, and 0 for `strike` /
premium / delta / yield / breakeven / iv_rank. Always populate ALL
fields — use 0 / "" for inapplicable ones, never omit a key.

**🔴 PRICE-ANCHOR RULE (non-negotiable)**: Every `thesis_1liner` you
emit MUST reference the **CURRENT** underlying price, not last week's.
Read it from `positions_caspar` / `positions_sarah` `last` column for
held tickers, or from `scan_results` / `technical_scores` `close` for
unheld watchlist tickers. **DO NOT copy thesis prose verbatim from
the previous week's row.** Re-anchor the dollar reference each run.

If the current price has moved by >2% vs your prior thesis:
- Update the in-thesis price reference AND re-evaluate viability.
- If price moved past the implied stop level (typically entry × 0.95
  for shares; entry × 0.92 for blue-chip), flip `status` to `killed`
  with a reason in the thesis ("stop breached at $X — original entry
  $Y, was $Z one week ago").
- If price moved further INTO the entry zone (lower is better for a
  BUY_DIP, up to stop), flag thesis as STILL VALID and stronger.
- If price ran past entry (upside breakout), flip `status` to
  `watching` or `killed` per the rule docs.

Each Sunday, you are NOT just refreshing the same theses — you are
RE-COMMITTING each one at today's price, OR flagging which prices have
invalidated which theses. The PWA Decisions tab also shows a live-price
overlay and "as of N days ago" chip per row, so users can see staleness
even if your prose lags. But the prose should not lag.

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

**🔴 ACCOUNT-CAPITAL CHECK (non-negotiable, applies to every option entry):**

Before emitting ANY option recommendation (CSP/CC/PMCC/LONG_CALL/LONG_PUT),
calculate `cash_required` against the **target account's** NLV:
- caspar NLV is in USD (read latest `snapshot_caspar.net_liq_usd`).
- sarah NLV is in SGD (read latest `snapshot_sarah.net_liq_sgd`); convert
  to USD using `usd_sgd` from latest `macro` row before comparing.

For CSPs: `cash_required = strike × 100 × num_contracts` (USD).
For CCs: `cash_required = 0` (covered by held shares — but verify shares
are actually held in the target account first).
For LONG_CALL/LONG_PUT: `cash_required = premium × 100 × num_contracts`.

**Hard rule:**
- If `cash_required > 50% of target NLV (USD)`: re-evaluate. Either
  (a) re-allocate to the OTHER account if it has capital, (b) reduce
  contract count / pick a lower strike, or (c) skip the rec.
- If `cash_required > 80% of target NLV`: NEVER emit — skip the rec
  entirely. No high-conviction thesis justifies betting the whole
  account on one trade.
- If a name is too big for both accounts (e.g. NVDA $190P at $19k
  collateral when caspar=$7k and sarah-headroom is exhausted): skip
  the CSP, propose alternatives (e.g. cheaper-strike CSP that fits,
  or LONG_CALL with smaller premium outlay).

Cite the sizing math in `thesis`: e.g. "Cash $19k on sarah NLV $46k
(40% allocation) — fits 50% cap; caspar's $7.5k NLV cannot."

**🔴 EXPOSURE CONSTRAINT (graduated):**

Read the latest `exposure_posture` row before proposing any decisions.

- `CASH_PRIORITY` → No `pending` BUY_DIPs/CSPs that ADD net long
  exposure. EXCEPTION: defensive positions (puts, gold, defensive
  sectors, volatility hedges) capped at ≤1% NLV per position with
  explicit hedge thesis.
- `REDUCE_ONLY` → Maximum 2 new `pending` entries per WSR run; both
  must be high-conviction (conv ≥ 4) AND high quality (passes TV
  multi-TF confluence).
- `NEW_ENTRY_ALLOWED` → No cap, but exposure_ceiling must be
  respected when sizing.

Aggressive watch entries (status: watching) are NOT subject to the
exposure constraint — they don't allocate capital until triggered.
This is the safety valve that lets creative output flow even when
exposure is tight.

Always cite the exposure ceiling in your `thesis_1liner` for any
pending row, e.g. "ceiling 65%, headroom +$1,200 — fits within
REDUCE_ONLY for trim".

**PMCC nudge:** If a position holds (or could buy) a deep-ITM 6+ month
call on a quality name with low IV rank, consider proposing a PMCC over
a naked CSP for capital efficiency. Use `strategy: "PMCC"` with the
long-call leg's strike.

**🔴 EARNINGS-IN-DTE CHECK (non-negotiable for option recs):**

Before emitting any CSP/CC/PMCC, look up the ticker in
`earnings_calendar`. If the next earnings date falls INSIDE the option's
DTE window (entry → expiry), one of two paths:

- **Skip the trade** (default). Earnings IV crush works against CSPs;
  earnings gaps work against CCs. The risk-adjusted yield isn't worth
  the gamma exposure.
- **Accept the risk explicitly** — only when (a) IV rank > 60 (juicy
  premium compensates for gamma), (b) you cite the earnings date in
  the thesis, AND (c) you set `thesis_confidence` ≤ 0.5. Brain must
  EXPLAIN why this earnings setup is worth taking.

Cite earnings status in thesis: "ER 5/20 AMC inside DTE — accepted
because IV rank 68, AAPL 22% OTM provides cushion."

For BUY_DIP share recs: earnings inside the next 5 days = WAIT signal
unless thesis is "buying the post-earnings dip" with explicit dip
trigger. Pre-earnings adds are reckless.

**🔴 INSIDER-FLOW CONFIRMATION (soft rule, pre WSR):**

Before adding a NEW high-conviction (conv ≥ 4) BUY_DIP, check
`insider_transactions` for the ticker over the last 7 days:
- Net side=buy >$1M last 7d → bullish confirm; ok to elevate conv
- Net side=sell >$5M last 7d → yellow flag; downgrade conv by 1 OR
  cite the selling in the thesis as "insider pressure offset by [X]"
- No insider activity → neutral, no impact

Aggregate by name × side over 7d window. The brain reads
`insider_transactions` and sums signed `value_usd` to get the net flow.

**🔴 NEWS-SENTIMENT FILTER (soft rule, pre WSR):**

Before proposing a BUY_DIP for a name with sentiment_score ≤ -0.5 in
`news_sentiment` over last 14 days:
- Read the headline + summary YOURSELF (don't trust the heuristic
  score blindly — Opus is better at semantic context)
- If the negative news is corporate stress (lawsuit/recall/layoffs/
  bankruptcy), SKIP the rec
- If it's market-wide noise that the heuristic misclassified, proceed
  but cite "headline sentiment was misclassified — actual context is X"
- If it's a one-time earnings miss already priced in, ok to proceed
  with downgraded conv

**🔴 ANALYST-CONSENSUS ANCHOR (informational, every Decision):**

Pull the ticker from `analyst_consensus`. Cite the distribution in the
`thesis_1liner` for share BUY_DIP recs:
- "Wall St 42-buy / 4-hold / 1-sell consensus BUY"
- If our conviction DIVERGES from consensus (we're conv=5 BUY but Wall
  St is HOLD), explain WHY the brain disagrees — that's a stronger
  thesis than just following consensus.

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
