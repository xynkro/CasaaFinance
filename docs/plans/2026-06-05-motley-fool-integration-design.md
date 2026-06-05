# Motley Fool Stock Advisor Integration — Design

**Date:** 2026-06-05
**Status:** Approved (all 4 roles)
**Author:** Caspar + Claude

## Goal

Use the user's paid Motley Fool **Stock Advisor** subscription as a high-conviction
*discovery / quality input* to the CasaaFinance systematic engine — **never** as an
auto-execution signal. Same guardrail established this session for macro/news:
**engine input, never auto-signal.**

## Feasibility verdict (empirically established)

Probed three integration paths against the live site:

| Path | Verdict | Why |
|---|---|---|
| Custom server-side MCP (headless scrape) | ❌ Dead | Picks are behind a JS-rendered, login-gated JSON API. No static endpoint; nothing to scrape from a headless server. |
| Custom MCP via cookie-replay | ❌ Overkill | Session cookies expire in days; MF picks change ~monthly. High fragility for ~zero benefit. |
| **Chrome MCP reader (in-session)** | ✅ **Chosen** | Reads the member Scorecard directly from the user's logged-in browser. Proven working 2026-06-05. No password handling, no expiring tokens. |

**Key constraint:** the GitHub Actions crons are headless and cannot read MF. Therefore
MF data is **low-frequency, manually-refreshed** (monthly-ish, in-session) — which exactly
matches MF's cadence (5-year holds, ~1 new rec/month). It does **not** need a cron.

## Data available (confirmed via live read)

**Scorecard** (active recs) per row: `ticker, price, rec_date, team, market_cap,
adj_rec_price, return_since_rec, return_vs_sp, type (Cautious/Moderate/Aggressive), div_rate`.

**Tabs:** Overview · Scorecard · **Foundational Stocks** (the curated 10 core) · Hold Recs ·
**New Recs** · **Rankings** (best-buys-now). Plus a per-stock **Moneyball Superscore** (0–100)
— bonus quality signal, also now live on the user's own holdings (My Stocks populated this session).

## Architecture

```
Chrome MCP reader (in-session, ~monthly)
        │   reads Scorecard + Foundational + New Recs + Rankings
        ▼
  curated_picks  (new Google Sheet tab, service-account write)
        │
        ├── role=core      → daily_plan conviction sleeve (equal-weight, capped)
        ├── role=watchlist → PWA Scanner/Decisions "MF watchlist" (no auto-buy)
        ├── role=overlay   → Options page CSP target list (sell puts at MF entry)
        └── role=reference → PWA "Motley Fool" card (scorecard + Moneyball)
        │
        ▼
  SPY-benchmark tracker  (tag source=motley_fool, measure sleeve vs SPY over time)
```

**One source of truth:** `curated_picks` sheet tab. Everything downstream reads it.
The Chrome-MCP read is the *only* MF-touching step; the rest is pure sheet→engine plumbing
identical to the existing macro_lean / daily_plan pattern.

## Components

### 1. `curated_picks` sheet tab + `CuratedPickRow` schema
Columns: `date, ticker, role, mf_type, rec_date, rec_price, market_cap,
return_since_rec, return_vs_sp, moneyball_score, source, note, updated_at`.
`source="motley_fool"` (future-proofs for other curators). `role ∈ {core, watchlist, overlay, reference}`.

### 2. Refresh path (in-session, manual trigger)
- User: "refresh MF picks" → Claude reads MF via Chrome MCP → runs
  `scripts/ingest_curated_picks.py` which upserts rows to `curated_picks` (service-account auth,
  same gspread+retry helper as the rest of the repo).
- A pick read from *Foundational Stocks* → `role=core`; *New Recs/Rankings* → `role=watchlist`;
  recent Buy within N days & within X% of rec price → also `role=overlay`; every active rec → `role=reference`.

### 3. Role: Core holds (the only role that touches money)
- MF Foundational names become **candidates** in the daily_plan growth satellite.
- **Bounded + equal-weight:** capped at a fixed sleeve (e.g. ≤3 MF names, equal %, inside the
  existing satellite budget — never expands total equity exposure). MF selection is the edge; sizing stays disciplined.
- Tagged `source=motley_fool` for attribution.

### 4. Role: Watchlist (read-only)
- New Recs + Rankings surfaced in the PWA as an "MF watchlist" strip. Research prompt, **zero auto-buy.**

### 5. Role: Options overlay (read-only suggestion)
- Recent MF Buys still near rec price → CSP target list on the Options page:
  "sell a cash-secured put to get paid waiting for MF's entry." Suggestion only; user/`wheel` decides.

### 6. Role: Reference card (read-only)
- PWA "Motley Fool" card: full scorecard, return-vs-S&P, type, Moneyball Superscore. Pure display.

### 7. SPY-benchmark tracker (the accountability layer)
- Every `source=motley_fool` position tracked vs SPY from entry, reusing the `paperBenchmark` pattern.
- **Purpose:** in 12 months, *know* whether the $499/yr earned real alpha — not vibes, not MF's
  marketed "since-2002" framing. Measures the user's actual fills.

## Data flow & error handling
- `curated_picks` stale/empty → all roles degrade gracefully (watchlist/reference render nothing;
  core sleeve falls back to the existing non-MF satellite selection). No hard dependency.
- Freshness guard: rows carry `updated_at`; PWA shows "as of" + greys out if > N weeks old.
- Non-US / unrecognized tickers skipped at ingest (logged, not silently dropped).

## Testing
- Unit: ingest parser (scorecard row → CuratedPickRow, role assignment, overlay eligibility window).
- Unit: daily_plan core-sleeve bounding (never exceeds cap; equal-weight; falls back when empty).
- PWA: tsc + vite build green; card renders null on empty.

## Guardrails (non-negotiable)
1. **Engine input, never auto-signal.** MF never triggers a trade by itself.
2. **Equal-weight, capped.** MF's edge is *selection*, not sizing.
3. **Separate SPY benchmark.** Always measurable vs just-buying-SPY.
4. **Paper only.** Consistent with the rest of the system; no real-money path.

## Explicitly out of scope (YAGNI)
- Headless/cron MF scraping (proven impractical).
- Auto-buying any MF pick.
- Cost-basis/P&L round-tripping back to MF (one-way: MF → engine).
