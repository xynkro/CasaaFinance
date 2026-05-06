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

```python
# Additional regime tabs (Agent 1's regime cron output):
# - regime_signals (LAST 7 DAYS, ALL SOURCES — market_breadth, ftd,
#     distribution_day, macro_regime)
# - exposure_posture (LATEST ROW ONLY — exposure-coach output: ceiling,
#     bias, participation, recommendation, confidence)
# - screen_candidates (LAST 30 DAYS, BOTH SOURCES — vcp + canslim
#     weekly fresh-blood ticker pool)
# - tv_signals (LATEST per ticker, both 1d and 1W intervals — TradingView's
#     26-indicator consensus: STRONG_BUY/BUY/NEUTRAL/SELL/STRONG_SELL plus
#     all underlying indicator values)
```

The `options` tab is refreshed every 30 minutes during US market hours by the cloud `options-refresh.yml` workflow (moneyness, DTE, assignment_risk, trend_risk, momentum_5d, sigma, RSI, SMAs all yfinance-derivable). The latest snapshot is the freshest you'll have, regardless of whether the Mac is on. New positions still get added nightly via Mac ibkr-grab.

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

**Regime classification (quant-anchored, NOT vibes):**

Read the latest `regime_signals` rows for all sources. Use them as PRIMARY regime input. Do NOT vibes-classify regime from price action. Specifically:
- `market_breadth.score` < 50 → bias toward defensive
- `distribution_day.label == "HIGH"` or `"SEVERE"` → regime is contracting
- `ftd.label == "FTD_CONFIRMED"` → regime is recovering
- `macro_regime.label` → use as the regime tag in your synthesis JSON

If signals conflict, default to the more conservative interpretation. Do not override quant signals with vibe.

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

### 4. Synthesize JSON (compact — Sonnet expands later)

Output a JSON matching this schema (pass to Sonnet template at `prompts/sonnet_format_wsr_lite.md`):

```json
{
  "type": "wsr_lite",
  "date": "YYYY-MM-DD",
  "regime": "bull_late_cycle",
  "regime_unchanged": true|false,
  "regime_drift_text": "1-2 paragraphs synthesising the past 2-3 days",
  "regime_anchor": {
    "breadth_score": 33,
    "distribution_label": "CAUTION",
    "ftd_label": "NO_SIGNAL",
    "macro_regime": "Concentration",
    "exposure_ceiling": 50,
    "exposure_recommendation": "REDUCE_ONLY"
  },
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

**`regime_anchor` (REQUIRED top-level field):** Pull each value from the latest `regime_signals` and `exposure_posture` rows. If a source hasn't reported, emit `null` for that field — Sonnet renders "—" for nulls. This forces an explicit read of the quant regime signals during the format step, surfacing them in the rendered markdown.

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

**🔴 PRICE-ANCHOR RULE (non-negotiable)**: Every `thesis_1liner` you
emit MUST reference the **CURRENT** underlying price, not last week's.
Read it from `positions_caspar` / `positions_sarah` `last` column for
held tickers, or from `scan_results` / `technical_scores` `close` for
unheld watchlist tickers. **DO NOT copy thesis prose verbatim from
the previous week's row.** Re-anchor the dollar reference each run.

If the current price has moved by >2% vs your last thesis:
- Update the in-thesis price reference AND re-evaluate viability.
- If price moved past the implied stop level (typically entry × 0.95
  for shares; entry × 0.92 for blue-chip), flip `status` to `killed`
  with a reason in the thesis ("stop breached at $X — original entry
  $Y, was $Z").
- If price moved further INTO the entry zone (i.e. for a BUY_DIP, lower
  is better up to the stop), flag thesis as STILL VALID and stronger
  (better entry now).
- If price moved AWAY from the entry zone (e.g. ran past entry to the
  upside), flip `status` to `watching` or `killed` per the rule docs.

The cleanest mental model: every Wed/Fri, you are NOT just refreshing
the same thesis — you are RE-COMMITTING to it at today's price, OR
flagging that today's price has invalidated it.

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

**🔴 EXPOSURE CONSTRAINT RULE (non-negotiable):**

Read the latest `exposure_posture` row before proposing any decisions.

- If `recommendation == "CASH_PRIORITY"`: do NOT propose any new BUY_DIP / TRIM-up / CSP / CC entries with `status: pending`. All new candidates must be `status: watching` with explicit re-entry condition (e.g. "watching for posture ≥ NEW_ENTRY_ALLOWED AND TICKER ≤ entry").
- If `recommendation == "REDUCE_ONLY"`: do NOT propose new BUY_DIPs. You MAY propose TRIM (status pending) on existing positions over target. CSP/CC defenses on held positions still allowed.
- If `recommendation == "NEW_ENTRY_ALLOWED"`: standard rules apply.
- Always cite the exposure ceiling in your `thesis_1liner` for any pending row, e.g. "ceiling 65%, headroom +$1,200 — fits within REDUCE_ONLY for trim".

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
