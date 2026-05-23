# Options Engine Overhaul — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 6 architectural problems in the options scoring/scanning pipeline and integrate research-backed VRP edge improvements from the options knowledge base.

**Architecture:** Upgrade `indicators.py` and `technical_score.py` as the single source of truth. Wire all scanners through unified scoring. Add VRP-aware signals (IV/RV ratio, term structure, earnings gating, Greeks).

**Tech Stack:** Python 3.11, pandas, yfinance, numpy (already in deps). No new dependencies.

**Reference:** `docs/research/options-knowledge-base.md` for research backing.

---

## Problem → Task Mapping

| # | Problem | Task(s) |
|---|---------|---------|
| P1 | Fragmented scoring (3 parallel systems) | T6, T7 |
| P2 | No Greeks beyond delta | T4 |
| P3 | IV Rank approximated / unreliable | T3 |
| P4 | No term structure awareness | T5 |
| P5 | Static delta targets (not VIX-adaptive) | T5 (via term structure DTE selection) |
| P6 | Missing per-ticker earnings gating | T2 |
| R1 | No IV/RV comparison (core VRP edge) | T1 |
| R2 | Close-to-close RV estimator (worst available) | T1 |
| R3 | No vega/theta tracking | T4 |
| R4 | Kelly sizing too aggressive (50% vs literature 5-10%) | T8 |

---

### Task 1: Yang-Zhang RV Estimator + IV/RV Ratio

**Why:** Close-to-close volatility (current `indicators.py:279-284`) is the least efficient RV estimator. Yang-Zhang uses O/H/L/C and handles overnight gaps. IV/RV ratio is the core VRP signal — without it we can't tell if premium is actually rich.

**Files:**
- Modify: `src/indicators.py:279-296` (replace close-to-close with Yang-Zhang)
- Modify: `src/technical_score.py` (add `iv_rv_ratio` signal + strategy weights)

**Step 1: Write the failing test**

Create `tests/test_yang_zhang.py`:
```python
import pandas as pd
import math
from src.indicators import compute_indicators

def test_yang_zhang_rv():
    """Yang-Zhang RV should use O/H/L/C, not just close-to-close."""
    # 30 bars of synthetic data with known volatility
    import numpy as np
    np.random.seed(42)
    n = 60
    close = 100 + np.cumsum(np.random.randn(n) * 2)
    high = close + np.abs(np.random.randn(n)) * 1.5
    low = close - np.abs(np.random.randn(n)) * 1.5
    open_ = close + np.random.randn(n) * 0.5

    df = pd.DataFrame({
        "Open": open_, "High": high, "Low": low,
        "Close": close, "Volume": [1_000_000] * n,
    })
    ind = compute_indicators(df)

    # Must produce volatility_annual using Yang-Zhang
    assert "volatility_annual" in ind
    assert "rv_estimator" in ind
    assert ind["rv_estimator"] == "yang_zhang"
    assert 0 < ind["volatility_annual"] < 3.0  # reasonable range


def test_iv_rv_ratio_signal():
    """IV/RV ratio signal should be positive when IV > RV (premium rich)."""
    from src.technical_score import _sig_iv_rv_ratio
    # IV 40%, RV 25% -> ratio 1.6 -> should be positive (sell premium)
    assert _sig_iv_rv_ratio(0.40, 0.25) > 0
    # IV 20%, RV 35% -> ratio 0.57 -> should be negative (don't sell)
    assert _sig_iv_rv_ratio(0.20, 0.35) < 0
    # IV == RV -> neutral
    assert _sig_iv_rv_ratio(0.30, 0.30) == 0.0
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_yang_zhang.py -v`
Expected: FAIL — `rv_estimator` key missing, `_sig_iv_rv_ratio` doesn't exist.

**Step 3: Implement Yang-Zhang in `indicators.py`**

Replace the close-to-close block at lines 279-284 with:

```python
# ----- Realized Volatility: Yang-Zhang estimator -----
# Uses O/H/L/C; handles overnight gaps; 3-5x more efficient
# than close-to-close (Bennett 2014, OQuants S2).
if len(df) >= 20:
    n_rv = min(30, len(df) - 1)  # 30-day lookback
    o = df["Open"].iloc[-n_rv-1:]
    h = df["High"].iloc[-n_rv-1:]
    l = df["Low"].iloc[-n_rv-1:]
    c = df["Close"].iloc[-n_rv-1:]

    # Overnight returns (close-to-open)
    log_co = (o.iloc[1:] / c.iloc[:-1]).apply(math.log)
    # Open-to-close returns
    log_oc = (c.iloc[1:] / o.iloc[1:]).apply(math.log)
    # Rogers-Satchell component
    log_hc = (h.iloc[1:] / c.iloc[1:]).apply(math.log)
    log_ho = (h.iloc[1:] / o.iloc[1:]).apply(math.log)
    log_lc = (l.iloc[1:] / c.iloc[1:]).apply(math.log)
    log_lo = (l.iloc[1:] / o.iloc[1:]).apply(math.log)

    sigma_o = float(log_co.var())  # overnight variance
    sigma_c = float(log_oc.var())  # close-to-close intraday variance
    sigma_rs = float((log_ho * log_hc + log_lo * log_lc).mean())  # Rogers-Satchell

    k = 0.34 / (1.34 + (n_rv + 1) / (n_rv - 1))
    sigma_yz_sq = sigma_o + k * sigma_c + (1 - k) * sigma_rs
    sigma_yz_sq = max(sigma_yz_sq, 1e-10)

    out["volatility_annual"] = round(math.sqrt(sigma_yz_sq * 252), 4)
    out["rv_estimator"] = "yang_zhang"
else:
    out["volatility_annual"] = 0.0
    out["rv_estimator"] = "insufficient_data"
```

**Step 4: Add IV/RV ratio signal to `technical_score.py`**

Add new signal function:
```python
def _sig_iv_rv_ratio(iv: float, rv: float) -> float:
    """
    IV/RV ratio signal. Core VRP indicator.
    Ratio > 1.0 = IV overpriced (sell premium). Ratio < 1.0 = IV cheap (buy).
    Centred at 1.0, mapped to [-1, +1] with soft clip.
    """
    if rv <= 0 or iv <= 0:
        return 0.0
    ratio = iv / rv
    # Centre at 1.0. Ratio 1.5 -> +1, ratio 0.5 -> -1.
    return max(-1.0, min(1.0, (ratio - 1.0) * 2.0))
```

Add to `compute_signals()`:
```python
"iv_rv_ratio": _sig_iv_rv_ratio(
    ind.get("iv_annual", 0.0),
    ind.get("volatility_annual", 0.0),
),
```

Add to `STRATEGY_WEIGHTS`:
```python
# iv_rv_ratio: positive = IV > RV = rich premium = good for sellers
"BUY":       {"iv_rv_ratio": -1},   # rich premium = expensive options to buy
"CSP":       {"iv_rv_ratio": +6},   # THIS IS THE CORE VRP SIGNAL
"CC":        {"iv_rv_ratio": +5},
"LONG_CALL": {"iv_rv_ratio": -4},   # expensive options bad for buyers
"LONG_PUT":  {"iv_rv_ratio": -3},
```

Add friendly name: `"iv_rv_ratio": "IV/RV"`.

**Step 5: Run tests**

Run: `.venv/bin/python3 -m pytest tests/test_yang_zhang.py tests/test_technical_score.py -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add src/indicators.py src/technical_score.py tests/test_yang_zhang.py
git commit -m "feat: Yang-Zhang RV estimator + IV/RV ratio signal

Replaces close-to-close HV30 (least efficient RV estimator) with
Yang-Zhang (uses O/H/L/C, handles overnight gaps, 3-5x more
efficient per Bennett 2014). Adds IV/RV ratio as core VRP signal
in technical_score.py — this is the primary edge indicator for
premium sellers."
```

---

### Task 2: Per-Ticker Earnings Gating in Harvest Scan

**Why:** Selling premium into earnings is the #1 blowup risk for retail CSP sellers. `fetch_earnings_dates()` already exists in `indicators.py` but harvest scan doesn't use it. The scan has macro-level blackouts (FOMC/CPI) but no per-ticker earnings check.

**Files:**
- Modify: `scripts/premium_harvest_scan.py:297-448` (scan_chain function)
- Modify: `src/technical_score.py` (upgrade `vol_regime` signal)

**Step 1: Write the failing test**

Create `tests/test_earnings_gate.py`:
```python
def test_harvest_rejects_near_earnings():
    """Candidates with earnings inside DTE should be rejected."""
    # Mock: ticker has earnings in 15 days, DTE is 35
    # Should reject because earnings event falls inside option lifetime
    from scripts.premium_harvest_scan import scan_chain
    import logging
    logger = logging.getLogger("test")

    ctx = {"price": 100, "sma20": 101, "sma50": 99, "sma200": 95,
           "rsi_14": 50, "support": 95, "resistance": 105, "hv30": 30, "avg_vol": 1_000_000}
    macro = {"regime": "STANDARD", "vix": 18, "spx_above_200sma": True}

    # With earnings_days_away=15 and DTE_RANGE=(25,45), earnings falls inside option life
    candidates = scan_chain("TEST", ctx, 60, macro, logger, earnings_days_away=15)
    assert len(candidates) == 0 or all(
        c.get("notes", "").startswith("EARNINGS_BLOCKED") for c in candidates
    )
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_earnings_gate.py -v`
Expected: FAIL — `scan_chain` doesn't accept `earnings_days_away` parameter.

**Step 3: Wire earnings check into harvest scan**

In `scan_chain()` function, add parameter and gate:
```python
def scan_chain(ticker: str, ctx: dict, conviction: int, macro: dict,
               logger, earnings_days_away: int = -1) -> list[dict]:
    # ... existing code ...

    # EARNINGS GATE: reject if earnings falls inside option DTE
    if 0 <= earnings_days_away <= dte:
        logger.info(f"  {ticker}: EARNINGS_BLOCKED — earnings in {earnings_days_away}d, DTE={dte}")
        return []
```

In `main()`, fetch earnings dates and pass through:
```python
# After Layer 2 survivors are known, batch-fetch earnings dates
from src.indicators import fetch_earnings_dates
earnings = fetch_earnings_dates(survivors)
# ... in the Layer 3 loop:
ed = earnings.get(ticker, {})
earnings_away = ed.get("earnings_days_away", -1)
picks = scan_chain(ticker, ctx, score, macro, logger, earnings_days_away=earnings_away)
```

**Step 4: Upgrade vol_regime in technical_score.py**

Currently `vol_regime` is set in `indicators.py:274` as "elevated"/"normal" based on recent vol spike. Add `"earnings_approaching"` state:

In `indicators.py`, after the vol_regime block (~line 277), add:
```python
# Override vol_regime if earnings are imminent
# (set externally by scanners that call fetch_earnings_dates)
# The signal function in technical_score.py penalises earnings_approaching
# with weight -1.0 (don't sell options into earnings)
```

**Step 5: Run tests**

Run: `.venv/bin/python3 -m pytest tests/test_earnings_gate.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add scripts/premium_harvest_scan.py src/indicators.py tests/test_earnings_gate.py
git commit -m "feat: per-ticker earnings gating in harvest scan

Blocks CSP candidates when earnings fall inside option DTE.
Uses existing fetch_earnings_dates() from indicators.py.
Selling premium into earnings is the #1 retail CSP blowup."
```

---

### Task 3: Robust IV Rank Computation

**Why:** Current IV Rank uses yfinance's `impliedVolatility` field which is often stale/sparse. IV Rank should compare current IV to a proper 52-week IV history, not a single-chain snapshot.

**Files:**
- Create: `src/iv_rank.py` (standalone module)
- Modify: `src/option_scanner.py:149-157` (replace `_iv_rank` with robust version)
- Modify: `scripts/premium_harvest_scan.py` (use robust IVR)

**Step 1: Write the failing test**

Create `tests/test_iv_rank.py`:
```python
def test_iv_rank_robust():
    """IV Rank should use percentile over 252 trading days of IV history."""
    from src.iv_rank import compute_iv_rank, compute_iv_percentile

    history = list(range(10, 60))  # IV ranged 10-59 over past year
    current = 40.0

    rank = compute_iv_rank(current, history)
    assert 55 < rank < 65  # (40-10)/(59-10) = 61.2

    pctile = compute_iv_percentile(current, history)
    # 30 of 50 values are below 40 -> 60th percentile
    assert 55 < pctile < 65


def test_iv_rank_sparse_history():
    """With < 30 data points, should return -1 (insufficient data)."""
    from src.iv_rank import compute_iv_rank
    assert compute_iv_rank(30.0, [25, 35]) == -1.0
```

**Step 2: Run test to verify fails**

Run: `.venv/bin/python3 -m pytest tests/test_iv_rank.py -v`
Expected: FAIL — `src.iv_rank` doesn't exist.

**Step 3: Create `src/iv_rank.py`**

```python
"""
iv_rank.py — Robust IV Rank and IV Percentile computation.

IV Rank = (current - 52w_low) / (52w_high - 52w_low) * 100
IV Percentile = % of days in lookback where IV was below current

IV Percentile is more robust (not distorted by single extreme).
Both require sufficient history (MIN_HISTORY_DAYS).
"""
from __future__ import annotations

MIN_HISTORY_DAYS = 30


def compute_iv_rank(iv_current: float, iv_history: list[float]) -> float:
    """IV Rank: where current sits in 52w range. Returns 0-100 or -1 if insufficient data."""
    clean = [v for v in iv_history if v and v > 0]
    if len(clean) < MIN_HISTORY_DAYS or iv_current <= 0:
        return -1.0
    lo, hi = min(clean), max(clean)
    if hi <= lo:
        return 50.0
    return round((iv_current - lo) / (hi - lo) * 100, 1)


def compute_iv_percentile(iv_current: float, iv_history: list[float]) -> float:
    """IV Percentile: % of days IV was below current. More robust than rank."""
    clean = [v for v in iv_history if v and v > 0]
    if len(clean) < MIN_HISTORY_DAYS or iv_current <= 0:
        return -1.0
    below = sum(1 for v in clean if v < iv_current)
    return round(below / len(clean) * 100, 1)


def fetch_iv_history(ticker: str, lookback_days: int = 252) -> list[float]:
    """
    Build IV history from yfinance ATM option chain snapshots.
    Falls back to HV-based proxy if chain history unavailable.
    """
    import yfinance as yf
    import math

    try:
        yt = yf.Ticker(ticker)
        # yfinance doesn't provide historical IV directly.
        # Best proxy: compute from current chain + historical price vol.
        hist = yt.history(period="1y", interval="1d", auto_adjust=True)
        if hist.empty or len(hist) < 60:
            return []

        closes = hist["Close"].dropna()
        # Rolling 30-day annualised vol as IV proxy (close-to-close)
        # This is a rough proxy but better than nothing.
        log_rets = closes.pct_change().dropna().apply(lambda x: math.log(1 + x) if x > -1 else 0)
        rolling_vol = log_rets.rolling(30).std() * math.sqrt(252)
        return [round(float(v), 4) for v in rolling_vol.dropna().tolist()]
    except Exception:
        return []
```

**Step 4: Wire into option_scanner.py and harvest scan**

Replace `_iv_rank()` in `option_scanner.py` with import from `src.iv_rank`.
In harvest scan, compute IVR using robust method when available.

**Step 5: Run tests, commit**

---

### Task 4: Greeks Computation (Gamma, Theta, Vega)

**Why:** System only computes delta. For CSP/CC sellers, theta decay profile and vega exposure are more important. Gamma magnitude indicates short-gamma risk.

**Files:**
- Modify: `src/wheel_continuation.py` (add `bs_gamma`, `bs_theta`, `bs_vega` alongside `bs_delta`)
- Modify: `src/option_scanner.py:160-250` (`_scan_one_side` to compute all Greeks)
- Modify: `scripts/daily_options_scan.py` (emit Greeks in scan results)

**Step 1: Write the failing test**

Create `tests/test_greeks.py`:
```python
def test_bs_greeks():
    """All 4 Greeks should compute for a standard ATM put."""
    from src.wheel_continuation import bs_delta, bs_gamma, bs_theta, bs_vega

    S, K, T, sigma, r = 100.0, 100.0, 35/365, 0.30, 0.045
    d = bs_delta(S, K, T, sigma, r, "P")
    g = bs_gamma(S, K, T, sigma, r)
    t = bs_theta(S, K, T, sigma, r, "P")
    v = bs_vega(S, K, T, sigma, r)

    assert -0.55 < d < -0.45   # ATM put delta ~ -0.50
    assert g > 0               # gamma always positive
    assert t < 0               # long option theta negative
    assert v > 0               # long option vega positive
```

**Step 2: Run test to verify fails**

Expected: FAIL — `bs_gamma`, `bs_theta`, `bs_vega` don't exist.

**Step 3: Implement Greeks in `wheel_continuation.py`**

```python
def bs_gamma(S: float, K: float, T: float, sigma: float, r: float) -> float:
    """Black-Scholes gamma (same for calls and puts)."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        # N'(d1) = standard normal PDF at d1
        nprime_d1 = math.exp(-0.5 * d1**2) / math.sqrt(2 * math.pi)
        return nprime_d1 / (S * sigma * math.sqrt(T))
    except (ValueError, ZeroDivisionError):
        return 0.0


def bs_theta(S: float, K: float, T: float, sigma: float, r: float, right: str) -> float:
    """Black-Scholes theta (per calendar day). Negative for long options."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        nprime_d1 = math.exp(-0.5 * d1**2) / math.sqrt(2 * math.pi)
        term1 = -(S * nprime_d1 * sigma) / (2 * math.sqrt(T))
        if right == "C":
            term2 = -r * K * math.exp(-r * T) * _norm_cdf(d2)
            theta_annual = term1 + term2
        else:
            term2 = r * K * math.exp(-r * T) * _norm_cdf(-d2)
            theta_annual = term1 + term2
        return theta_annual / 365  # per calendar day
    except (ValueError, ZeroDivisionError):
        return 0.0


def bs_vega(S: float, K: float, T: float, sigma: float, r: float) -> float:
    """Black-Scholes vega: price change per 1% (0.01) IV change. Same for calls/puts."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        nprime_d1 = math.exp(-0.5 * d1**2) / math.sqrt(2 * math.pi)
        return S * nprime_d1 * math.sqrt(T) / 100  # per 1% IV change
    except (ValueError, ZeroDivisionError):
        return 0.0
```

**Step 4: Wire into `_scan_one_side` in option_scanner.py**

Add gamma/theta/vega to the `best` dict returned by `_scan_one_side`:
```python
gamma = bs_gamma(underlying_last, K, T, vol_for_delta, 0.045)
theta = bs_theta(underlying_last, K, T, vol_for_delta, 0.045, right)
vega = bs_vega(underlying_last, K, T, vol_for_delta, 0.045)
best = {
    ...,
    "gamma": gamma, "theta": theta, "vega": vega,
}
```

**Step 5: Run tests, commit**

---

### Task 5: Term Structure Awareness + Adaptive DTE Selection

**Why:** Harvest picks the single "closest to TARGET_DTE" expiry (line 312-327). No awareness of whether 30 DTE or 45 DTE offers better risk/reward. Term structure slope predicts VRP returns (OQuants S4). Static delta targets don't adapt to VIX regime.

**Files:**
- Modify: `scripts/premium_harvest_scan.py:312-327` (multi-expiry evaluation)
- Add: `src/term_structure.py` (term structure slope computation)
- Modify: `src/technical_score.py` (add `term_structure` signal)

**Step 1: Write the failing test**

Create `tests/test_term_structure.py`:
```python
def test_term_structure_slope():
    """Contango (long > short IV) should produce positive slope signal."""
    from src.term_structure import compute_ts_slope

    # Contango: 30-day IV = 25%, 60-day IV = 30%
    slope = compute_ts_slope(iv_short=0.25, iv_long=0.30, dte_short=30, dte_long=60)
    assert slope > 0  # contango = favorable for short vol

    # Backwardation: 30-day IV = 35%, 60-day IV = 25%
    slope = compute_ts_slope(iv_short=0.35, iv_long=0.25, dte_short=30, dte_long=60)
    assert slope < 0  # backwardation = unfavorable


def test_best_expiry_selection():
    """Should pick expiry with best risk/reward, not just closest to target DTE."""
    from src.term_structure import rank_expiries

    expiries = [
        {"expiry": "2026-06-20", "dte": 28, "atm_iv": 0.35, "credit": 1.50},
        {"expiry": "2026-07-18", "dte": 56, "atm_iv": 0.28, "credit": 2.10},
    ]
    # If term structure is steep backwardation (short IV much higher),
    # shorter expiry captures more VRP per day
    ranked = rank_expiries(expiries, rv_forecast=0.25)
    assert ranked[0]["dte"] == 28  # shorter expiry wins when backwardated
```

**Step 2: Run test to verify fails**

**Step 3: Create `src/term_structure.py`**

```python
"""
term_structure.py — IV term structure analysis.

Computes term structure slope and ranks expiries by VRP-per-day.
Contango (long-term IV > short-term) predicts better short-vol
returns (OQuants S4, Sinclair "Positional Option Trading").
"""
from __future__ import annotations

import math


def compute_ts_slope(iv_short: float, iv_long: float,
                     dte_short: int, dte_long: int) -> float:
    """
    Term structure slope as annualised IV difference per sqrt-day.
    Positive = contango (normal, favorable for short vol).
    Negative = backwardation (stressed, unfavorable).
    """
    if iv_short <= 0 or iv_long <= 0 or dte_short <= 0 or dte_long <= dte_short:
        return 0.0
    # Normalise to annualised basis
    iv_diff = iv_long - iv_short
    time_diff = math.sqrt(dte_long / 365) - math.sqrt(dte_short / 365)
    if time_diff <= 0:
        return 0.0
    return round(iv_diff / time_diff, 4)


def rank_expiries(expiries: list[dict], rv_forecast: float) -> list[dict]:
    """
    Rank expiries by VRP edge per calendar day.

    VRP_per_day = (atm_iv - rv_forecast) / sqrt(dte)
    Captures: shorter DTE with rich IV = more edge per day.
    """
    scored = []
    for e in expiries:
        iv = e.get("atm_iv", 0)
        dte = e.get("dte", 1)
        if iv <= 0 or dte <= 0:
            continue
        vrp_per_day = (iv - rv_forecast) / math.sqrt(dte) if rv_forecast > 0 else 0
        scored.append({**e, "vrp_per_day": round(vrp_per_day, 6)})
    scored.sort(key=lambda x: x["vrp_per_day"], reverse=True)
    return scored
```

**Step 4: Add term_structure signal to `technical_score.py`**

```python
def _sig_term_structure(ts_slope: float) -> float:
    """
    Term structure slope signal.
    Positive slope (contango) = favorable for selling vol.
    Negative (backwardation) = stressed, unfavorable.
    """
    # Typical range [-0.5, +0.5], map to [-1, +1]
    return max(-1.0, min(1.0, ts_slope * 2.0))
```

Add to strategy weights:
```python
"CSP":       {"term_structure": +4},  # contango = better VRP for sellers
"CC":        {"term_structure": +3},
"BUY":       {"term_structure": -1},
"LONG_CALL": {"term_structure": -2},  # contango = expensive long options
"LONG_PUT":  {"term_structure": -1},
```

**Step 5: Modify harvest scan to evaluate multiple expiries**

Replace single-best-expiry logic (lines 312-327) with:
```python
# Evaluate ALL expiries in DTE_RANGE, pick best by VRP-per-day
from src.term_structure import rank_expiries
candidate_expiries = []
for exp_str in expiries:
    exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
    dte = (exp_date - today).days
    if DTE_RANGE[0] <= dte <= DTE_RANGE[1]:
        # Get ATM IV for this expiry (quick chain peek)
        candidate_expiries.append({"expiry": exp_str, "dte": dte, ...})

if candidate_expiries:
    ranked = rank_expiries(candidate_expiries, rv_forecast=hv30/100)
    best_exp = ranked[0]["expiry"]
```

**Step 6: Run tests, commit**

---

### Task 6: Scoring Unification — Harvest Scan Delegates to technical_score.py

**Why:** Harvest scan has its own ad-hoc conviction scoring (base 40 + gates + bonuses, lines 283-294). This duplicates what `technical_score.py` does with 14 weighted signals. Three parallel scoring systems deciding "is this a good CSP?" should be one.

**Files:**
- Modify: `scripts/premium_harvest_scan.py:212-294` (replace `technical_conviction` guts)
- Modify: `scripts/premium_harvest_scan.py:376-384` (replace chain-level conviction bonuses)

**Step 1: Refactor `technical_conviction()` to use `compute_scores()`**

```python
def technical_conviction(ticker: str, logger) -> tuple[bool, int, dict]:
    """Technical gates + conviction score via unified scoring engine."""
    import yfinance as yf
    from src.indicators import compute_indicators
    from src.technical_score import compute_scores, score_label

    try:
        yt = yf.Ticker(ticker)
        hist = yt.history(period="250d", interval="1d", auto_adjust=True)
        if hist.empty or len(hist) < 50:
            return False, 0, {}
    except Exception:
        return False, 0, {}

    # Compute full indicator suite
    ind = compute_indicators(hist)
    price = ind.get("close", 0)
    if price <= 0:
        return False, 0, {}

    # Hard gates (non-negotiable)
    sma50 = ind.get("sma_50", 0)
    sma200 = ind.get("sma_200", 0)
    rsi = ind.get("rsi_14", 50)
    support = ind.get("support", 0)
    avg_vol = ind.get("vol_avg_20", 0)

    if sma50 > 0 and price < sma50:
        return False, 0, ind
    if sma200 > 0 and price < sma200:
        return False, 0, ind
    if rsi < 30 or rsi > 75:
        return False, 0, ind
    if support > 0 and price < support * 1.03:
        return False, 0, ind
    if avg_vol < 200_000:
        return False, 0, ind

    # UNIFIED SCORING: use technical_score.py CSP score
    scores = compute_scores(ind)
    csp_score = scores.get("CSP", 0)

    # Map CSP score [-100, +100] to conviction [0, 100]
    conviction = max(0, min(100, int((csp_score + 100) / 2)))

    ctx = {
        "price": round(price, 2),
        "sma20": round(ind.get("sma_20", 0), 2),
        "sma50": round(sma50, 2),
        "sma200": round(sma200, 2),
        "rsi_14": round(rsi, 1),
        "support": round(support, 2),
        "resistance": round(ind.get("resistance", 0), 2),
        "hv30": round(ind.get("volatility_annual", 0) * 100, 1),
        "avg_vol": int(avg_vol),
    }

    return True, conviction, ctx
```

**Step 2: Remove duplicate chain-level conviction bonuses**

The iv_rich_bonus, oi_bonus, spread_bonus (lines 376-384) should be absorbed into the composite score from `option_scanner.py`'s `compute_composite()`, not hand-rolled.

**Step 3: Run existing tests + new integration test**

**Step 4: Commit**

```bash
git commit -m "refactor: unify harvest scoring through technical_score.py

Harvest scan conviction now delegates to compute_scores() CSP score
instead of ad-hoc base-40 + gates system. One scoring engine for
all option strategy decisions."
```

---

### Task 7: Scoring Unification — Daily Scan Delegates to technical_score.py

**Why:** `daily_options_scan.py` has yet another parallel quality scoring. Wire it through the same `compute_scores()` + `compute_composite()` pipeline.

**Files:**
- Modify: `scripts/daily_options_scan.py` (quality score → composite via option_scanner)

**Step 1:** Replace each strategy's ad-hoc quality score with `compute_scores()` for the strategy-specific score, then `compute_composite()` for the chain-level composite.

**Step 2:** Ensure the scan_results output includes the unified score.

**Step 3:** Run tests, commit.

---

### Task 8: Kelly Sizing Recalibration

**Why:** Current `option_scanner.py` uses Half-Kelly (50% of full Kelly). Research consensus (OQuants S4, Sinclair) is 5-10% of Kelly for VRP trades. We may be oversized.

**Files:**
- Modify: `src/option_scanner.py:49-53, 288-311` (HALF_KELLY_FRACTION and `_half_kelly_size`)

**Step 1:** Change `HALF_KELLY_FRACTION = 0.5` to `FRACTIONAL_KELLY = 0.10` (10% of Kelly as starting point).

**Step 2:** Rename function to `_fractional_kelly_size` for clarity.

**Step 3:** Add configurable `KELLY_FRACTION` constant with documentation:

```python
# Position sizing: Fractional Kelly
# Full Kelly: maximizes terminal wealth but 48%+ max drawdown.
# Half-Kelly (0.50): 25% max drawdown (traditional).
# 5-10% of Kelly: recommended for VRP/short-vol trades where
# return distribution has fat tails (Sinclair, OQuants S4).
KELLY_FRACTION = 0.10  # 10% of full Kelly
```

**Step 4:** Run tests, commit.

---

## Dependency Graph

```
T1 (Yang-Zhang + IV/RV) ─────────────────────┐
T2 (Earnings gating) ────────────────────────│
T3 (Robust IV Rank) ─────────────────────────┤
T4 (Greeks: gamma/theta/vega) ───────────────┤
T5 (Term structure + adaptive DTE) ──────────┤
                                              ├─→ T6 (Unify harvest) ──→ T7 (Unify daily scan)
T8 (Kelly recalibration) ────────────────────┘
```

T1-T5 and T8 are independent of each other. T6 depends on T1 being done (needs IV/RV signal in `compute_scores()`). T7 depends on T6 (same pattern).

**Recommended execution order:** T2 → T1 → T3 → T4 → T5 → T8 → T6 → T7

Rationale: T2 (earnings gating) is highest defensive value, simplest to implement. T1 (VRP core) is highest edge value. T6/T7 (unification) go last because they benefit from all new signals being available.

---

## Validation

After all 8 tasks:
1. Run full test suite: `.venv/bin/python3 -m pytest tests/ -v`
2. Dry-run harvest scan: `.venv/bin/python3 scripts/premium_harvest_scan.py --dry --top 10`
3. Dry-run daily scan: `.venv/bin/python3 scripts/daily_options_scan.py --dry`
4. Verify Telegram format unchanged (signal blocks should include new fields)
5. Verify PWA HarvestPicksCard still renders (schema backward-compatible)
