# Market-Microstructure Signals: GEX / Volume Profile / CVD — Research & Decision

**Date:** 2026-06-01
**Question:** Should FinancePWA incorporate gamma exposure (GEX), volume profile
(POC/VAH/VAL/HVN/LVN), and cumulative volume delta (CVD) — for vol-regime
sizing, objective levels, and entry-timing / fake-breakout filtering?

**Verdict (Synthesis, 0.82):** Build **GEX** (done — see below). Volume profile is
a **lightweight, low-priority** add. **CVD is rejected.** None of the three change
the structural "won't beat SPY by stacking signals" conclusion — they are
entry-quality / risk-sizing refinements, not alpha.

---

## The meta-point (the decisive frame)

GEX, VP, and CVD are **intraday discretionary day-trader tools.** FinancePWA is a
**daily-batch, automated, swing/income** system (GitHub Actions cron, Sheets-backed,
options-income + momentum). The real question isn't "are they good indicators" —
it's "which survives translation into a once-a-day, code-driven, premium-selling
system." Only GEX cleanly does.

| Tool | Evidence | Fits cron/swing system | Data we can get | Verdict |
|---|---|---|---|---|
| **GEX** | Academic (Gamma Fragility) | Yes — EOD positioning is stable | **Yes — CBOE delayed quotes (free, has OI)** | **BUILT** |
| **Volume Profile** | Soft / discretionary | Yes — daily levels | Yes (Finnhub intraday bars) | Lightweight / deferred |
| **CVD** | Vendor blogs only | **No — intraday/real-time** | **No — needs tick data, local-only** | **Skip** |

---

## 1. GEX — Gamma Exposure (BUILT)

**Evidence (Fact / Judgement 0.8):** Barbon & Buraschi (2021), *Gamma Fragility*
(SSRN 3725454) — aggregate dealer gamma imbalances link to intraday momentum vs.
reversal. Mechanism matches the user's framing exactly:
- **Dealers long gamma** (positive GEX) → hedge *against* moves → vol suppressed → **chop/pin**.
- **Dealers short gamma** (negative GEX, below "gamma flip") → hedge *with* moves → vol amplified → **trend/squeeze**.

**Why it fits OUR strategy (not the generic reason):** Caspar is a **premium
seller** (CSP/CC/credit spreads). Positive-GEX regime = vol suppressed, price pins
inside the short strikes, theta decays cleanly = **when to sell premium**.
Negative-GEX = gap risk straight through the short strikes = **when to stand down.**
GEX is a direct **risk gate on the core income engine**, plus call-wall/put-wall
context for the momentum buys ("don't buy calls into the call wall").

**The data lesson that nearly killed it (Fact):** GEX is *defined* by open
interest. **yfinance returns `openInterest = 0` for every SPY/QQQ strike** —
silently breaks any GEX calc. Fix: **CBOE delayed-quotes JSON**
(`cdn.cboe.com/api/global/delayed_quotes/options/{SYM}.json`) — free, no key, and
the rare source carrying real OI + per-option greeks. ATM IV is a decimal (~0.075).
This is now the data source; it's also the more robust source if GEX ever extends
to single names.

**Boundary (Judgement, 0.8):** GEX signal lives in **index/ETF + high-OI mega-caps**
(SPY/QQQ). Small-cap momentum picks (RKLB etc.) have thin OI → GEX is noise there.

**What shipped (commit 0593513):**
- `src/gex.py` — pure math: signed dealer dollar-gamma (calls +, puts −), net/gross
  GEX, gamma-flip via spot-grid recompute, call/put walls, scale-free regime
  classifier (POSITIVE_PINNED / NEGATIVE_TREND / NEUTRAL), premium_gate
  (SELL_OK / SELL_CAUTION / NORMAL). 8 unit tests.
- `scripts/gex_regime.py` — SPY/QQQ from CBOE; writes `gex_regime` tab.
- `schema.GexRegimeRow`; `.github/workflows/gex-regime.yml` (13:00 UTC pre-open).
- **Executor gate**: `alpaca_paper_execute` reads SPY `premium_gate` and skips NEW
  credit entries (CSP/CC/PCS/CCS/IC) on SELL_CAUTION days (permissive default).
- PWA: `GexRegimeBanner` on the Options page; Settings run-a-job allowlist entry.
- Live first run: SPY POSITIVE_PINNED +$6.1bn, flip 755, call wall 760 / put wall 757.

## 2. Volume Profile (lightweight / deferred)

Evidence is **soft** — Market/Volume Profile is a *descriptive* framework, not a
validated edge; levels work partly because they're self-fulfilling. Computable from
Finnhub intraday bars as a daily POC/VAH/VAL. Worth a thin "nearest value-area edge"
annotation on existing picks later; **not** worth heavy investment. Not built.

## 3. CVD — Cumulative Volume Delta (REJECTED)

Two hard blockers: (1) **data** — needs tick-level trades classified by aggressor
side; yfinance has none, Finnhub tick data is premium, IBKR `reqTickByTick` is
local/real-time only (unreachable from the cloud cron — same wall as TWS-for-
fundamentals). (2) **timeframe** — CVD is a real-time entry-timing tool; a daily
snapshot throws away the only thing it's good for. Revisit only if a live, local,
intraday execution layer is ever built. Evidence base is vendor blogs, not research.

---

## Standing context this sits inside (prior research verdict)

The earlier strategy audit + research concluded the **multi-engine strategy is
structurally unlikely to beat the S&P** (income caps upside; diversification drags
~1pt/yr for 60/40, ~3pt/yr for permanent puts; momentum doesn't survive retail
costs/taxes; SPIVA: ~90% of pros lose to the S&P over 15yr; CBOE PUT/BXM income
indices lag/tie the S&P). Recommendation was **core-satellite + measure honestly via
the SPY benchmark** (`scripts/paper_benchmark.py`, `paper_benchmark` tab). GEX does
not change this — it improves *when* premium is sold, not whether the book beats SPY.
The honest scoreboard remains the paper-vs-SPY alpha.

---

## Research → live-decision wiring map (audited 2026-06-01)

Verifying the research actually *bites* on buys/actions, not just sits in a doc.

| Research finding | Where it gates a decision | Status |
|---|---|---|
| GEX regime → premium-selling risk | `alpaca_paper_execute` skips NEW credit entries (CSP/CC/PCS/CCS/IC) when SPY `premium_gate == SELL_CAUTION` | wired (executor) |
| GEX regime → real-money awareness | PWA `GexRegimeBanner` on Options page (pre-market) | wired (PWA) |
| Materiality → "will it move the stock?" on OPTION buys | `daily_options_scan` LONG_CALL quality gate scores contract materiality (0-30 vs market cap); only emits at quality >= 40 | already wired |
| Materiality → on MOMENTUM/STOCK buys | `growth_scan.apply_confluence` scales smart-money boost by materiality (HUGE 1.25x / MATERIAL 1.0x / NOTABLE 0.7x / IMMATERIAL 0.4x / blank 0.5x) → executor buys the adjusted top picks | wired 2026-06-01 (was the gap) |
| Smart money SELLING (TRIM) → don't chase | `growth_scan.apply_confluence` VETO on TRIM/SELL | wired |
| "Won't beat SPY" → measure, don't assume | `paper_benchmark` per-position alpha vs SPY | wired |
| Delta/OTM/premium discipline → no junk picks | `daily_options_scan` gates (|delta| 0.15-0.35, OTM <=30%, premium >=$0.30) | wired |
| Growth tilt (diversification drag) → allocation | `risk_parity_targets.yaml` Caspar 74/21/5 | wired |

**Cron pipeline (UTC, all scheduled + dispatchable):**
`02:35 options-scan -> 12:30 growth-scan (Mon/Thu) -> 13:00 gex-regime -> 14:30 EXECUTOR(--execute) -> 21:30 paper-benchmark`; gov-confluence 23:00 (feeds next day), risk-parity 22:45, tail-hedge 23:15 Mon. The 14:30 executor reads same-day option picks + GEX gate + latest growth picks + prior-day confluence.

**Known not-wired (by design / data limits):** per-stock GEX walls (only index GEX; noise on thin chains); volume profile (deferred); CVD (rejected — tick data unreachable in cron).
