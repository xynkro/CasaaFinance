# Credit Spread Exit Management + Support/Resistance Entry Timing

**Date:** 2026-05-15
**Status:** Building

## Gap 1: Credit Spread Exit Management

### Problem
`exit_plan.py` only handles single-leg options (CSP/CC). PCS/CCS/IC positions scanned by `daily_options_scan.py` have no profit tracking, dynamic stop, or rolling trigger.

### Design: `compute_spread_exit_plan()` in `exit_plan.py`

**Dynamic stop trailing (3 phases):**
- Phase INITIAL (profit < 25%): stop at loss = 1× credit received (spread doubles)
- Phase TRAILING_BE (profit 25-50%): stop at breakeven
- Phase TAKE_PROFIT (profit ≥ 50%): close, or trail to lock 25% min profit

**Mechanical rules:**
- 21 DTE close regardless of P&L (gamma acceleration)
- 50% profit target (buy back at half of credit)
- 75%+ profit: close immediately
- Short strike tested (price within 2%): flag ROLL_OR_CLOSE
- Earnings inside DTE: CATALYST_WARNING

**Return dict:** status, recommendation, reasoning, profit_capture_pct, stop_value, stop_phase, width, max_loss

### Integration
- `daily_tracker.py` detects spread pairs from IBKR grab (same ticker/expiry/right, opposite qty)
- Routes detected spreads through `compute_spread_exit_plan()` instead of single-leg plan
- Includes spread exit plans in defense brief and Telegram alerts

## Gap 2: Support/Resistance Entry Timing

### Problem
`daily_options_scan.py` scores PCS/CCS candidates purely on credit ratio + IVR. Doesn't check whether price is near support (ideal for PCS) or resistance (ideal for CCS).

### Design: `_technical_context()` helper + scoring bonus

**New helper** replaces `_hv30()` — computes HV30 + RSI-14 + 20d support/resistance from the same 60d history fetch:
- Support = 20d rolling low
- Resistance = 20d rolling high
- RSI-14 standard calculation

**PCS bonus:**
- Price within 3% above support → +15 composite score
- RSI < 35 (oversold confirmation) → +10 bonus
- Appended to `notes` field for Telegram visibility

**CCS bonus:**
- Price within 3% below resistance → +15 composite score
- RSI > 65 (overbought confirmation) → +10 bonus

**IC bonus:**
- Both conditions checked independently for each side
- +8 bonus if both sides have favorable S/R context

No new dependencies. Same yfinance data already fetched.
