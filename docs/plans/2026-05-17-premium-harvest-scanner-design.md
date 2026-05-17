# Premium Harvest Scanner + Insider Tab + PWA Expansion

**Date:** 2026-05-17
**Status:** Approved

## Problem

The existing `daily_options_scan.py` only scans tickers already in the portfolio or decision queue. High-IV premium opportunities (BMNR, CRWV, AAOI, COPX, SLV) that expire worthless for disciplined sellers never surface. Meanwhile, `market_scan.py` emits duplicate CSP+CC rows for the same ticker instead of merging them into a strangle/IC.

Gov confluence data (CapitolTrades, USGOVSpend, SEC Form 4) exists in the backend but has no dedicated PWA tab — it's buried as icons inside Decisions.

## Solution Overview

1. **`premium_harvest_scan.py`** — new standalone 3-layer scanner: broad high-IV universe → macro+fundamental gate → technical conviction filter. Every candidate carries pre-built entry/maintenance/exit signal blocks.
2. **"Harvest" PWA tab** — surfaces harvest picks with live signal status.
3. **"Insider" PWA tab** — dedicated view for gov confluence, congress trades, insider buys, and per-ticker investment score.
4. **Telegram push** — harvest picks to Options Intel topic; insider digest already on topic 510.
5. **`market_scan.py` dedup fix** — merge CSP+CC on same ticker into SHORT_STRANGLE.

---

## 1. Premium Harvest Scanner (`scripts/premium_harvest_scan.py`)

### 3-Layer Pipeline

```
Layer 1: Universe Discovery
  FinViz free screener (finvizfinance PyPI) → optionable US stocks
  sorted by IV percentile descending → top ~150
    ↓
Layer 2: Macro Gate + Soft Fundamentals
  Kill switches + quality floor → ~60-80 survivors
    ↓
Layer 3: Per-Ticker Technical + Chain Scan
  RSI, SMA, support, option chain → scored + ranked → top ~15-25 picks
    ↓
Output: harvest_scan sheet + PWA Harvest tab + Telegram Options Intel
```

### Layer 1: Universe Discovery

Source: `finvizfinance` Python package (free, no API key). Screen for:
- Optionable stocks (`optionable = True`)
- Market cap > $500M
- Average volume > 500K shares/day
- Price $5–$600 (affordable CSP collateral)
- Option volume > 1,000 contracts/day (liquidity)

Sort by: IV percentile (descending via FinViz "Volatility" sort). Take top 150.

Fallback: if FinViz is unreachable, fall back to a curated high-IV watchlist (~80 tickers including: SLV, GDX, COPX, MSTR, COIN, HOOD, SOFI, AAOI, CRWV, BMNR, MU, AMD, TSLA, PLTR, RIVN, LCID, RKLB, ASTS, OPEN, SNAP, PINS, ROKU, DKNG, PENN, AFRM, UPST, etc.)

### Layer 2: Macro Gate + Soft Fundamentals

**Macro gate (kill switches):**
- VIX > 30 (elevated/crisis regime) → HALT all harvest scanning. Return empty with `macro_halted: true`.
- SPX below 200-day SMA → reduce universe to defensive names only (ETFs: SLV, GLD, GDX, TLT + mega-cap: AAPL, MSFT, GOOGL, JPM, JNJ).
- Macro blackout window (FOMC/CPI/NFP within 2 calendar days) → skip scan, flag `macro_blackout: true`.
- VIX 25-30 → scan but tag all picks as `elevated_caution`, reduce position sizing recommendation by 50%.

**Soft fundamental gate:**
- Market cap < $500M → reject (penny-cap risk)
- No revenue (yfinance `totalRevenue` is None or 0) → reject
- Price < $3 → reject (penny stock)
- No options chain available → reject
- Active delisting/bankruptcy risk → reject (sector = "Financial Services" + negative book value as proxy)

Data source: `yfinance.Ticker(sym).info` for market cap + revenue. Cached per scan run.

### Layer 3: Technical Conviction Filter

For each surviving ticker, fetch 60d daily history via `yfinance` (same pattern as `_technical_context()` in `daily_options_scan.py`):

**Technical gates (all must pass):**
| Gate | Criteria | Rationale |
|------|----------|-----------|
| SMA-50 trend | Price > SMA-50 | Don't sell puts into a downtrend |
| SMA-200 trend | Price > SMA-200 | Major trend intact |
| RSI range | 30 < RSI-14 < 75 | Not crashing (< 30) or blow-off top (> 75) |
| Not falling knife | Price > 20d low × 1.03 | At least 3% above recent low |
| Earnings clear | No earnings within DTE | Avoid binary events |
| Volume health | 20d avg volume > 200K | Sufficient liquidity |

**Conviction score (0-100):**
- Base: 40 points (passed all gates)
- SMA-50 uptrend bonus: +10 (SMA-20 > SMA-50)
- RSI sweet spot (40-60): +10
- Near support (within 5% of 20d low but above it): +10
- IV richness (IV/HV30 > 1.2): +10
- High open interest on target strike (> 200): +5
- Tight bid-ask spread (< 10%): +5
- Gov confluence signal exists for ticker: +10

**Option chain scan (for survivors):**
- Target DTE: 25-45 days (ideal 35)
- Strike: 10-18% OTM (below current price)
- Minimum annual yield: 14%
- Minimum open interest: 50
- Minimum mid-price: $0.08

### Per-Candidate Signal Blocks

Every emitted candidate carries three dicts:

**`entry_signals`:**
```python
{
    "strategy": "HARVEST_CSP",          # or HARVEST_STRANGLE
    "ticker": "AAOI",
    "strike": 105.0,
    "expiry": "20260620",
    "dte": 35,
    "credit": 4.20,
    "annual_yield_pct": 48.0,
    "iv_rank": 68,
    "conviction": 82,
    "sr_context": "near support $98 (7%) · RSI 42",
    "macro_regime": "STANDARD",
    "vix": 18.2,
    "spx_above_200sma": True,
}
```

**`maintenance_signals`:**
```python
{
    "profit_target_pct": 50,            # close when premium decays to 50% of credit
    "profit_target_optional": True,     # can let expire if conviction high
    "time_stop_dte": 21,                # roll forward at 21 DTE
    "strike_tested_pct": 3,             # flag when price within 3% of strike
    "earnings_in_dte": False,           # True → close before announcement
    "macro_shift_exit": True,           # close if VIX crosses 30 or SPX < 200SMA
    "trend_break_exit": True,           # close if price drops below SMA-50
    "sma50_at_entry": 112.5,            # SMA-50 value at scan time
}
```

**`exit_signals`:**
```python
{
    "max_loss_mult": 2.0,               # stop at 2× credit received
    "max_loss_value": 8.40,             # absolute stop value
    "mechanical_close_dte": 14,         # close at 14 DTE regardless
    "assignment_risk_dte": 7,           # flag if ITM + DTE < 7
    "expired_worthless": True,          # the goal — 100% profit
}
```

### CSP+CC → SHORT_STRANGLE Merge

If both a CSP and CC qualify for the same ticker:
- Combine into `HARVEST_STRANGLE` with merged credit
- Maintenance: close untested side if one side tested; 50% combined profit target
- Exit: max loss = 2× combined credit on losing side

### Output

- **Sheet tab:** `harvest_scan` (new tab, schema: `HarvestScanRow`)
- **Telegram:** Options Intel topic via new `ping_harvest_scan()` in `telegram.py`
- **PWA:** consumed by new Harvest page

### Schedule

GitHub Action: daily at 10:40 SGT (5 minutes after `daily_options_scan.py`), Mon-Fri.

---

## 2. Harvest PWA Tab

New page: `pwa/src/pages/HarvestPage.tsx`

### Cards

**Macro Regime Banner:**
- Green: STANDARD (VIX < 20, SPX > 200SMA) → "Harvest active"
- Amber: CAUTION (VIX 20-25 or SPX near 200SMA) → "Harvest active — reduced sizing"
- Red: HALTED (VIX > 25 or SPX < 200SMA or macro blackout) → "Harvest paused"
- Data: latest `macro` row from sheet

**Today's Harvest Picks:**
- Sorted by conviction score descending
- Each row: ticker, strike, DTE, credit, yield, conviction badge
- Expandable: shows full entry/maintenance/exit signal blocks
- Colour: conviction ≥ 75 green, 50-74 amber, < 50 red

**Active Harvests (future):**
- Once positions are opened from harvest picks, track live status
- Requires matching harvest picks to IBKR positions (deferred to Phase 2)

**Harvest History (future):**
- Past picks with outcomes: expired worthless, closed at profit, stopped out, rolled
- Win rate display (deferred to Phase 2)

### Data Flow

`harvest_scan` sheet tab → `fetchTab<HarvestScanRow>("harvest_scan")` in `data.ts` → `HarvestPage.tsx`

---

## 3. Insider PWA Tab

New page: `pwa/src/pages/InsiderPage.tsx`

### Cards

**Gov Confluence Top Picks:**
- Today's `gov_confluence_signals` with score ≥ 60
- Show 4-factor breakdown: contract (40%), insider (30%), congress (15%), analyst (15%)
- Tier badge: A (score ≥ 90), B (70-89), C (60-69)
- Recommended strategy: BUY_DIP / LONG_CALL / PMCC
- Thesis one-liner from `screen_gov_confluence.py`

**Recent Congress Trades:**
- Latest from `congress_trades` sheet (last 7 days)
- Columns: politician, party, ticker, type (buy/sell), amount range, filed date, traded date
- Link to CapitolTrades source

**Recent Insider Buys:**
- From `insider_transactions` sheet (last 14 days, buys only)
- Cluster detection: multiple insiders buying same ticker = strong signal
- Aggregate buy value vs sell value per ticker

**Investment Score:**
- Per-ticker composite (0-100):
  - Confluence component (40%): gov_confluence_signals score (0-100 → 0-40)
  - Fundamental component (30%): revenue growth + profit margin + debt/equity via yfinance
  - Technical component (30%): RSI health + SMA trend + momentum
- Colour-coded: ≥ 75 green (worthy), 50-74 amber (watchlist), < 50 red (avoid)
- This is computed by `screen_gov_confluence.py` and stored as a new field

### Data Flow

Existing sheet tabs (`gov_confluence_signals`, `congress_trades`, `insider_transactions`) already fetched in `data.ts`. Just need to wire them to the new page instead of only feeding Decision card badges.

---

## 4. Telegram Push

### Harvest Picks → Options Intel (topic 492)

New function: `ping_harvest_scan()` in `telegram.py`

Format:
```
🌾 PREMIUM HARVEST · {date}
Macro: {regime_emoji} {regime} (VIX {vix} · SPX {spx_status})
{n} candidates found

💰 HARVEST_CSP ({count})
  ${ticker} ${strike}P {expiry} ({dte}d) · ${credit} cr · {yield}% ann · IVR≈{ivr} · Conv {conv}
    📋 50% profit · 21DTE roll · stop 2×(${stop})
    🛑 {exit_notes}

🔀 HARVEST_STRANGLE ({count}) — CSP+CC combined
  ${ticker} ${put_strike}P/${call_strike}C {expiry} ({dte}d) · ${combined_credit} cr
    📋 close untested if tested · 50% profit
    🛑 max loss ${max_loss} per side
```

Caps: 8 picks max per message. Footer links to PWA Harvest tab.

### Insider Digest → Insider Trading (topic 510)

Already built in `insider_pulse_digest.py`. Enhancement: append investment score to each confluence pick in the digest.

---

## 5. Bug Fix: `market_scan.py` CSP+CC Dedup

In `screen_ticker()`, after scanning both CSP and CC:

```python
# If both CSP and CC found for same ticker → merge into SHORT_STRANGLE
if len(recs) == 2 and recs[0]["strategy"] == "CSP" and recs[1]["strategy"] == "CC":
    put_rec, call_rec = recs[0], recs[1]
    combined_credit = put_rec["premium_per_share"] + call_rec["premium_per_share"]
    recs = [{
        **put_rec,
        "strategy": "SHORT_STRANGLE",
        "right": "P+C",
        "premium_per_share": round(combined_credit, 2),
        "annual_yield_pct": round(combined_credit / put_rec["strike"] * (365 / put_rec["dte"]) * 100, 1),
        "notes": f"Put ${put_rec['strike']:.0f} + Call ${call_rec['strike']:.0f}",
        "call_strike": call_rec["strike"],
    }]
```

Also update `daily_options_scan.py` `MAX_PER_TICKER` logic: if both CSP and CC qualify, emit one combined row tagged as IC/strangle instead of two separate rows.

---

## Dependencies

- `finvizfinance` PyPI package (free, no API key) — for Layer 1 universe discovery
- All other data from `yfinance` (already a dependency)
- No new secrets or API keys required

## Schedule Summary

| Script | Schedule (SGT) | Output |
|--------|----------------|--------|
| `fetch_gov_contracts.py` | 06:00 | gov_contracts sheet |
| `fetch_congress_trades.py` | 06:30 | congress_trades sheet |
| `screen_gov_confluence.py` | 07:00 | gov_confluence_signals + decision_queue |
| `daily_options_scan.py` | 10:35 | scan_results sheet |
| `premium_harvest_scan.py` | 10:40 | harvest_scan sheet |
| `insider_pulse_digest.py` | 07:15 | Telegram Insider topic |
| `daily_tracker.py` | 11:00 | positions + macro + defense + exit plans |

## Phases

**Phase 1 (this build):**
- `premium_harvest_scan.py` with 3-layer pipeline + signal blocks
- `harvest_scan` sheet schema
- `ping_harvest_scan()` Telegram push
- `HarvestPage.tsx` PWA tab (picks + macro banner)
- `InsiderPage.tsx` PWA tab (confluence + congress + insider + investment score)
- `market_scan.py` CSP+CC dedup fix
- Tab bar update (Home, Portfolio, Options, Harvest, Insider, Decisions, Review, Settings)

**Phase 2 (future):**
- Active Harvest tracking (match picks to IBKR positions)
- Harvest History + win rate analytics
- Investment score as standalone computed column in screen_gov_confluence
