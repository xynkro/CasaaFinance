# Premium Harvest Scanner Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a "never get assigned" CSP scanner that discovers high-IV opportunities across the full US market, filters by macro regime + fundamentals + technicals, and surfaces picks with pre-built entry/maintenance/exit signals on a new PWA tab and Telegram.

**Architecture:** New standalone `premium_harvest_scan.py` with 3-layer pipeline (FinViz universe → macro+fundamental gate → technical conviction). New `HarvestScanRow` schema. New `HarvestPage.tsx` + `InsiderPage.tsx` PWA tabs. Telegram push via `ping_harvest_scan()`. Bug fix for `market_scan.py` CSP+CC dedup.

**Tech Stack:** Python (yfinance, finvizfinance), TypeScript/React (Vite PWA), Google Sheets (via gspread), Telegram Bot API.

**Design doc:** `docs/plans/2026-05-17-premium-harvest-scanner-design.md`

---

## Task 1: `HarvestScanRow` Schema

**Files:**
- Modify: `src/schema.py` (append after `AlpacaPositionRow` class, ~line 2080)

**Step 1: Add `HarvestScanRow` dataclass**

Add after the `AlpacaPositionRow` class at end of `schema.py`:

```python
@dataclass
class HarvestScanRow:
    """Premium Harvest scanner output — one row per candidate per day.

    Each row carries entry/maintenance/exit signal blocks as JSON strings
    so the PWA and Telegram can render full lifecycle plans.
    """
    TAB_NAME = "harvest_scan"
    HEADERS = [
        "date", "ticker", "strategy", "strike", "expiry", "dte",
        "credit", "annual_yield_pct", "iv_rank", "conviction",
        "underlying_last", "cash_required", "breakeven",
        "sr_context", "macro_regime", "vix",
        "entry_signals", "maintenance_signals", "exit_signals",
        "notes",
    ]

    date: str
    ticker: str
    strategy: str           # HARVEST_CSP | HARVEST_STRANGLE
    strike: float
    expiry: str             # YYYYMMDD
    dte: int
    credit: float
    annual_yield_pct: float
    iv_rank: float
    conviction: int         # 0-100
    underlying_last: float
    cash_required: float
    breakeven: float
    sr_context: str         # "near support $98 (7%) · RSI 42"
    macro_regime: str       # STANDARD | CAUTION | HALTED
    vix: float
    entry_signals: str      # JSON dict
    maintenance_signals: str # JSON dict
    exit_signals: str       # JSON dict
    notes: str              # e.g. "call_strike=140" for strangles

    def to_row(self) -> List[str]:
        return [
            self.date, self.ticker, self.strategy,
            _num(self.strike, 2), self.expiry, str(self.dte),
            _num(self.credit, 2), _num(self.annual_yield_pct, 1),
            _num(self.iv_rank, 1), str(self.conviction),
            _num(self.underlying_last, 2), _num(self.cash_required, 2),
            _num(self.breakeven, 2),
            self.sr_context, self.macro_regime, _num(self.vix, 1),
            self.entry_signals, self.maintenance_signals, self.exit_signals,
            self.notes,
        ]
```

**Step 2: Verify schema compiles**

Run: `python3 -c "import py_compile; py_compile.compile('src/schema.py', doraise=True); print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add src/schema.py
git commit -m "feat: add HarvestScanRow schema for premium harvest scanner"
```

---

## Task 2: `premium_harvest_scan.py` — Layer 1 Universe Discovery

**Files:**
- Create: `scripts/premium_harvest_scan.py`

**Step 1: Create the script with Layer 1 (universe discovery)**

Create `scripts/premium_harvest_scan.py` with:
- `_setup_logging()` — same pattern as `daily_options_scan.py`
- `FALLBACK_HIGH_IV_UNIVERSE` — ~80 curated high-IV tickers as fallback
- `discover_universe(logger) -> list[str]` — try FinViz screener first (`finvizfinance.screener.overview.Overview` with filters: `optionable=True`, price $5-$600, avg volume > 500K, market cap > small). Sort by volatility. Take top 150. On failure, fall back to curated list.
- `main()` with argparse (`--dry`, `--top N`)
- Script header matching `daily_options_scan.py` pattern

The FinViz screener call:
```python
from finvizfinance.screener.overview import Overview
foverview = Overview()
filters_dict = {
    "Option/Short": "Optionable",
    "Price": "Over $5",
    "Average Volume": "Over 500K",
    "Market Cap": "+Small (over $300mln)",
}
foverview.set_filter(filters_dict=filters_dict)
df = foverview.screener_view()
# df has columns: No., Ticker, Company, Sector, Industry, ...
tickers = df["Ticker"].tolist()[:150]
```

Fallback universe (curated):
```python
FALLBACK_HIGH_IV_UNIVERSE = [
    # Metals / commodities ETFs (high IV, your friend's picks)
    "SLV", "GDX", "COPX", "GLD", "TLT", "USO", "XLE",
    # Crypto-adjacent
    "MSTR", "COIN", "HOOD", "RIOT", "MARA", "CLSK",
    # High-IV tech/growth
    "AAOI", "CRWV", "BMNR", "OPEN", "SNAP", "PINS", "ROKU",
    "DKNG", "PENN", "AFRM", "UPST", "SOFI", "LCID", "RIVN",
    # Meme/momentum
    "PLTR", "RKLB", "ASTS", "NBIS", "RDDT", "PATH", "IONQ",
    # Large-cap high IV
    "TSLA", "AMD", "NVDA", "MU", "SMCI", "ARM", "AVGO",
    "NFLX", "META", "AMZN", "GOOGL",
    # Biotech (high IV but careful)
    "MRNA", "CRSP",
    # Industrials with options volume
    "BA", "GE", "CAT", "DE",
    # Financials
    "JPM", "GS", "BAC", "C", "MS",
    # Consumer
    "NKE", "LULU", "COST", "WMT",
    # Energy
    "OXY", "CVX", "XOM", "HAL",
    # Misc high-IV
    "SNDK", "ORCL", "SHOP", "SQ", "PYPL",
]
```

**Step 2: Test Layer 1 runs**

Run: `python3 scripts/premium_harvest_scan.py --dry`
Expected: prints discovered universe count or falls back to curated list

**Step 3: Commit**

```bash
git add scripts/premium_harvest_scan.py
git commit -m "feat: premium_harvest_scan Layer 1 — universe discovery via FinViz"
```

---

## Task 3: `premium_harvest_scan.py` — Layer 2 Macro Gate + Fundamentals

**Files:**
- Modify: `scripts/premium_harvest_scan.py`

**Step 1: Add macro gate function**

```python
def macro_gate(logger) -> dict:
    """Check macro regime. Returns {regime, vix, spx, spx_above_200sma, halted, blackout, caution}."""
    import yfinance as yf

    result = {"regime": "STANDARD", "halted": False, "blackout": False, "caution": False}

    # VIX
    try:
        vix_data = yf.download("^VIX", period="1d", progress=False)
        vix = float(vix_data["Close"].dropna().iloc[-1])
        result["vix"] = round(vix, 1)
    except Exception:
        vix = 18.0  # assume normal if fetch fails
        result["vix"] = vix

    # SPX + 200 SMA
    try:
        spx_data = yf.download("^GSPC", period="250d", progress=False)
        spx_close = spx_data["Close"].dropna()
        spx = float(spx_close.iloc[-1])
        sma200 = float(spx_close.tail(200).mean()) if len(spx_close) >= 200 else 0
        result["spx"] = round(spx, 1)
        result["spx_sma200"] = round(sma200, 1)
        result["spx_above_200sma"] = spx > sma200
    except Exception:
        result["spx"] = 0
        result["spx_above_200sma"] = True  # assume OK

    # Macro blackout check
    try:
        from src.macro_blackouts import MacroFeed
        feed = MacroFeed.fetch()
        # Check if any high-impact event within 2 days
        from datetime import datetime, timedelta, timezone
        now_utc = datetime.now(timezone.utc)
        for ev in feed.events:
            ev_time = ev.get("_dt") or ev.get("datetime")
            if ev_time and abs((ev_time - now_utc).total_seconds()) < 2 * 86400:
                if ev.get("impact") == "high":
                    result["blackout"] = True
                    result["blackout_event"] = ev.get("event", "unknown")
                    break
    except Exception:
        pass  # no blackout data = assume OK

    # Regime classification
    if vix > 30 or not result.get("spx_above_200sma", True):
        result["regime"] = "HALTED"
        result["halted"] = True
    elif vix > 25 or result.get("blackout"):
        result["regime"] = "CAUTION"
        result["caution"] = True

    logger.info(f"Macro gate: {result['regime']} (VIX={result['vix']}, SPX>200SMA={result.get('spx_above_200sma')})")
    return result
```

**Step 2: Add soft fundamental filter**

```python
def fundamental_gate(ticker: str, logger) -> tuple[bool, str]:
    """Soft fundamental filter. Returns (pass, reason)."""
    import yfinance as yf

    try:
        info = yf.Ticker(ticker).info
    except Exception:
        return False, "info fetch failed"

    mkt_cap = info.get("marketCap") or 0
    if mkt_cap < 500_000_000:
        return False, f"market cap ${mkt_cap/1e6:.0f}M < $500M"

    revenue = info.get("totalRevenue") or info.get("revenue") or 0
    if revenue <= 0:
        return False, "no revenue"

    price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
    if price < 3:
        return False, f"price ${price:.2f} < $3"

    return True, "pass"
```

**Step 3: Wire Layer 2 into main() — filter universe through macro + fundamentals**

After Layer 1 discovers tickers, run:
```python
macro = macro_gate(logger)
if macro["halted"]:
    logger.warning("MACRO HALTED — skipping harvest scan")
    # Still write a single row flagging the halt for PWA banner
    ...
    return 0

survivors = []
for ticker in universe:
    ok, reason = fundamental_gate(ticker, logger)
    if ok:
        survivors.append(ticker)
    else:
        logger.debug(f"  {ticker}: fundamental reject — {reason}")
logger.info(f"Layer 2: {len(survivors)} of {len(universe)} passed fundamentals")
```

**Step 4: Verify**

Run: `python3 scripts/premium_harvest_scan.py --dry`
Expected: prints macro regime + fundamental filter pass/fail counts

**Step 5: Commit**

```bash
git add scripts/premium_harvest_scan.py
git commit -m "feat: premium_harvest_scan Layer 2 — macro gate + soft fundamentals"
```

---

## Task 4: `premium_harvest_scan.py` — Layer 3 Technical Filter + Signal Blocks

**Files:**
- Modify: `scripts/premium_harvest_scan.py`

**Step 1: Add technical conviction filter**

```python
def technical_conviction(ticker: str, logger) -> tuple[bool, int, dict]:
    """
    Technical gates + conviction score. Returns (pass, score, context_dict).
    context_dict has keys: price, sma50, sma200, rsi_14, support, resistance, hv30
    """
    import yfinance as yf
    import math

    try:
        yt = yf.Ticker(ticker)
        hist = yt.history(period="250d", interval="1d", auto_adjust=True)
        if hist.empty or len(hist) < 50:
            return False, 0, {}
        closes = hist["Close"].dropna()
        price = float(closes.iloc[-1])
    except Exception:
        return False, 0, {}

    # SMA-50
    sma50 = float(closes.tail(50).mean()) if len(closes) >= 50 else 0
    # SMA-200
    sma200 = float(closes.tail(200).mean()) if len(closes) >= 200 else 0
    # SMA-20
    sma20 = float(closes.tail(20).mean()) if len(closes) >= 20 else 0

    # RSI-14 (Wilder smoothing)
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = (-delta.clip(upper=0))
    avg_gain = gain.ewm(alpha=1/14, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0, float('inf'))
    rsi_series = 100 - (100 / (1 + rs))
    rsi_14 = float(rsi_series.iloc[-1]) if len(rsi_series) >= 14 else 50.0
    if math.isnan(rsi_14):
        rsi_14 = 50.0

    # 20d support/resistance
    recent_20 = closes.tail(20)
    support = float(recent_20.min())
    resistance = float(recent_20.max())

    # HV30
    log_rets = closes.pct_change().dropna().apply(lambda x: math.log(1 + x))
    hv30 = float(log_rets.tail(30).std() * math.sqrt(252) * 100)

    # Volume check
    vols = hist["Volume"].dropna()
    avg_vol = float(vols.tail(20).mean()) if len(vols) >= 20 else 0

    ctx = {
        "price": round(price, 2),
        "sma20": round(sma20, 2),
        "sma50": round(sma50, 2),
        "sma200": round(sma200, 2),
        "rsi_14": round(rsi_14, 1),
        "support": round(support, 2),
        "resistance": round(resistance, 2),
        "hv30": round(hv30, 1),
        "avg_vol": int(avg_vol),
    }

    # === GATES (all must pass) ===
    if sma50 > 0 and price < sma50:
        return False, 0, ctx  # below SMA-50
    if sma200 > 0 and price < sma200:
        return False, 0, ctx  # below SMA-200
    if rsi_14 < 30 or rsi_14 > 75:
        return False, 0, ctx  # crashing or blow-off
    if support > 0 and price < support * 1.03:
        return False, 0, ctx  # falling knife (within 3% of 20d low)
    if avg_vol < 200_000:
        return False, 0, ctx  # illiquid

    # === CONVICTION SCORE ===
    score = 40  # base (passed all gates)
    if sma20 > sma50:
        score += 10  # uptrend
    if 40 <= rsi_14 <= 60:
        score += 10  # RSI sweet spot
    if support > 0 and price < support * 1.05:
        score += 10  # near support but above
    if hv30 > 0:
        # IV richness bonus computed later when we have IV from chain
        pass
    if avg_vol > 1_000_000:
        score += 5  # high liquidity

    return True, score, ctx
```

**Step 2: Add option chain scan + signal block builder**

```python
def scan_chain(ticker: str, yt, ctx: dict, conviction: int, macro: dict, logger) -> list[dict]:
    """Scan option chain for CSP + CC candidates. Build signal blocks. Returns list of candidate dicts."""
    import json
    from datetime import date, datetime

    price = ctx["price"]
    hv30 = ctx["hv30"]

    try:
        expiries = yt.options
    except Exception:
        return []
    if not expiries:
        return []

    # Best expiry: closest to 35 DTE within [25, 45]
    today = date.today()
    best_exp, best_diff = None, 9999
    for exp_str in expiries:
        try:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            dte = (exp_date - today).days
            if 25 <= dte <= 45:
                diff = abs(dte - 35)
                if diff < best_diff:
                    best_diff = diff
                    best_exp = exp_str
        except ValueError:
            continue
    if not best_exp:
        return []

    dte = (datetime.strptime(best_exp, "%Y-%m-%d").date() - today).days
    expiry_iso = best_exp.replace("-", "")

    try:
        chain = yt.option_chain(best_exp)
    except Exception:
        return []

    candidates = []

    # ── CSP scan ──
    try:
        puts = chain.puts.copy()
        puts = puts[puts["openInterest"] >= 50]
        puts["mid"] = puts.apply(
            lambda r: (r["bid"] + r["ask"]) / 2
            if (r.get("bid", 0) or 0) > 0 or (r.get("ask", 0) or 0) > 0
            else (r.get("lastPrice", 0) or 0),
            axis=1,
        )
        puts = puts[puts["mid"] >= 0.08]
        # Strike 10-18% OTM
        puts = puts[(puts["strike"] >= price * 0.82) & (puts["strike"] <= price * 0.90)]
        puts = puts.copy()
        puts["ann_yield"] = puts["mid"] / puts["strike"] * (365 / dte) * 100
        puts = puts[puts["ann_yield"] >= 14.0]
        puts = puts.sort_values("ann_yield", ascending=False)

        if not puts.empty:
            r = puts.iloc[0]
            mid = float(r["mid"])
            strike = float(r["strike"])
            iv_pct = float(r.get("impliedVolatility", 0) or 0) * 100
            oi = int(r.get("openInterest", 0) or 0)

            # IV richness bonus
            iv_rich_bonus = 10 if (hv30 > 0 and iv_pct / hv30 > 1.2) else 0
            oi_bonus = 5 if oi > 200 else 0
            bid = float(r.get("bid", 0) or 0)
            ask = float(r.get("ask", 0) or 0)
            spread_pct = ((ask - bid) / mid * 100) if mid > 0 and bid > 0 else 99
            spread_bonus = 5 if spread_pct < 10 else 0
            final_conviction = min(100, conviction + iv_rich_bonus + oi_bonus + spread_bonus)

            # S/R context string
            sr_parts = []
            if ctx["support"] > 0:
                dist_pct = (price - ctx["support"]) / price * 100
                sr_parts.append(f"support ${ctx['support']:.0f} ({dist_pct:.0f}%)")
            sr_parts.append(f"RSI {ctx['rsi_14']:.0f}")
            sr_context = " · ".join(sr_parts)

            # Signal blocks
            entry_signals = json.dumps({
                "strategy": "HARVEST_CSP",
                "ticker": ticker, "strike": strike,
                "expiry": expiry_iso, "dte": dte,
                "credit": round(mid, 2),
                "annual_yield_pct": round(float(r["ann_yield"]), 1),
                "iv_rank": round(iv_pct, 1), "conviction": final_conviction,
                "sr_context": sr_context,
                "macro_regime": macro["regime"],
                "vix": macro["vix"],
                "spx_above_200sma": macro.get("spx_above_200sma", True),
            })
            maintenance_signals = json.dumps({
                "profit_target_pct": 50,
                "profit_target_optional": True,
                "time_stop_dte": 21,
                "strike_tested_pct": 3,
                "earnings_in_dte": False,  # TODO: check earnings calendar
                "macro_shift_exit": True,
                "trend_break_exit": True,
                "sma50_at_entry": ctx["sma50"],
            })
            exit_signals = json.dumps({
                "max_loss_mult": 2.0,
                "max_loss_value": round(mid * 2, 2),
                "mechanical_close_dte": 14,
                "assignment_risk_dte": 7,
                "expired_worthless": True,
            })

            candidates.append({
                "ticker": ticker, "strategy": "HARVEST_CSP",
                "strike": strike, "expiry": expiry_iso, "dte": dte,
                "credit": round(mid, 2),
                "annual_yield_pct": round(float(r["ann_yield"]), 1),
                "iv_rank": round(iv_pct, 1),
                "conviction": final_conviction,
                "underlying_last": price,
                "cash_required": round(strike * 100, 2),
                "breakeven": round(strike - mid, 2),
                "sr_context": sr_context,
                "entry_signals": entry_signals,
                "maintenance_signals": maintenance_signals,
                "exit_signals": exit_signals,
                "notes": "",
            })
    except Exception as e:
        logger.debug(f"  {ticker}: CSP chain error — {e}")

    # ── CC scan (for strangle detection) ──
    try:
        calls = chain.calls.copy()
        calls = calls[calls["openInterest"] >= 50]
        calls["mid"] = calls.apply(
            lambda r: (r["bid"] + r["ask"]) / 2
            if (r.get("bid", 0) or 0) > 0 or (r.get("ask", 0) or 0) > 0
            else (r.get("lastPrice", 0) or 0),
            axis=1,
        )
        calls = calls[calls["mid"] >= 0.08]
        calls = calls[(calls["strike"] >= price * 1.05) & (calls["strike"] <= price * 1.15)]
        calls = calls.copy()
        calls["ann_yield"] = calls["mid"] / price * (365 / dte) * 100
        calls = calls[calls["ann_yield"] >= 10.0]
        calls = calls.sort_values("ann_yield", ascending=False)

        if not calls.empty and candidates:
            # Both CSP + CC → merge into HARVEST_STRANGLE
            cr = calls.iloc[0]
            call_mid = float(cr["mid"])
            call_strike = float(cr["strike"])
            csp_rec = candidates[0]  # the CSP we just found
            combined_credit = csp_rec["credit"] + round(call_mid, 2)

            # Overwrite the CSP candidate as a strangle
            csp_rec["strategy"] = "HARVEST_STRANGLE"
            csp_rec["credit"] = round(combined_credit, 2)
            csp_rec["annual_yield_pct"] = round(
                combined_credit / csp_rec["strike"] * (365 / dte) * 100, 1
            )
            csp_rec["notes"] = f"call_strike={call_strike:.2f}"

            # Update signal blocks with strangle info
            entry = json.loads(csp_rec["entry_signals"])
            entry["strategy"] = "HARVEST_STRANGLE"
            entry["credit"] = round(combined_credit, 2)
            entry["call_strike"] = call_strike
            csp_rec["entry_signals"] = json.dumps(entry)

            maint = json.loads(csp_rec["maintenance_signals"])
            maint["strangle_untested_close"] = True
            csp_rec["maintenance_signals"] = json.dumps(maint)

            exit_s = json.loads(csp_rec["exit_signals"])
            exit_s["max_loss_value"] = round(combined_credit * 2, 2)
            csp_rec["exit_signals"] = json.dumps(exit_s)

        elif not calls.empty and not candidates:
            # CC only — rare for harvest, but emit as standalone
            pass  # skip CC-only for harvest scanner (CSP-focused)

    except Exception as e:
        logger.debug(f"  {ticker}: CC chain error — {e}")

    return candidates
```

**Step 3: Wire Layer 3 into main() and write to sheet**

After Layer 2 survivors, for each ticker:
```python
all_candidates = []
for ticker in survivors:
    try:
        yt = yf.Ticker(ticker)
        ok, score, ctx = technical_conviction(ticker, logger)
        if not ok:
            logger.debug(f"  {ticker}: technical reject")
            continue
        picks = scan_chain(ticker, yt, ctx, score, macro, logger)
        all_candidates.extend(picks)
    except Exception as e:
        logger.debug(f"  {ticker}: scan error — {e}")

all_candidates.sort(key=lambda c: c["conviction"], reverse=True)
logger.info(f"Layer 3: {len(all_candidates)} harvest candidates")

# Top picks log
for c in all_candidates[:10]:
    logger.info(f"  {c['strategy']:18} {c['ticker']:6} ${c['strike']:.0f} {c['dte']}d "
                f"cr=${c['credit']:.2f} yld={c['annual_yield_pct']:.0f}% conv={c['conviction']}")
```

Then write to sheet (same pattern as `daily_options_scan.py`):
```python
if not args.dry:
    from src.sync import load_env
    from src import sheets as sh
    from src import schema as S
    load_env()
    client = sh.authenticate()
    sh.ensure_headers(client, S.HarvestScanRow.TAB_NAME, S.HarvestScanRow.HEADERS)
    today_iso = date.today().isoformat()
    rows = []
    for c in all_candidates[:25]:  # cap at 25 per day
        row = S.HarvestScanRow(
            date=today_iso, ticker=c["ticker"], strategy=c["strategy"],
            strike=c["strike"], expiry=c["expiry"], dte=c["dte"],
            credit=c["credit"], annual_yield_pct=c["annual_yield_pct"],
            iv_rank=c["iv_rank"], conviction=c["conviction"],
            underlying_last=c["underlying_last"],
            cash_required=c["cash_required"], breakeven=c["breakeven"],
            sr_context=c["sr_context"],
            macro_regime=macro["regime"], vix=macro["vix"],
            entry_signals=c["entry_signals"],
            maintenance_signals=c["maintenance_signals"],
            exit_signals=c["exit_signals"],
            notes=c.get("notes", ""),
        )
        rows.append(row.to_row())
    sh.append_rows(client, S.HarvestScanRow.TAB_NAME, rows)
    logger.info(f"✓ Wrote {len(rows)} rows to harvest_scan")
```

**Step 4: Full dry run test**

Run: `python3 scripts/premium_harvest_scan.py --dry`
Expected: Prints universe size → fundamental survivors → technical survivors → top 10 picks with conviction scores

**Step 5: Commit**

```bash
git add scripts/premium_harvest_scan.py
git commit -m "feat: premium_harvest_scan Layer 3 — technical conviction + chain scan + signal blocks"
```

---

## Task 5: `ping_harvest_scan()` Telegram Push

**Files:**
- Modify: `src/telegram.py` (append after `ping_options_defense()`, ~line 1020)

**Step 1: Add `ping_harvest_scan()` function**

```python
def ping_harvest_scan(
    date: str,
    candidates: list[dict],
    macro: dict,
    pwa_url: str | None = None,
) -> dict:
    """Push harvest scan picks to Options Intel topic with signal blocks."""
    import html as _html
    import json

    if not candidates:
        return {"skipped": "no harvest candidates"}

    regime = macro.get("regime", "STANDARD")
    regime_emoji = {"STANDARD": "✅", "CAUTION": "⚠️", "HALTED": "🛑"}.get(regime, "❓")
    vix = macro.get("vix", 0)
    spx_status = "SPX>200SMA" if macro.get("spx_above_200sma") else "SPX<200SMA ⚠️"

    lines = [f"<b>🌾 PREMIUM HARVEST</b> · {_html.escape(date)}"]
    lines.append(f"Macro: {regime_emoji} {regime} (VIX {vix:.0f} · {spx_status})")
    lines.append(f"{len(candidates)} candidate{'s' if len(candidates) != 1 else ''}")

    # Group by strategy
    csps = [c for c in candidates if c.get("strategy") == "HARVEST_CSP"]
    strangles = [c for c in candidates if c.get("strategy") == "HARVEST_STRANGLE"]

    for group, label, emoji in [
        (csps, "HARVEST_CSP", "💰"),
        (strangles, "HARVEST_STRANGLE", "🔀"),
    ]:
        if not group:
            continue
        lines.append("")
        lines.append(f"{emoji} <b>{label}</b> ({len(group)})")

        for c in group[:8]:
            tk = _html.escape(str(c.get("ticker", "?")))
            strike = float(c.get("strike", 0))
            exp = str(c.get("expiry", ""))
            if len(exp) == 8:
                exp = f"{exp[4:6]}/{exp[6:]}"
            dte = int(c.get("dte", 0))
            credit = float(c.get("credit", 0))
            yld = float(c.get("annual_yield_pct", 0))
            ivr = float(c.get("iv_rank", 0))
            conv = int(c.get("conviction", 0))

            if c.get("strategy") == "HARVEST_STRANGLE":
                call_strike = c.get("notes", "").replace("call_strike=", "")
                lines.append(
                    f"  <b>${tk}</b> ${strike:.0f}P/${call_strike}C {exp} ({dte}d)"
                    f" · <code>${credit:.2f}</code> cr · {yld:.0f}% ann · Conv {conv}"
                )
            else:
                lines.append(
                    f"  <b>${tk}</b> ${strike:.0f}P {exp} ({dte}d)"
                    f" · <code>${credit:.2f}</code> cr · {yld:.0f}% ann · IVR≈{ivr:.0f} · Conv {conv}"
                )

            # Maintenance + exit one-liner
            try:
                maint = json.loads(c.get("maintenance_signals", "{}"))
                exit_s = json.loads(c.get("exit_signals", "{}"))
                maint_parts = []
                if maint.get("profit_target_pct"):
                    maint_parts.append(f"{maint['profit_target_pct']}% profit")
                if maint.get("time_stop_dte"):
                    maint_parts.append(f"{maint['time_stop_dte']}DTE roll")
                if exit_s.get("max_loss_value"):
                    maint_parts.append(f"stop 2×(${exit_s['max_loss_value']:.2f})")
                if maint_parts:
                    lines.append(f"    📋 {' · '.join(maint_parts)}")
            except Exception:
                pass

    if pwa_url:
        lines.append("")
        lines.append(f'📱 <a href="{_html.escape(pwa_url)}">Full picks in PWA</a>')

    return send(
        "\n".join(lines),
        parse_mode="HTML",
        message_thread_id=OPTIONS_INTEL_TOPIC,
        disable_web_page_preview=True,
    )
```

**Step 2: Wire Telegram push into `premium_harvest_scan.py`**

After writing to sheet:
```python
# Telegram push
try:
    from src import telegram as tg
    tg_result = tg.ping_harvest_scan(
        date=today_iso,
        candidates=all_candidates[:8],
        macro=macro,
        pwa_url="https://xynkro.github.io/CasaaFinance/",
    )
    if tg_result.get("skipped"):
        logger.info(f"  Telegram: skipped ({tg_result['skipped']})")
    else:
        logger.info("  ✓ Harvest picks sent to Telegram")
except Exception as e:
    logger.warning(f"  Telegram harvest push failed: {e}")
```

**Step 3: Verify compilation**

Run: `python3 -c "import py_compile; py_compile.compile('src/telegram.py', doraise=True); print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add src/telegram.py scripts/premium_harvest_scan.py
git commit -m "feat: ping_harvest_scan() Telegram push with signal blocks"
```

---

## Task 6: `market_scan.py` CSP+CC Dedup Fix

**Files:**
- Modify: `scripts/market_scan.py:281-287` (end of `screen_ticker()`)

**Step 1: Add strangle merge logic**

Replace the return section of `screen_ticker()` (after both CSP and CC scans, around line 281):

```python
    # ── Merge CSP+CC → SHORT_STRANGLE if both found ────────────────────
    if len(recs) == 2 and recs[0]["strategy"] == "CSP" and recs[1]["strategy"] == "CC":
        put_rec, call_rec = recs[0], recs[1]
        combined_credit = put_rec["premium_per_share"] + call_rec["premium_per_share"]
        merged = {
            **put_rec,
            "strategy": "SHORT_STRANGLE",
            "right": "P+C",
            "premium_per_share": round(combined_credit, 2),
            "annual_yield_pct": round(
                combined_credit / put_rec["strike"] * (365 / put_rec["dte"]) * 100, 1
            ),
        }
        recs = [merged]
        labels = [f"STRANGLE {merged['annual_yield_pct']:.1f}%/yr (P${put_rec['strike']:.0f}+C${call_rec['strike']:.0f})"]
        logger.info(f"  ✓ {ticker:8} @ ${price:7.2f}  IV={merged['iv_rank']:.0f}%  HV30={hv30:.0f}%  → {', '.join(labels)}")
    elif recs:
        labels = [f"{r['strategy']} {r['annual_yield_pct']:.1f}%/yr" for r in recs]
        logger.info(f"  ✓ {ticker:8} @ ${price:7.2f}  IV={recs[0]['iv_rank']:.0f}%  HV30={hv30:.0f}%  → {', '.join(labels)}")
    else:
        logger.debug(f"  ✗ {ticker:8} @ ${price:7.2f}  HV30={hv30:.0f}%  — no qualifying strikes")

    return recs
```

**Step 2: Verify compilation**

Run: `python3 -c "import py_compile; py_compile.compile('scripts/market_scan.py', doraise=True); print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add scripts/market_scan.py
git commit -m "fix: merge CSP+CC into SHORT_STRANGLE in market_scan (dedup fix)"
```

---

## Task 7: PWA — `HarvestScanRow` Type + Data Fetch

**Files:**
- Modify: `pwa/src/data.ts`

**Step 1: Add `HarvestScanRow` interface**

Add after `AlpacaPositionRow` interface (~line 798):

```typescript
export interface HarvestScanRow {
  date: string;
  ticker: string;
  strategy: string;
  strike: string;
  expiry: string;
  dte: string;
  credit: string;
  annual_yield_pct: string;
  iv_rank: string;
  conviction: string;
  underlying_last: string;
  cash_required: string;
  breakeven: string;
  sr_context: string;
  macro_regime: string;
  vix: string;
  entry_signals: string;
  maintenance_signals: string;
  exit_signals: string;
  notes: string;
}
```

**Step 2: Add GID placeholder to `GIDS` object**

Add to the `GIDS` object (~line 70):
```typescript
  harvest_scan: "0",  // placeholder — update after first scan run creates the tab
```

**Step 3: Add to `DashboardData` interface**

Add to `DashboardData` (~line 1168):
```typescript
  harvestScan: HarvestScanRow[];
```

**Step 4: Add fetch call**

Add to the second `Promise.all` batch in `fetchDashboard()`:
```typescript
fetchTab<HarvestScanRow>("harvest_scan").catch(() => [] as HarvestScanRow[]),
```

Wire the result into the return object:
```typescript
harvestScan: harvestScanRows,
```

**Step 5: Verify build**

Run: `cd pwa && npx tsc --noEmit`

**Step 6: Commit**

```bash
git add pwa/src/data.ts
git commit -m "feat: add HarvestScanRow type + data fetch to PWA"
```

---

## Task 8: PWA — `HarvestPage.tsx`

**Files:**
- Create: `pwa/src/pages/HarvestPage.tsx`
- Create: `pwa/src/cards/HarvestPicksCard.tsx`

**Step 1: Create `HarvestPicksCard.tsx`**

Follow the pattern of `ScanCard.tsx` — expandable rows with conviction badges:

```typescript
// pwa/src/cards/HarvestPicksCard.tsx
import { useState } from "react";
import type { HarvestScanRow } from "../data";
import { Card } from "./Card";
import { Wheat, ChevronDown, ChevronUp } from "lucide-react";

function convColor(c: number) {
  if (c >= 75) return "text-emerald-400 bg-emerald-500/15 border-emerald-500/30";
  if (c >= 50) return "text-amber-400 bg-amber-500/15 border-amber-500/30";
  return "text-slate-400 bg-slate-500/15 border-slate-500/30";
}

function PickRow({ row }: { row: HarvestScanRow }) {
  const [expanded, setExpanded] = useState(false);
  const conv = Number(row.conviction) || 0;
  const credit = Number(row.credit) || 0;
  const yld = Number(row.annual_yield_pct) || 0;
  const dte = Number(row.dte) || 0;
  const strike = Number(row.strike) || 0;
  const isStrangle = row.strategy === "HARVEST_STRANGLE";

  let maint: Record<string, unknown> = {};
  let exitS: Record<string, unknown> = {};
  try { maint = JSON.parse(row.maintenance_signals || "{}"); } catch { /* */ }
  try { exitS = JSON.parse(row.exit_signals || "{}"); } catch { /* */ }

  return (
    <div
      className="border-b border-white/3 last:border-0 py-2.5 cursor-pointer"
      onClick={() => setExpanded((e) => !e)}
    >
      <div className="flex items-center gap-2">
        <span className="font-bold text-[length:var(--t-sm)]">${row.ticker}</span>
        <span className={`px-1.5 py-0.5 rounded text-[length:var(--t-2xs)] font-bold border ${convColor(conv)}`}>
          {conv}
        </span>
        <span className="text-[length:var(--t-xs)] text-slate-400 ml-auto">
          {isStrangle ? `$${strike.toFixed(0)}P/${row.notes?.replace("call_strike=", "$")}C` : `$${strike.toFixed(0)}P`}
        </span>
        <span className="text-[length:var(--t-xs)] text-emerald-400 font-mono">${credit.toFixed(2)}</span>
        {expanded ? <ChevronUp size={14} className="text-slate-500" /> : <ChevronDown size={14} className="text-slate-500" />}
      </div>
      <div className="flex gap-3 mt-0.5 text-[length:var(--t-2xs)] text-slate-500">
        <span>{dte}d</span>
        <span>{yld.toFixed(0)}% ann</span>
        <span>IVR {Number(row.iv_rank || 0).toFixed(0)}</span>
        {row.sr_context && <span>{row.sr_context}</span>}
      </div>

      {expanded && (
        <div className="mt-2 space-y-1 text-[length:var(--t-2xs)]">
          <div className="text-slate-400">
            📋 <b>Maint:</b> {maint.profit_target_pct}% profit target (optional) · {maint.time_stop_dte} DTE roll · strike tested at {maint.strike_tested_pct}%
          </div>
          <div className="text-slate-400">
            🛑 <b>Exit:</b> stop 2× (${Number(exitS.max_loss_value || 0).toFixed(2)}) · {exitS.mechanical_close_dte} DTE mech close
          </div>
          {isStrangle && (
            <div className="text-amber-400/80">🔀 Strangle: close untested side if one tested</div>
          )}
        </div>
      )}
    </div>
  );
}

export function HarvestPicksCard({ picks }: { picks: HarvestScanRow[] }) {
  if (!picks.length) {
    return (
      <Card icon={Wheat} title="Harvest Picks" subtitle="No picks today">
        <p className="text-[length:var(--t-xs)] text-slate-500 py-4 text-center">
          Scanner found no candidates passing all filters.
        </p>
      </Card>
    );
  }

  const sorted = [...picks].sort((a, b) => Number(b.conviction) - Number(a.conviction));
  return (
    <Card icon={Wheat} title="Harvest Picks" subtitle={`${picks.length} candidates`}>
      {sorted.map((p, i) => <PickRow key={`${p.ticker}-${i}`} row={p} />)}
    </Card>
  );
}
```

**Step 2: Create `HarvestPage.tsx`**

```typescript
// pwa/src/pages/HarvestPage.tsx
import type { HarvestScanRow } from "../data";
import { HarvestPicksCard } from "../cards/HarvestPicksCard";

function MacroBanner({ picks }: { picks: HarvestScanRow[] }) {
  const regime = picks[0]?.macro_regime || "STANDARD";
  const vix = Number(picks[0]?.vix || 0);

  const config: Record<string, { bg: string; text: string; label: string }> = {
    STANDARD: { bg: "bg-emerald-500/10 border-emerald-500/20", text: "text-emerald-400", label: "Harvest active" },
    CAUTION:  { bg: "bg-amber-500/10 border-amber-500/20",   text: "text-amber-400",   label: "Harvest active — reduced sizing" },
    HALTED:   { bg: "bg-red-500/10 border-red-500/20",       text: "text-red-400",      label: "Harvest paused — elevated risk" },
  };
  const c = config[regime] || config.STANDARD;

  return (
    <div className={`rounded-xl border p-3 mb-3 ${c.bg}`}>
      <div className={`font-bold text-[length:var(--t-sm)] ${c.text}`}>{c.label}</div>
      <div className="text-[length:var(--t-2xs)] text-slate-500 mt-0.5">
        {regime} · VIX {vix.toFixed(0)}
      </div>
    </div>
  );
}

export function HarvestPage({
  harvestScan,
  loading,
}: {
  harvestScan: HarvestScanRow[];
  loading: boolean;
}) {
  if (loading && !harvestScan.length) {
    return <div className="px-4 py-8 text-center text-slate-500 text-[length:var(--t-sm)]">Loading…</div>;
  }

  return (
    <div className="flex flex-col px-4 pb-4">
      <div className="fade-up fade-up-1 mt-3">
        <MacroBanner picks={harvestScan} />
      </div>
      <div className="fade-up fade-up-2 mt-1">
        <HarvestPicksCard picks={harvestScan} />
      </div>
    </div>
  );
}
```

**Step 3: Commit**

```bash
git add pwa/src/pages/HarvestPage.tsx pwa/src/cards/HarvestPicksCard.tsx
git commit -m "feat: HarvestPage + HarvestPicksCard PWA components"
```

---

## Task 9: PWA — `InsiderPage.tsx`

**Files:**
- Create: `pwa/src/pages/InsiderPage.tsx`

**Step 1: Create `InsiderPage.tsx`**

Reuses existing `GovConfluenceCard` and `CongressTradesCard`:

```typescript
// pwa/src/pages/InsiderPage.tsx
import type { GovConfluenceRow, CongressTradeRow, InsiderSummary } from "../data";
import { GovConfluenceCard } from "../cards/GovConfluenceCard";
import { CongressTradesCard } from "../cards/CongressTradesCard";
import { Card } from "../cards/Card";
import { Eye, TrendingUp, TrendingDown } from "lucide-react";

function InsiderFlowCard({ insiderByTicker }: { insiderByTicker: Map<string, InsiderSummary> }) {
  const entries = [...insiderByTicker.entries()]
    .filter(([, s]) => s.netBuyValue > 0)
    .sort((a, b) => b[1].netBuyValue - a[1].netBuyValue)
    .slice(0, 10);

  if (!entries.length) {
    return (
      <Card icon={Eye} title="Insider Buys" subtitle="Last 7 days">
        <p className="text-[length:var(--t-xs)] text-slate-500 py-4 text-center">
          No significant insider buying detected.
        </p>
      </Card>
    );
  }

  return (
    <Card icon={Eye} title="Insider Buys" subtitle={`${entries.length} tickers with net buying`}>
      {entries.map(([ticker, summary]) => (
        <div key={ticker} className="flex items-center gap-2 py-2 border-b border-white/3 last:border-0">
          <span className="font-bold text-[length:var(--t-sm)]">${ticker}</span>
          <TrendingUp size={11} className="text-emerald-400" />
          <span className="text-[length:var(--t-xs)] text-emerald-400 ml-auto">
            +${(summary.netBuyValue / 1000).toFixed(0)}K net
          </span>
          <span className="text-[length:var(--t-2xs)] text-slate-500">
            {summary.buyCount} buy{summary.buyCount !== 1 ? "s" : ""}
          </span>
        </div>
      ))}
    </Card>
  );
}

export function InsiderPage({
  govConfluence,
  congressTrades,
  insiderByTicker,
  loading,
}: {
  govConfluence: GovConfluenceRow[];
  congressTrades: CongressTradeRow[];
  insiderByTicker: Map<string, InsiderSummary>;
  loading: boolean;
}) {
  if (loading && !govConfluence.length && !congressTrades.length) {
    return <div className="px-4 py-8 text-center text-slate-500 text-[length:var(--t-sm)]">Loading…</div>;
  }

  return (
    <div className="flex flex-col px-4 pb-4">
      <div className="fade-up fade-up-1 mt-3">
        <GovConfluenceCard signals={govConfluence} />
      </div>
      <div className="fade-up fade-up-2 mt-3">
        <CongressTradesCard trades={congressTrades} />
      </div>
      <div className="fade-up fade-up-3 mt-3">
        <InsiderFlowCard insiderByTicker={insiderByTicker} />
      </div>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add pwa/src/pages/InsiderPage.tsx
git commit -m "feat: InsiderPage PWA — confluence + congress + insider flow cards"
```

---

## Task 10: PWA — Tab Bar + App.tsx Wiring

**Files:**
- Modify: `pwa/src/components/TabBar.tsx`
- Modify: `pwa/src/App.tsx`

**Step 1: Update TabBar — add Harvest + Insider tabs**

In `TabBar.tsx`, update the TABS array (line 4-11):

```typescript
import { Home, Briefcase, CircleDot, Wheat, Landmark, Target, LineChart, Settings } from "lucide-react";

const TABS = [
  { icon: Home,       label: "Home"      },
  { icon: Briefcase,  label: "Portfolio" },
  { icon: CircleDot,  label: "Options"   },
  { icon: Wheat,      label: "Harvest"   },
  { icon: Landmark,   label: "Insider"   },
  { icon: Target,     label: "Decisions" },
  { icon: LineChart,  label: "Review"    },
  { icon: Settings,   label: "Settings"  },
] as const;
```

**Step 2: Update App.tsx — add imports, update TAB_TITLES and SETTINGS_TAB**

Update imports (~line 1-17):
```typescript
import { HarvestPage } from "./pages/HarvestPage";
import { InsiderPage } from "./pages/InsiderPage";
```

Update constants (~line 19-20):
```typescript
const TAB_TITLES = ["Home", "Portfolio", "Options", "Harvest", "Insider", "Decisions", "Review", "Settings"];
const SETTINGS_TAB = 7;
```

**Step 3: Update renderPage switch**

Add cases after Options (case 2) and shift existing cases:

```typescript
      case 3:
        return (
          <HarvestPage
            harvestScan={data?.harvestScan ?? []}
            loading={loading && !data}
          />
        );
      case 4:
        return (
          <InsiderPage
            govConfluence={data?.govConfluence ?? []}
            congressTrades={data?.congressTrades ?? []}
            insiderByTicker={data?.insiderByTicker ?? new Map()}
            loading={loading && !data}
          />
        );
```

Shift Decisions from case 3 → case 5, Review from case 4 → case 6, Settings from case 5 → case 7.

**Step 4: Update badge wiring**

The decision badge and defense badge logic reference tab labels, so they should work automatically with the label-based matching in TabBar.

**Step 5: Verify build**

Run: `cd pwa && npx tsc --noEmit && npm run build`

**Step 6: Commit**

```bash
git add pwa/src/components/TabBar.tsx pwa/src/App.tsx
git commit -m "feat: wire Harvest + Insider tabs into PWA tab bar and routing"
```

---

## Task 11: GitHub Action for `premium_harvest_scan.py`

**Files:**
- Create: `.github/workflows/premium-harvest-scan.yml`

**Step 1: Create workflow file**

Follow the pattern of `.github/workflows/daily-options-scan.yml`:

```yaml
name: Premium Harvest Scan
on:
  schedule:
    - cron: "40 2 * * 1-5"  # 10:40 SGT (UTC+8) Mon-Fri
  workflow_dispatch:

permissions:
  contents: read

jobs:
  scan:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -r requirements.txt
      - run: python scripts/premium_harvest_scan.py
        env:
          GOOGLE_SHEETS_CREDS: ${{ secrets.GOOGLE_SHEETS_CREDS }}
          SHEET_ID: ${{ secrets.SHEET_ID }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_FINANCE_CHAT_ID: ${{ secrets.TELEGRAM_FINANCE_CHAT_ID }}
          FINNHUB_API_KEY: ${{ secrets.FINNHUB_API_KEY }}
```

**Step 2: Add `finvizfinance` to requirements.txt**

```
finvizfinance
```

**Step 3: Commit**

```bash
git add .github/workflows/premium-harvest-scan.yml requirements.txt
git commit -m "ci: add premium harvest scan daily workflow + finvizfinance dep"
```

---

## Task 12: Final Integration Test + Push

**Step 1: Full dry run**

```bash
python3 scripts/premium_harvest_scan.py --dry
```

Expected: Universe → fundamentals → technicals → top picks logged with conviction scores

**Step 2: PWA build**

```bash
cd pwa && npm run build
```

Expected: clean build with no TS errors

**Step 3: Git push**

```bash
git push origin main
```

---

## Summary

| Task | What | Files |
|------|------|-------|
| 1 | HarvestScanRow schema | `src/schema.py` |
| 2 | Layer 1 universe discovery | `scripts/premium_harvest_scan.py` |
| 3 | Layer 2 macro + fundamentals | `scripts/premium_harvest_scan.py` |
| 4 | Layer 3 technicals + signals | `scripts/premium_harvest_scan.py` |
| 5 | Telegram push | `src/telegram.py`, `scripts/premium_harvest_scan.py` |
| 6 | market_scan dedup fix | `scripts/market_scan.py` |
| 7 | PWA data type + fetch | `pwa/src/data.ts` |
| 8 | HarvestPage + card | `pwa/src/pages/HarvestPage.tsx`, `pwa/src/cards/HarvestPicksCard.tsx` |
| 9 | InsiderPage | `pwa/src/pages/InsiderPage.tsx` |
| 10 | TabBar + App wiring | `pwa/src/components/TabBar.tsx`, `pwa/src/App.tsx` |
| 11 | GitHub Action | `.github/workflows/premium-harvest-scan.yml`, `requirements.txt` |
| 12 | Integration test + push | — |
