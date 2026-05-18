# IV Surface Scanner Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a volatility-surface option scanner that fits an IV smile per ticker, ranks every contract by richness (iv_excess), and surfaces the best premium-selling opportunities on a dedicated Scanner page.

**Architecture:** Python backend script (`scripts/iv_surface_scan.py`) fetches multi-expiry option chains from yfinance for portfolio + harvest tickers, fits a 2D polynomial IV surface via numpy OLS, computes iv_excess per contract, writes to a new Sheet tab (`iv_surface_scan`). PWA reads CSV, renders an IV smile scatter chart (Recharts), top candidates table, and full chain view on a new Scanner page.

**Tech Stack:** Python 3.12 + yfinance + numpy (backend), React + TypeScript + Tailwind + Recharts (PWA), Google Sheets CSV (data layer), GitHub Actions (cron trigger).

**Design doc:** `docs/plans/2026-05-18-iv-surface-scanner-design.md`

---

## Task 1: Schema — IvSurfaceScanRow dataclass

**Files:**
- Modify: `src/schema.py` (append after HarvestScanRow at line ~2135)

**Step 1: Add the dataclass**

Append to end of `src/schema.py`:

```python
@dataclass
class IvSurfaceScanRow:
    """IV surface scanner output — one row per option contract per day.

    The key metric is iv_excess: actual IV minus fitted IV surface value
    in percentage points. Positive = rich premium (sell candidate).
    Negative = cheap (skip or buy).
    """
    TAB_NAME = "iv_surface_scan"
    HEADERS = [
        "date", "ticker", "type", "strike", "expiry", "dte", "spot",
        "iv", "iv_fitted", "iv_excess",
        "delta", "bid", "ask", "mid", "ann_yield_pct",
        "oi", "volume", "spread_pct",
        "assignment_risk", "earnings_before_expiry",
    ]

    date: str
    ticker: str
    type: str               # "P" or "C"
    strike: float
    expiry: str             # YYYY-MM-DD
    dte: int
    spot: float
    iv: float               # actual implied vol (0-1 scale)
    iv_fitted: float        # fitted surface value
    iv_excess: float        # iv - iv_fitted in percentage points
    delta: float            # Black-Scholes delta
    bid: float
    ask: float
    mid: float
    ann_yield_pct: float    # annualised yield on capital at risk
    oi: int                 # open interest
    volume: int
    spread_pct: float       # bid-ask spread as %
    assignment_risk: str    # "LOW" | "MEDIUM" | "HIGH"
    earnings_before_expiry: bool

    def to_row(self) -> List[str]:
        return [
            self.date, self.ticker, self.type,
            _num(self.strike, 2), self.expiry, str(self.dte),
            _num(self.spot, 2),
            _num(self.iv, 4), _num(self.iv_fitted, 4),
            _num(self.iv_excess, 2),
            _num(self.delta, 4),
            _num(self.bid, 2), _num(self.ask, 2), _num(self.mid, 2),
            _num(self.ann_yield_pct, 1),
            str(self.oi), str(self.volume),
            _num(self.spread_pct, 1),
            self.assignment_risk,
            "TRUE" if self.earnings_before_expiry else "",
        ]
```

**Step 2: Verify import works**

Run: `python -c "from src.schema import IvSurfaceScanRow; print(IvSurfaceScanRow.HEADERS)"`
Expected: prints the 20 headers list

**Step 3: Commit**

```bash
git add src/schema.py
git commit -m "feat(schema): add IvSurfaceScanRow for IV surface scanner"
```

---

## Task 2: Backend — iv_surface_scan.py core pipeline

**Files:**
- Create: `scripts/iv_surface_scan.py`

**Step 1: Write the full scanner script**

The script follows the same structure as `scripts/premium_harvest_scan.py`:
- Reads portfolio tickers from Sheet (positions_caspar + positions_sarah) + harvest_scan
- Fetches multi-expiry chains from yfinance
- Fits IV surface, scores contracts, writes to Sheet

Key functions to implement:

```python
"""
iv_surface_scan.py — IV Surface Option Scanner

Fits a volatility surface per ticker using a 2D polynomial (OLS),
ranks every contract by iv_excess (how many percentage points above
the fitted surface), and writes results to the iv_surface_scan sheet.

North star: find rich premium to sell with minimal assignment risk.

Usage:
  python scripts/iv_surface_scan.py            # full scan
  python scripts/iv_surface_scan.py --dry      # print only, no sheet write
  python scripts/iv_surface_scan.py --tickers AVGO TSLA   # specific tickers
"""
```

Core algorithms:

1. **`_gather_universe(client)`** — read positions_caspar, positions_sarah, harvest_scan from Sheet, deduplicate tickers. Return `list[str]`.

2. **`_fetch_chains(ticker, min_dte=14, max_dte=120)`** — `yf.Ticker(sym).options` for expirations, filter by DTE range, `t.option_chain(exp)` for each. Return a DataFrame with columns: `type, strike, expiry, dte, spot, iv, bid, ask, mid, oi, volume`. Skip contracts with IV=0 or bid=0.

3. **`_fit_iv_surface(df)`** — given a DataFrame of contracts for one ticker, compute `log_moneyness = ln(strike/spot)`, `sqrt_time = sqrt(dte/365)`. Build design matrix `[1, m, m^2, sqrt_t, m*sqrt_t]`. Solve via `np.linalg.lstsq`. Return fitted IV per row. Require >= 5 valid rows to fit; skip ticker otherwise.

4. **`_bs_delta(spot, strike, iv, dte, r=0.045, option_type='P')`** — Black-Scholes delta. For puts: `N(d1) - 1`. For calls: `N(d1)`. Where `d1 = (ln(S/K) + (r + 0.5*iv^2)*T) / (iv*sqrt(T))`.

5. **`_get_earnings_date(ticker)`** — `yf.Ticker(sym).calendar` → next earnings date. Compare to each contract's expiry.

6. **`_score_row(row)`** — compute `iv_excess = (iv - iv_fitted) * 100` (convert to pp), `ann_yield_pct = (mid / strike) * (365 / dte) * 100` for puts or `(mid / spot) * (365 / dte) * 100` for calls, `spread_pct = (ask - bid) / mid * 100`, `assignment_risk` based on abs(delta).

7. **`main()`** — orchestrate: gather universe → loop tickers → fetch chains → fit surface → score → collect all IvSurfaceScanRow → write to Sheet via `sh.append_rows(client, IvSurfaceScanRow.TAB_NAME, rows)`.

Use `argparse` for `--dry` and `--tickers` flags.
Use `logging` at INFO level with same format as premium_harvest_scan.
Rate-limit yfinance calls with 0.5s sleep between tickers.

**Step 2: Test locally with --dry**

Run: `python scripts/iv_surface_scan.py --dry --tickers AVGO`
Expected: prints ~30-100 contract rows for AVGO, no Sheet write

**Step 3: Test full write with one ticker**

Run: `python scripts/iv_surface_scan.py --tickers AVGO`
Expected: writes rows to Sheet tab `iv_surface_scan`, logs row count

**Step 4: Commit**

```bash
git add scripts/iv_surface_scan.py
git commit -m "feat: iv_surface_scan.py — volatility surface option scanner"
```

---

## Task 3: GitHub Actions workflow

**Files:**
- Create: `.github/workflows/iv-surface-scan.yml`

**Step 1: Write the workflow file**

Follow the exact pattern of `premium-harvest-scan.yml`:

```yaml
name: IV Surface Scan — Volatility Surface

on:
  schedule:
    # 13:00 UTC = 8:00 AM ET (pre-market, after overnight IV settles)
    - cron: "0 13 * * 1-5"
  workflow_dispatch:
    inputs:
      dry:
        type: boolean
        default: false
      tickers:
        type: string
        description: "Space-separated ticker override (blank = portfolio + harvest)"
        default: ""

permissions:
  contents: read

concurrency:
  group: iv-surface-scan
  cancel-in-progress: false

jobs:
  scan:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    env:
      OAUTH_TOKEN_JSON:    ${{ secrets.OAUTH_TOKEN_JSON }}
      SHEET_ID:            ${{ secrets.SHEET_ID }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -r requirements.txt
      - name: Run IV surface scan
        run: |
          ARGS=""
          if [ "${{ inputs.dry }}" = "true" ]; then ARGS="$ARGS --dry"; fi
          if [ -n "${{ inputs.tickers }}" ]; then ARGS="$ARGS --tickers ${{ inputs.tickers }}"; fi
          python scripts/iv_surface_scan.py $ARGS
```

**Step 2: Commit**

```bash
git add .github/workflows/iv-surface-scan.yml
git commit -m "ci: add iv-surface-scan workflow (daily 13:00 UTC pre-market)"
```

---

## Task 4: PWA data layer — IvSurfaceScanRow interface + fetch

**Files:**
- Modify: `pwa/src/data.ts`

**Step 1: Add the TypeScript interface**

After `HarvestScanRow` interface (around line 825), add:

```typescript
export interface IvSurfaceScanRow {
  date?: string;
  ticker?: string;
  type?: string;        // "P" or "C"
  strike?: string;
  expiry?: string;
  dte?: string;
  spot?: string;
  iv?: string;
  iv_fitted?: string;
  iv_excess?: string;   // percentage points above fitted surface
  delta?: string;
  bid?: string;
  ask?: string;
  mid?: string;
  ann_yield_pct?: string;
  oi?: string;
  volume?: string;
  spread_pct?: string;
  assignment_risk?: string;  // "LOW" | "MEDIUM" | "HIGH"
  earnings_before_expiry?: string;
}
```

**Step 2: Add GID to GIDS record**

In the `GIDS` constant (around line 71), add after `harvest_scan`:

```typescript
iv_surface_scan: "0",  // placeholder — update after first scan creates the tab
```

**Step 3: Add to fetchAll()**

In the `fetchAll` function, add the fetch call alongside the other parallel fetches:

```typescript
fetchTab<IvSurfaceScanRow>("iv_surface_scan").catch(() => [] as IvSurfaceScanRow[]),
```

And wire it into the return object as `ivSurfaceScan`.

**Step 4: Build to verify**

Run: `cd pwa && npm run build`
Expected: clean build, no TS errors

**Step 5: Commit**

```bash
git add pwa/src/data.ts
git commit -m "feat(pwa): add IvSurfaceScanRow interface + fetch"
```

---

## Task 5: Install Recharts

**Files:**
- Modify: `pwa/package.json`

**Step 1: Install recharts**

Run: `cd pwa && npm install recharts`

**Step 2: Verify build still passes**

Run: `npm run build`
Expected: clean build

**Step 3: Commit**

```bash
git add pwa/package.json pwa/package-lock.json
git commit -m "chore: add recharts for IV surface chart"
```

---

## Task 6: PWA — IvSmileChart component

**Files:**
- Create: `pwa/src/cards/IvSmileChart.tsx`

**Step 1: Build the scatter chart component**

Props: `{ contracts: IvSurfaceScanRow[], spot: number }`

Implementation:
- Recharts `ComposedChart` with `Scatter` (actual IV dots) + `Line` (fitted curve)
- X-axis: strike price. Y-axis: IV as percentage
- Custom dot renderer: green fill for iv_excess > 3, gray for ±3, red for < -3
- Dot radius scales with `Math.min(8, 3 + Math.abs(iv_excess))`
- Spot price shown as `ReferenceLine` (vertical dashed)
- Tap handler: set selected contract → show popover with details
- Popover shows: strike, IV+pp, delta, OI, annual yield, bid/ask
- Responsive: `ResponsiveContainer` width 100%, height 250

Sort contracts by strike ascending for the fitted line to draw correctly.

**Step 2: Build and verify**

Run: `npm run build`
Expected: no TS errors

**Step 3: Commit**

```bash
git add pwa/src/cards/IvSmileChart.tsx
git commit -m "feat(pwa): IvSmileChart — scatter plot with fitted IV curve"
```

---

## Task 7: PWA — TopCandidatesCard component

**Files:**
- Create: `pwa/src/cards/TopCandidatesCard.tsx`

**Step 1: Build the ranked table**

Props: `{ contracts: IvSurfaceScanRow[] }`

Implementation:
- Filter to `iv_excess > 0` only
- Sort by iv_excess descending
- Show top 15 (configurable)
- Per row: ticker, type badge (P/C), strike, expiry, DTE, IV+pp (colored), delta, annual yield %, OI
- Row shading: green background for iv_excess > 5pp, subtle green for 3-5pp, gray otherwise
- Yellow warning icon on rows where spread_pct > 15 or oi < 50
- Earnings warning emoji on rows where earnings_before_expiry = true
- Assignment risk badge: green (LOW), amber (MEDIUM), red (HIGH)
- Tap row → expand to show bid/ask, spread %, volume, full details

Use the existing `Card` wrapper and follow the styling pattern from `HarvestPicksCard.tsx`.

**Step 2: Build**

Run: `npm run build`

**Step 3: Commit**

```bash
git add pwa/src/cards/TopCandidatesCard.tsx
git commit -m "feat(pwa): TopCandidatesCard — ranked rich-premium contracts"
```

---

## Task 8: PWA — ChainViewCard component

**Files:**
- Create: `pwa/src/cards/ChainViewCard.tsx`

**Step 1: Build the chain table**

Props: `{ contracts: IvSurfaceScanRow[], spot: number }`

Implementation:
- All contracts for the currently selected ticker + expiration
- Sorted by strike ascending
- Columns: Strike, Type, IV, IV+pp, Delta, Bid, Ask, Mid, OI, Vol, Yield%
- Row shading same as TopCandidatesCard (by iv_excess)
- Yellow cell shading on: wide spread (spread_pct > 15), low OI (< 50), low volume (< 10)
- ITM strikes get subtle background tint to distinguish from OTM
- Spot price shown as a divider row between ITM and OTM strikes

**Step 2: Build**

Run: `npm run build`

**Step 3: Commit**

```bash
git add pwa/src/cards/ChainViewCard.tsx
git commit -m "feat(pwa): ChainViewCard — full option chain with IV shading"
```

---

## Task 9: PWA — ScannerPage assembly

**Files:**
- Create: `pwa/src/pages/ScannerPage.tsx`
- Modify: `pwa/src/App.tsx` (add page case, import, TAB_TITLES)
- Modify: `pwa/src/components/TabBar.tsx` (add Scanner tab)

**Step 1: Build ScannerPage**

State:
- `selectedTicker: string | null` — which ticker to show (default: first)
- `selectedExpiry: string | null` — which expiry for chart + chain view
- `filterType: "P" | "C" | "both"` — default "P" (CSP focus)
- `deltaRange: [number, number]` — default [5, 30]
- `filtersOpen: boolean` — collapsible filter bar

Layout (vertical scroll):
1. **Ticker chips** — horizontal scroll of all scanned tickers, tap to select
2. **Expiration dropdown** — available expiries for selected ticker
3. **IvSmileChart** — filtered to selected ticker + expiry
4. **TopCandidatesCard** — filtered by deltaRange, filterType, all tickers
5. **ChainViewCard** — selected ticker + expiry
6. **Filters bar** (collapsible) — delta range slider, type toggle, min OI

Props from App.tsx: `{ ivSurfaceScan: IvSurfaceScanRow[], loading: boolean }`

**Step 2: Wire into App.tsx**

- Import `ScannerPage`
- Add `"Scanner"` to `TAB_TITLES` at index 4 (between Harvest and Insider, shifting others up)
- Add `case 4:` rendering ScannerPage with `ivSurfaceScan` prop
- Shift existing cases: Insider→5, Decisions→6, Review→7, Settings→8
- Update `SETTINGS_TAB` constant if it exists

**Step 3: Wire into TabBar.tsx**

- Import `Scan` (or `Radar` or `Activity`) icon from lucide-react
- Add `{ icon: Scan, label: "Scanner" }` at index 4 in the `TABS` array

**Step 4: Build and verify**

Run: `npm run build`
Expected: clean build. Tab bar shows 9 tabs including Scanner.

**Step 5: Commit**

```bash
git add pwa/src/pages/ScannerPage.tsx pwa/src/App.tsx pwa/src/components/TabBar.tsx
git commit -m "feat(pwa): ScannerPage with IV smile chart, candidates, chain view"
```

---

## Task 10: First scan run + GID resolution

**Step 1: Trigger the scan locally**

Run: `python scripts/iv_surface_scan.py --tickers AVGO TSLA NVDA`

This creates the `iv_surface_scan` Sheet tab if it doesn't exist.

**Step 2: Get the GID**

After the tab is created, get its GID from the Sheet URL or via gspread:

```python
python -c "
from src import sheets as sh
c = sh.authenticate()
import os
wb = c.open_by_key(os.environ['SHEET_ID'])
ws = wb.worksheet('iv_surface_scan')
print(ws.id)
"
```

**Step 3: Update data.ts with real GID**

Replace `iv_surface_scan: "0"` with the actual GID.

**Step 4: Rebuild and verify in browser**

Run: `cd pwa && npm run build`
Open PWA → Scanner tab → verify data loads and chart renders.

**Step 5: Commit**

```bash
git add pwa/src/data.ts
git commit -m "fix: resolve iv_surface_scan GID after first run"
```

---

## Task 11: Final push + workflow trigger

**Step 1: Push all commits**

Run: `git push origin main`

**Step 2: Trigger workflow manually**

Run: `gh workflow run iv-surface-scan.yml --repo xynkro/CasaaFinance`

**Step 3: Verify workflow completes**

Run: `gh run list --workflow=iv-surface-scan.yml --repo xynkro/CasaaFinance --limit 1`

---

## Summary

| Task | What | Files |
|------|------|-------|
| 1 | Schema dataclass | `src/schema.py` |
| 2 | Backend scanner script | `scripts/iv_surface_scan.py` |
| 3 | GitHub Actions workflow | `.github/workflows/iv-surface-scan.yml` |
| 4 | PWA data layer | `pwa/src/data.ts` |
| 5 | Install Recharts | `pwa/package.json` |
| 6 | IV Smile Chart component | `pwa/src/cards/IvSmileChart.tsx` |
| 7 | Top Candidates Card | `pwa/src/cards/TopCandidatesCard.tsx` |
| 8 | Chain View Card | `pwa/src/cards/ChainViewCard.tsx` |
| 9 | Scanner Page + nav wiring | `pwa/src/pages/ScannerPage.tsx`, `App.tsx`, `TabBar.tsx` |
| 10 | First scan + GID | `pwa/src/data.ts` |
| 11 | Push + workflow trigger | git push |
