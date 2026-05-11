# Gov Confluence Strategy — Tweaks #1–#4 Shipped Report

**Date:** 2026-05-11
**Status:** ✅ All 4 tweaks merged to main, pushed to origin
**Plan:** [`2026-05-11-gov-confluence-tweaks-1-4.md`](./2026-05-11-gov-confluence-tweaks-1-4.md)
**Phase 1 base:** [`2026-05-10-gov-spending-confluence-strategy-shipped.md`](./2026-05-10-gov-spending-confluence-strategy-shipped.md)

---

## Commits

```
12fb5b0 feat: Tweak #4 — analyst consensus as 4th confluence vector
316605f feat: Tweak #3 — richer thesis prose (replaces stat-dump format)
0a3f4b5 feat: Tweak #2 — Congress SELL signals → TRIM candidates
03ffd9a feat: Tweak #1 — Congress cluster bonus (+20 for 3+ politicians/30d)
5329311 plan: 4 ROI-ranked tweaks for gov confluence (cluster, sells, prose, analyst)
```

Net change: 440 insertions, 45 deletions across 2 files
(`scripts/screen_gov_confluence.py`, `src/schema.py`).

---

## What changed (per tweak)

### Tweak #1 — Congress cluster bonus (+20)
- New `has_congress_cluster` flag on `TickerStats`, set by walking
  congress_buys for 3+ unique politicians in trailing 30d
- `_score_congress` applies +20 bonus on top of existing
  amount-driven + recency scoring (final clipped to [0, 100])
- Synthetic smoke test: 6 cases pass (no activity → 0, $500K → 50,
  $500K + recent → 70, $500K + recent + cluster → 90, clip at 100,
  cluster-only with small amount → 21)

### Tweak #2 — Congress SELL signals → TRIM candidates
- Three new helpers: `_read_congress_sells`, `_read_held_tickers`,
  `_append_sell_signals_to_queue`
- TRIM rows emit to `decision_queue` with `source=gov_confluence_sell`,
  `bucket=GOV_CONFLUENCE_TRIM`, `strategy=TRIM`, `conv=2`, status `watching`
- Conservative gate: 2+ politicians OR $500K+ midpoint AND ticker held
- `--dry` mode now prints would-emit TRIM candidates
- First dry run found 2 real candidates: AAPL and NVDA (each: 2
  politicians selling within 30d, small dollar amounts but cluster
  pattern is the signal). Brain reviews in next-morning daily brief.

### Tweak #3 — Richer thesis prose
- `_build_thesis` rewritten as 2–3 sentence WSJ/Bloomberg-style prose
  mirroring QuiverQuant's ChatGPT-Enhanced format
- `_build_action_text` retightened to subject-line format (with score),
  distinct from thesis prose
- Three synthetic profiles verified: AVAV (single contract + all
  signals), LMT (stacked contracts only), NVDA (pure Congress play)

**Before** (stat dump):
```
Contract 80 · Congress 60 · Insider 30 (multi-yr IDIQ, fresh award <7d, Congress <14d)
```

**After** (prose):
```
Captured a $35.0M multi-year IDIQ in a top federal-spending sector in the
last 7 days. Aligned 3 Congress buys from 3+ distinct members totaling
$0.38M/30d and 1 insider buys worth $0.18M. Score breakdown — contract
80 / congress 60 / insider 30 / analyst 0.
```

### Tweak #4 — Analyst consensus as 4th vector
- Schema bump: `GovConfluenceSignalRow` gains `analyst_score` column
  (backward-compat default 0.0; all subsequent fields now have defaults)
- New constants: `W_CONTRACT=0.35`, `W_CONGRESS=0.25`,
  `W_INSIDER=0.25`, `W_ANALYST=0.15` (sum = 1.00 verified)
- New reader `_read_analyst_consensus` reads the weekly Finnhub
  `analyst_consensus` sheet
- New scorer `_score_analyst`: consensus_score ∈ [1.0, 2.0] maps to
  [50, 100]; below BUY → 0; <5 analysts → ×0.5 dampening
- Thesis prose appends sell-side sentence when ticker has BUY/STRONG_BUY
  with ≥5 analysts
- 8 synthetic cases pass

---

## Behaviour verification

### Pre-flight baseline
```
INFO Computed stats for 48 unique tickers
INFO   · 0 signals scored >= 60
```

Contracts feed not yet populated (Phase 1 cron hasn't fired in
production yet — gov_contracts sheet missing), so BUY-side scores all
zero. Once `fetch_gov_contracts.yml` runs at 06:00 SGT tomorrow,
Tweaks #1, #3, #4 will all show their effects in the next screener run.

### Post-tweak dry run
```
INFO Computed stats for 48 unique tickers
INFO   · 0 signals scored >= 60
INFO [DRY] no writes performed
INFO [DRY] would emit 2 TRIM candidates:
INFO   · AAPL: 2 politicians, $0.02M total
INFO   · NVDA: 2 politicians, $0.04M total
```

Tweak #2 already firing on real Congress sells data.

---

## What's deliberately out of scope (v1.5+)

- **Per-analyst track-record scoring** — true QQ Analyst Buys recipe
  requires individual analyst hit-rates which Finnhub's free tier
  doesn't expose. v1.5 could add this if budget allows.
- **Real shorts** — book is long-only. Tweak #2 captures sell-side
  info as TRIM-on-held only.
- **Portfolio-level allocation cap** (Tweak #5 from the original
  brainstorm) — deferred until v1 shows whether multi-signal weeks
  over-concentrate.
- **House-only weighting** — House L/S had better Sharpe than full
  Congress; could add a `chamber_weight` parameter after the
  CapitolTrades scraper reliably populates chamber field.
- **Lobbying-spend vector** — QQ "Lobbying Spending Growth" had the
  highest CAGR (26.5%); adding LD-2 disclosure ingestion is a
  multi-day project on its own.

---

## Next morning checklist (for Caspar when you wake up)

1. **Confirm the gov_contracts cron has run** — `gh run list
   --workflow=fetch-gov-contracts.yml --limit 3` should show a
   06:00 SGT run from today
2. **Spot-check the screener output** — `python scripts/screen_gov_confluence.py
   --dry | tail -30` should now show non-zero signals
3. **Check `gov_confluence_signals` sheet** — first row of today's
   run should have an `analyst_score` column
4. **Watch the Insider Trading Telegram topic** at ~07:15 SGT for the
   daily digest with new prose thesis
5. **Daily brief at 07:43 SGT** — Multi Day Swing topic should pick
   up the gov_confluence section with the richer thesis lines

If anything looks off, the screener log is at `.state/screen-gov-confluence.log`.
