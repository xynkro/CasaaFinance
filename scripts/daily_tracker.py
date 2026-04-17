"""
daily_tracker.py — Fetch current prices from Yahoo Finance using last-known
positions, calculate portfolio values, and push daily snapshots + macro to the
Sheet.  No IBKR connection needed — just internet.

How it works:
  1. Reads the most recent PortfolioGrab JSON for holdings (tickers, qty, avg_cost)
     and last-known cash balances.
  2. Fetches live prices via yfinance for every ticker.
  3. Calculates mkt_val, UPL, net_liq per account.
  4. Fetches macro data (VIX, SPX, DXY, US 10Y, USD/SGD).
  5. Builds options rows with moneyness, DTE, assignment risk, wheel stage.
  6. Pushes snapshot, positions, options, and macro rows to the Sheet.

Usage:
  python scripts/daily_tracker.py              # fetch + push
  python scripts/daily_tracker.py --dryrun     # fetch + print, no push
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GRAB_DIR = ROOT / "PortfolioGrabs"

# SGX tickers need .SI suffix for Yahoo Finance
SGX_TICKERS = {"C6L", "G3B", "ES3"}

# Macro symbols on Yahoo Finance
MACRO_SYMBOLS = {
    "vix":     "^VIX",
    "spx":     "^GSPC",
    "dxy":     "DX-Y.NYB",
    "us_10y":  "^TNX",
    "usd_sgd": "USDSGD=X",
}


def yahoo_ticker(symbol: str) -> str:
    """Convert our ticker to Yahoo Finance symbol."""
    s = symbol.upper()
    if s in SGX_TICKERS:
        return f"{s}.SI"
    return s


def find_latest_grab() -> Path | None:
    """Find the most recent PortfolioGrab JSON."""
    if not GRAB_DIR.exists():
        return None
    grabs = sorted(GRAB_DIR.glob("*_PortfolioGrab.json"))
    return grabs[-1] if grabs else None


def fetch_prices(tickers: list[str]) -> dict[str, float]:
    """Fetch current/last-close prices for a list of tickers via yfinance."""
    import yfinance as yf

    yahoo_syms = [yahoo_ticker(t) for t in tickers]
    result: dict[str, float] = {}

    # Batch download — much faster than one-by-one
    data = yf.download(yahoo_syms, period="1d", progress=False, threads=True)

    if data.empty:
        print("  Warning: yfinance returned no data")
        return result

    # yf.download returns a DataFrame with MultiIndex columns when multiple tickers
    close = data.get("Close")
    if close is None:
        return result

    for orig, ysym in zip(tickers, yahoo_syms):
        try:
            if len(yahoo_syms) == 1:
                # Single ticker: Close is a Series
                val = float(close.dropna().iloc[-1])
            else:
                # Multi ticker: Close is a DataFrame with ticker columns
                col = close[ysym] if ysym in close.columns else None
                if col is not None:
                    val = float(col.dropna().iloc[-1])
                else:
                    val = 0.0
            result[orig] = val
        except (KeyError, IndexError):
            print(f"  Warning: no price for {orig} ({ysym})")
            result[orig] = 0.0

    return result


def fetch_macro() -> dict[str, float]:
    """Fetch macro indicators from Yahoo Finance."""
    import yfinance as yf

    symbols = list(MACRO_SYMBOLS.values())
    result: dict[str, float] = {}

    data = yf.download(symbols, period="1d", progress=False, threads=True)
    if data.empty:
        return result

    close = data.get("Close")
    if close is None:
        return result

    for key, ysym in MACRO_SYMBOLS.items():
        try:
            if len(symbols) == 1:
                val = float(close.dropna().iloc[-1])
            else:
                col = close[ysym] if ysym in close.columns else None
                val = float(col.dropna().iloc[-1]) if col is not None else 0.0
            result[key] = round(val, 4)
        except (KeyError, IndexError):
            result[key] = 0.0

    return result


def build_snapshots(grab: dict, prices: dict[str, float], macro: dict[str, float]):
    """Build schema rows from grab + live prices."""
    from src import schema as S

    date = datetime.now().strftime("%Y-%m-%d")
    usd_sgd = macro.get("usd_sgd", 1.0) or 1.0

    results = {"date": date}

    for acct_key, snap_cls, pos_tab in [
        ("caspar", S.SnapshotCaspar, "positions_caspar"),
        ("sarah",  S.SnapshotSarah, "positions_sarah"),
    ]:
        acct = grab.get("accounts", {}).get(acct_key, {})
        summary = acct.get("summary", {})
        positions_raw = acct.get("positions", [])

        # Cash: use last known value
        if acct_key == "caspar":
            cash = float(summary.get("total_cash", 0))
        else:
            cash = float(summary.get("total_cash_sgd", 0))

        # Build position rows with live prices
        pos_rows = []
        total_mkt_val = 0.0
        total_upl = 0.0

        for p in positions_raw:
            symbol = p.get("symbol", "")
            qty = float(p.get("qty", 0))
            avg_cost = float(p.get("avg_cost", 0))
            last = prices.get(symbol, float(p.get("last", 0)))

            # For SGX stocks in Sarah's account: price is in SGD already from Yahoo .SI
            # For US stocks in Sarah's account: price is in USD, mkt_val in USD
            # Sarah's net_liq is reported in SGD by IBKR — we'll approximate by
            # converting USD positions using usd_sgd rate
            mkt_val = qty * last
            upl = (last - avg_cost) * qty

            # Sarah: convert USD-denominated positions to SGD for aggregation
            if acct_key == "sarah" and symbol not in SGX_TICKERS:
                mkt_val_sgd = mkt_val * usd_sgd
                upl_sgd = upl * usd_sgd
            else:
                mkt_val_sgd = mkt_val
                upl_sgd = upl

            if acct_key == "sarah":
                total_mkt_val += mkt_val_sgd
                total_upl += upl_sgd
            else:
                total_mkt_val += mkt_val
                total_upl += upl

            pos_rows.append(S.PositionRow(
                date=date,
                ticker=symbol,
                qty=qty,
                avg_cost=avg_cost,
                last=last,
                mkt_val=mkt_val,
                upl=upl,
                weight=0.0,  # calculated after net_liq is known
            ))

        net_liq = total_mkt_val + cash
        upl_pct = total_upl / net_liq if net_liq else 0.0

        # Back-fill weights
        for pr in pos_rows:
            if net_liq > 0:
                pr.weight = abs(pr.mkt_val) / net_liq if acct_key == "caspar" else abs(pr.mkt_val * (usd_sgd if pr.ticker not in SGX_TICKERS else 1.0)) / net_liq

        if acct_key == "caspar":
            snap = S.SnapshotCaspar(date=date, net_liq_usd=net_liq, cash=cash, upl=total_upl, upl_pct=upl_pct)
        else:
            snap = S.SnapshotSarah(date=date, net_liq_sgd=net_liq, cash_sgd=cash, upl_sgd=total_upl, upl_pct=upl_pct)

        results[f"snap_{acct_key}"] = snap
        results[f"pos_{acct_key}"] = pos_rows

    # Macro row
    results["macro"] = S.MacroRow(
        date=date,
        vix=macro.get("vix"),
        dxy=macro.get("dxy"),
        us_10y=macro.get("us_10y"),
        spx=macro.get("spx"),
        usd_sgd=macro.get("usd_sgd"),
    )

    return results


def calc_moneyness(right: str, strike: float, underlying: float) -> str:
    """Calculate ITM/ATM/OTM based on option type and underlying price."""
    if underlying <= 0 or strike <= 0:
        return "?"
    pct_diff = abs(underlying - strike) / strike
    if pct_diff < 0.02:  # within 2% of strike
        return "ATM"
    if right == "C":
        return "ITM" if underlying > strike else "OTM"
    else:  # put
        return "ITM" if underlying < strike else "OTM"


def calc_dte(expiry: str) -> int:
    """Days to expiry from YYYYMMDD string."""
    try:
        exp_date = datetime.strptime(expiry, "%Y%m%d").date()
        return max(0, (exp_date - date.today()).days)
    except (ValueError, TypeError):
        return -1


def calc_assignment_risk(moneyness: str, dte: int, trend_risk: str = "") -> str:
    """Assignment risk based on moneyness + time to expiry + trend."""
    if moneyness == "ITM":
        if dte <= 7 or trend_risk == "BREACHING":
            return "HIGH"
        elif dte <= 21 or trend_risk == "CONVERGING":
            return "MED"
        else:
            return "LOW"
    elif moneyness == "ATM":
        if dte <= 7 or trend_risk in ("BREACHING", "CONVERGING"):
            return "MED"
        else:
            return "LOW"
    elif trend_risk == "CONVERGING" and dte <= 14:
        return "MED"
    return "LOW"  # OTM


def fetch_indicators(tickers: list[str]) -> dict[str, dict]:
    """Fetch 1-year prices for option underlyings and compute indicators:
    momentum (5d, 20d), annualized volatility, SMA20/50, RSI14."""
    import yfinance as yf

    if not tickers:
        return {}

    yahoo_syms = [yahoo_ticker(t) for t in tickers]
    result: dict[str, dict] = {}

    data = yf.download(yahoo_syms, period="1y", progress=False, threads=True)
    if data.empty:
        return {t: {} for t in tickers}

    close = data.get("Close")
    if close is None:
        return {t: {} for t in tickers}

    for orig, ysym in zip(tickers, yahoo_syms):
        ind: dict = {}
        try:
            if len(yahoo_syms) == 1:
                series = close.dropna()
            else:
                col = close[ysym] if ysym in close.columns else None
                series = col.dropna() if col is not None else None

            if series is None or len(series) < 20:
                result[orig] = {}
                continue

            # Momentum
            if len(series) >= 6:
                ind["momentum_5d"] = round(
                    (float(series.iloc[-1]) - float(series.iloc[-6])) / float(series.iloc[-6]) * 100, 2
                )
            if len(series) >= 21:
                ind["momentum_20d"] = round(
                    (float(series.iloc[-1]) - float(series.iloc[-21])) / float(series.iloc[-21]) * 100, 2
                )

            # Volatility (annualized from daily returns)
            returns = series.pct_change().dropna()
            if len(returns) >= 10:
                daily_vol = float(returns.std())
                ind["volatility_annual"] = round(daily_vol * math.sqrt(252), 4)

            # SMAs
            if len(series) >= 20:
                ind["sma_20"] = round(float(series.iloc[-20:].mean()), 4)
            if len(series) >= 50:
                ind["sma_50"] = round(float(series.iloc[-50:].mean()), 4)

            # RSI-14 (classic formula)
            if len(series) >= 15:
                delta = series.diff().dropna()
                gains = delta.where(delta > 0, 0).iloc[-14:].mean()
                losses = -delta.where(delta < 0, 0).iloc[-14:].mean()
                if losses > 0:
                    rsi = 100 - (100 / (1 + gains / losses))
                else:
                    rsi = 100.0 if gains > 0 else 50.0
                ind["rsi_14"] = round(float(rsi), 1)

        except (KeyError, IndexError, ValueError):
            pass

        result[orig] = ind

    return result


def _norm_cdf(x: float) -> float:
    """Standard normal CDF."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_prob_itm(S: float, K: float, T: float, sigma: float, r: float, right: str) -> float:
    """Black-Scholes probability of finishing ITM at expiry (risk-neutral)."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.5
    try:
        d2 = (math.log(S / K) + (r - 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    except (ValueError, ZeroDivisionError):
        return 0.5
    if right == "C":
        return _norm_cdf(d2)
    else:
        return _norm_cdf(-d2)


def calc_confidence(
    right: str,
    strike: float,
    underlying: float,
    dte: int,
    sigma_annual: float,
    momentum_5d: float,
    rsi_14: float,
    sma_20: float,
    sma_50: float,
    vix: float,
) -> tuple[int, str]:
    """
    Compute confidence % of assignment (0-100) with reasoned explanation.
    Combines: Black-Scholes N(d2) base probability + momentum + RSI + SMA trend + VIX.
    """
    if underlying <= 0 or strike <= 0 or dte < 0:
        return (50, "insufficient data")

    # Base: Black-Scholes probability of finishing ITM
    T = max(dte, 1) / 365.0
    sigma = sigma_annual if sigma_annual > 0 else 0.4  # fallback to 40% if unknown
    r = 0.045
    base_prob = bs_prob_itm(underlying, strike, T, sigma, r, right)
    base_pct = base_prob * 100

    # Momentum adjustment (-10 to +15)
    mom_adj = 0.0
    if right == "C":
        if momentum_5d > 3:
            mom_adj = min(15, momentum_5d * 0.8)
        elif momentum_5d < -3:
            mom_adj = max(-10, momentum_5d * 0.5)
    else:  # P
        if momentum_5d < -3:
            mom_adj = min(15, abs(momentum_5d) * 0.8)
        elif momentum_5d > 3:
            mom_adj = max(-10, -momentum_5d * 0.5)

    # Trend alignment (SMA20 vs SMA50) — small adjustment
    trend_adj = 0.0
    trend_label = ""
    if sma_20 > 0 and sma_50 > 0:
        uptrend = sma_20 > sma_50
        if right == "C":
            trend_adj = 5 if uptrend else -5
            trend_label = "uptrend" if uptrend else "downtrend"
        else:
            trend_adj = -5 if uptrend else 5
            trend_label = "uptrend" if uptrend else "downtrend"

    # RSI overbought/oversold — contrarian signal
    rsi_adj = 0.0
    rsi_label = ""
    if rsi_14 > 70:
        rsi_label = f"RSI {rsi_14:.0f} overbought"
        rsi_adj = -4 if right == "C" else 3
    elif rsi_14 < 30:
        rsi_label = f"RSI {rsi_14:.0f} oversold"
        rsi_adj = 3 if right == "C" else -4

    # VIX — higher = wider distribution (slightly more assignment uncertainty both ways)
    vix_adj = 0.0
    if vix > 25:
        vix_adj = 3
    elif vix < 14:
        vix_adj = -2

    raw = base_pct + mom_adj + trend_adj + rsi_adj + vix_adj
    confidence = int(max(0, min(100, round(raw))))

    # Reasoning string
    dist_pct = (underlying - strike) / strike * 100
    parts = []
    parts.append(f"BS {base_pct:.0f}%")
    if right == "C":
        if dist_pct > 0:
            parts.append(f"stock ${underlying:.2f} is {dist_pct:.1f}% above strike (ITM)")
        else:
            parts.append(f"${underlying:.2f} is {abs(dist_pct):.1f}% below ${strike:.0f} strike")
    else:
        if dist_pct < 0:
            parts.append(f"${underlying:.2f} is {abs(dist_pct):.1f}% below strike (ITM)")
        else:
            parts.append(f"${underlying:.2f} is {dist_pct:.1f}% above ${strike:.0f} strike")
    parts.append(f"{dte}d DTE")
    parts.append(f"σ {sigma * 100:.0f}%")
    if abs(momentum_5d) > 2:
        direction = "toward" if mom_adj > 0 else "away"
        parts.append(f"5d momentum {momentum_5d:+.1f}% {direction}")
    if rsi_label:
        parts.append(rsi_label)
    if trend_label:
        parts.append(trend_label)
    if vix > 25:
        parts.append(f"VIX {vix:.0f} elevated")

    return confidence, " · ".join(parts)


def calc_trend_risk(right: str, strike: float, underlying: float, momentum_5d: float, is_short: bool) -> str:
    """Assess whether price momentum is pushing toward assignment."""
    if underlying <= 0 or strike <= 0:
        return "?"
    dist_pct = (underlying - strike) / strike * 100  # positive = above strike

    if is_short:
        # Short call: danger if price trending UP toward/past strike
        if right == "C":
            if dist_pct > 2 and momentum_5d > 1:        # already ITM & going deeper
                return "BREACHING"
            elif dist_pct > -5 and momentum_5d > 1.5:    # close & accelerating up
                return "CONVERGING"
            elif momentum_5d > 2 and dist_pct > -10:     # strong uptrend
                return "DRIFTING"
            return "SAFE"
        # Short put: danger if price trending DOWN toward/past strike
        else:
            if dist_pct < -2 and momentum_5d < -1:       # already ITM & going deeper
                return "BREACHING"
            elif dist_pct < 5 and momentum_5d < -1.5:    # close & accelerating down
                return "CONVERGING"
            elif momentum_5d < -2 and dist_pct < 10:     # strong downtrend
                return "DRIFTING"
            return "SAFE"
    else:
        # Long positions: reverse logic (you WANT ITM)
        if right == "C":
            if dist_pct > 2 and momentum_5d > 0:
                return "SAFE"          # profitable & trending right
            elif momentum_5d < -1.5:
                return "DRIFTING"      # moving away from profit
            return "SAFE"
        else:
            if dist_pct < -2 and momentum_5d < 0:
                return "SAFE"
            elif momentum_5d > 1.5:
                return "DRIFTING"
            return "SAFE"


def build_options(grab: dict, prices: dict[str, float], indicators: dict[str, dict], macro: dict[str, float], today: str):
    """Build option rows with moneyness, wheel stage, and adjusted cost basis."""
    from src import schema as S

    option_rows = []

    for acct_key in ("caspar", "sarah"):
        acct = grab.get("accounts", {}).get(acct_key, {})
        options_raw = acct.get("options", [])
        positions_raw = acct.get("positions", [])

        if not options_raw:
            continue

        # Build stock holdings map: ticker -> {qty, avg_cost}
        stock_map = {}
        for p in positions_raw:
            sym = p.get("symbol", "")
            stock_map[sym] = {
                "qty": float(p.get("qty", 0)),
                "avg_cost": float(p.get("avg_cost", 0)),
            }

        # Accumulate total credits per ticker from current options
        # (for adj_cost_basis = stock_avg_cost - premiums_per_share)
        ticker_credits: dict[str, float] = {}
        for opt in options_raw:
            sym = opt.get("symbol", "")
            credit = float(opt.get("avg_cost_credit", 0))
            mult = int(opt.get("multiplier", 100))
            # credit is per-share cost from IBKR (avg_cost_credit / multiplier gives per-share premium)
            credit_per_share = credit / mult if mult else credit / 100
            if opt.get("qty", 0) < 0:  # short = sold = credit received
                ticker_credits[sym] = ticker_credits.get(sym, 0) + credit_per_share

        for opt in options_raw:
            sym = opt.get("symbol", "")
            right = opt.get("right", "C")
            strike = float(opt.get("strike", 0))
            expiry = opt.get("expiry", "")
            qty = float(opt.get("qty", 0))
            credit = float(opt.get("avg_cost_credit", 0))
            mult = int(opt.get("multiplier", 100))
            last_opt = float(opt.get("last", 0))
            mkt_val = float(opt.get("mkt_val", 0))
            upl = float(opt.get("upl", 0))

            # Underlying price from Yahoo (live)
            underlying_last = prices.get(sym, 0.0)

            moneyness = calc_moneyness(right, strike, underlying_last)
            dte = calc_dte(expiry)
            is_short = qty < 0
            ind = indicators.get(sym, {})
            mom_5d = ind.get("momentum_5d", 0.0)
            vol_annual = ind.get("volatility_annual", 0.0)
            rsi_14 = ind.get("rsi_14", 50.0)
            sma_20 = ind.get("sma_20", 0.0)
            sma_50 = ind.get("sma_50", 0.0)
            vix = macro.get("vix", 18.0) or 18.0
            trend = calc_trend_risk(right, strike, underlying_last, mom_5d, is_short)
            assignment_risk = calc_assignment_risk(moneyness, dte, trend)
            confidence_pct, confidence_reasoning = calc_confidence(
                right, strike, underlying_last, dte,
                vol_annual, mom_5d, rsi_14, sma_20, sma_50, vix,
            )

            # Determine wheel leg
            has_stock = sym in stock_map and stock_map[sym]["qty"] > 0
            if qty < 0 and right == "C" and has_stock:
                wheel_leg = "CC"  # covered call
            elif qty < 0 and right == "P":
                wheel_leg = "CSP"  # cash-secured put
            elif qty < 0 and right == "C" and not has_stock:
                wheel_leg = "NAKED_CALL"
            elif qty > 0 and right == "C":
                wheel_leg = "LONG_CALL"
            elif qty > 0 and right == "P":
                wheel_leg = "LONG_PUT"
            else:
                wheel_leg = "OTHER"

            # Adjusted cost basis: stock avg_cost - premiums collected
            stock_info = stock_map.get(sym)
            if stock_info and stock_info["qty"] > 0:
                total_credit_per_share = ticker_credits.get(sym, 0)
                adj_cost_basis = stock_info["avg_cost"] - total_credit_per_share
            else:
                adj_cost_basis = 0.0

            option_rows.append(S.OptionRow(
                date=today,
                account=acct_key,
                ticker=sym,
                right=right,
                strike=strike,
                expiry=expiry,
                qty=qty,
                credit=credit / mult if mult else credit / 100,
                last=last_opt,
                mkt_val=mkt_val,
                upl=upl,
                underlying_last=underlying_last,
                moneyness=moneyness,
                dte=dte,
                assignment_risk=assignment_risk,
                wheel_leg=wheel_leg,
                adj_cost_basis=adj_cost_basis,
                momentum_5d=mom_5d,
                trend_risk=trend,
                confidence_pct=confidence_pct,
                confidence_reasoning=confidence_reasoning,
                volatility_annual=vol_annual,
                rsi_14=rsi_14,
                sma_20=sma_20,
                sma_50=sma_50,
            ))

    return option_rows


def push_to_sheet(results: dict):
    """Push all rows to sheet."""
    from src import schema as S, sheets as sh
    from src.sync import load_env
    load_env()
    client = sh.authenticate()

    snap_c = results["snap_caspar"]
    sh.ensure_headers(client, S.SnapshotCaspar.TAB_NAME, S.SnapshotCaspar.HEADERS)
    sh.append_row(client, S.SnapshotCaspar.TAB_NAME, snap_c.to_row())

    pos_c = results["pos_caspar"]
    sh.ensure_headers(client, "positions_caspar", S.PositionRow.HEADERS)
    sh.append_rows(client, "positions_caspar", [p.to_row() for p in pos_c])

    snap_s = results["snap_sarah"]
    sh.ensure_headers(client, S.SnapshotSarah.TAB_NAME, S.SnapshotSarah.HEADERS)
    sh.append_row(client, S.SnapshotSarah.TAB_NAME, snap_s.to_row())

    pos_s = results["pos_sarah"]
    sh.ensure_headers(client, "positions_sarah", S.PositionRow.HEADERS)
    sh.append_rows(client, "positions_sarah", [p.to_row() for p in pos_s])

    # Options
    opts = results.get("options", [])
    if opts:
        sh.ensure_headers(client, S.OptionRow.TAB_NAME, S.OptionRow.HEADERS)
        sh.append_rows(client, S.OptionRow.TAB_NAME, [o.to_row() for o in opts])

    macro = results["macro"]
    sh.ensure_headers(client, S.MacroRow.TAB_NAME, S.MacroRow.HEADERS)
    sh.append_row(client, S.MacroRow.TAB_NAME, macro.to_row())

    print(f"  Pushed: snapshot_caspar, {len(pos_c)} caspar positions, "
          f"snapshot_sarah, {len(pos_s)} sarah positions, "
          f"{len(opts)} options, macro")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dryrun", action="store_true", help="Fetch and print only, don't push to sheet")
    ap.add_argument("--grab", type=str, help="Path to specific grab JSON (default: latest)")
    args = ap.parse_args()

    # Find grab file
    if args.grab:
        grab_path = Path(args.grab)
    else:
        grab_path = find_latest_grab()
    if not grab_path or not grab_path.exists():
        print(f"No grab file found in {GRAB_DIR}")
        print("Run `python src/ibkr_grab.py` at least once to capture positions.")
        return 1

    print(f"Using positions from: {grab_path.name}")
    grab = json.loads(grab_path.read_text())

    # Collect all tickers (stocks + option underlyings)
    all_tickers = set()
    for acct in ("caspar", "sarah"):
        acct_data = grab.get("accounts", {}).get(acct, {})
        for p in acct_data.get("positions", []):
            all_tickers.add(p["symbol"])
        for o in acct_data.get("options", []):
            all_tickers.add(o["symbol"])  # underlying ticker

    print(f"Fetching prices for {len(all_tickers)} tickers...")
    prices = fetch_prices(list(all_tickers))
    print(f"  Got prices for {sum(1 for v in prices.values() if v > 0)}/{len(all_tickers)} tickers")

    print("Fetching macro data...")
    macro = fetch_macro()
    for k, v in macro.items():
        print(f"  {k}: {v}")

    print("Building snapshots...")
    results = build_snapshots(grab, prices, macro)

    snap_c = results["snap_caspar"]
    snap_s = results["snap_sarah"]
    print(f"  Caspar: net_liq=${snap_c.net_liq_usd:,.2f}  upl=${snap_c.upl:,.2f}  ({snap_c.upl_pct*100:.2f}%)")
    print(f"  Sarah:  net_liq=S${snap_s.net_liq_sgd:,.2f}  upl=S${snap_s.upl_sgd:,.2f}  ({snap_s.upl_pct*100:.2f}%)")

    # Fetch indicators (vol, momentum, SMA, RSI) for option underlyings
    option_underlyings = set()
    for acct in ("caspar", "sarah"):
        for o in grab.get("accounts", {}).get(acct, {}).get("options", []):
            option_underlyings.add(o["symbol"])

    indicators: dict[str, dict] = {}
    if option_underlyings:
        print(f"Fetching indicators for {len(option_underlyings)} option underlyings...")
        indicators = fetch_indicators(list(option_underlyings))
        for sym in sorted(option_underlyings):
            ind = indicators.get(sym, {})
            if ind:
                print(f"  {sym}: mom5d={ind.get('momentum_5d', 0):+.1f}% "
                      f"σ={ind.get('volatility_annual', 0)*100:.0f}% "
                      f"RSI={ind.get('rsi_14', 0):.0f} "
                      f"SMA20={ind.get('sma_20', 0):.2f}")

    # Build options
    print("Building options...")
    today = results["date"]
    option_rows = build_options(grab, prices, indicators, macro, today)
    results["options"] = option_rows
    for opt in option_rows:
        exp_fmt = f"{opt.expiry[:4]}-{opt.expiry[4:6]}-{opt.expiry[6:]}" if len(opt.expiry) == 8 else opt.expiry
        print(f"  {opt.account}: {opt.ticker} {opt.strike}{opt.right} exp {exp_fmt} "
              f"| {opt.moneyness} | DTE {opt.dte} | risk {opt.assignment_risk} | "
              f"confidence {opt.confidence_pct}% | {opt.wheel_leg}"
              f"{f' | adj_basis ${opt.adj_cost_basis:.2f}' if opt.adj_cost_basis else ''}")
        print(f"      → {opt.confidence_reasoning}")

    if args.dryrun:
        print("\n--dryrun: not pushing to sheet.")
        return 0

    print("\nPushing to sheet...")
    push_to_sheet(results)
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
