# IV Surface Scanner — Design

**Date:** 2026-05-18
**Status:** Approved
**North star:** Earn money on premiums, never get assigned.

## What

A volatility-surface option scanner for FinancePWA. Fits an IV smile per
ticker across multiple expirations, ranks every contract by how rich its
premium is relative to the fitted surface (IV+pp), and surfaces the best
contracts to sell on a dedicated Scanner page.

Inspired by [medloh/stockpile](https://github.com/medloh/stockpile).

## Architecture

```
GitHub Actions cron (13:00 UTC / 8am ET)
  → scripts/iv_surface_scan.py
  → yfinance multi-expiry chain fetch
  → 2D polynomial IV surface fit (OLS)
  → writes to Sheet tab: iv_surface_scan
  → PWA reads CSV, renders chart + tables
```

Same batch-to-Sheet-to-PWA pattern as every other scanner.

## Universe

Portfolio tickers (CASPAR + SARAH positions) + harvest_scan picks.
~30 symbols. For each: 3 nearest qualifying expirations (DTE 14–120),
puts + calls.

## IV Surface Fit

5-coefficient 2D polynomial via OLS (numpy `lstsq`):

```
IV = a + b·m + c·m² + d·√T + e·m·√T
```

Where `m = ln(K/S)` (log-moneyness), `T = DTE/365`.
Requires ≥5 valid contracts per ticker; skip otherwise.

**Key metric:** `iv_excess = actual_IV - fitted_IV` in percentage points.
Positive = rich premium (sell). Negative = cheap (skip or buy).

## Backend: `scripts/iv_surface_scan.py`

Pipeline:
1. Gather universe from Sheet (positions + harvest_scan), deduplicate
2. Fetch chains via yfinance — all expirations in DTE 14–120
3. Compute log-moneyness and time-to-expiry per contract
4. Fit surface per-ticker (OLS, 5 coefficients)
5. Score: iv_excess, Black-Scholes delta (r=4.5%), annualized yield
6. Tag assignment_risk: LOW (<15 delta), MEDIUM (15–30), HIGH (>30)
7. Flag earnings_before_expiry (yfinance calendar)
8. Write to Sheet tab `iv_surface_scan` (clear + rewrite daily)

### Sheet Schema (one row per contract)

| Column | Type | Example |
|--------|------|---------|
| date | str | 2026-05-19 |
| ticker | str | AVGO |
| type | str | P |
| strike | float | 380 |
| expiry | str | 2026-06-20 |
| dte | int | 32 |
| spot | float | 432.50 |
| iv | float | 0.42 |
| iv_fitted | float | 0.38 |
| iv_excess | float | 4.0 |
| delta | float | -0.18 |
| bid | float | 3.40 |
| ask | float | 3.80 |
| mid | float | 3.60 |
| ann_yield_pct | float | 34.2 |
| oi | int | 1250 |
| volume | int | 340 |
| spread_pct | float | 11.1 |
| assignment_risk | str | LOW |
| earnings_before_expiry | bool | false |

### GitHub Actions

`iv-surface-scan.yml` — cron 13:00 UTC (8am ET pre-market).
Runtime ~2-3 min for 30 tickers.

## PWA: Scanner Page

New nav tab: **Scanner** (between Harvest and Insider).

### Card 1 — IV Smile Chart

Scatter plot (Recharts `ScatterChart` + `LineChart` overlay):
- X-axis: strike price
- Y-axis: implied volatility %
- Green dots: iv_excess > +3pp (rich, sell these)
- Gray dots: ±3pp (fair value)
- Red dots: < -3pp (cheap, skip)
- Dot size scales with |iv_excess|
- Dashed line: fitted IV surface
- Vertical dashed line: spot price
- Tap dot → popover: strike, IV+pp, delta, OI, yield, bid/ask
- Expiration dropdown to switch views
- Earnings warning banner if earnings before selected expiry

### Card 2 — Top Candidates

Best contracts across ALL expirations, ranked by iv_excess descending.
Default filter: assignment_risk = LOW (delta < 15).

Columns: ticker, strike, expiry, DTE, IV+pp, delta, annual yield %,
bid/ask spread %, OI.

Row shading: green (rich), gray (fair), yellow warning on wide
spreads or low OI.

### Card 3 — Chain View

Full chain for selected ticker + expiration, sorted by strike.
Same row shading. Equivalent to Stockpile's chain table.

### Filters (collapsible bar)

- Delta range: default 5–30 (far OTM, minimizes assignment)
- Min OI: 10
- Type: Puts / Calls / Both (default Puts for CSP)
- Only iv_excess > 0 in top candidates by default

### Roll Mode

Tap active short option from Book → "Find rolls" → filters Scanner
to same ticker, later expiry, adds net credit column. Not a separate
page — a filter preset.

### Ticker Selector

Scrollable chip bar at top. All scanned tickers. Tap to filter
chart + chain view to that ticker.

## Not Building (YAGNI)

- Portfolio CSV upload (IBKR positions already flow in)
- Spreads builder (1,300 lines in Stockpile, separate project)
- HTML report export (PWA is the report)
- Buy mode as default (exists in filters, not prominent)
- 3D surface visualization (useless on mobile)

## Dependencies

**Backend:** numpy (already installed), yfinance (already installed),
scipy not needed (OLS via numpy.linalg.lstsq).

**PWA:** recharts (new dependency, ~40KB gzipped).
