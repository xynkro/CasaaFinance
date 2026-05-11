"""refresh_exit_plans.py — daily refresh of exit_plans for BOTH accounts.

The original exit_plans path runs only when `casaa portfolio-grab` (or
daily_tracker) is invoked manually, and only generates rows for accounts
that the IBKR grab returns positions for. Sarah's IBKR isn't connected,
so her exit_plans go stale within days while Caspar's stay current.

This script side-steps that limitation:
  - reads positions from `positions_caspar` + `positions_sarah` sheets
    (always fresh, populated every 15min by yahoo_grab)
  - reads live_prices from sheet for the current price
  - fetches per-ticker indicators on the fly via yfinance
  - calls compute_stock_exit_plan and writes fresh rows to exit_plans

Runs daily via .github/workflows/refresh-exit-plans.yml at 06:30 SGT,
after yahoo_grab's 06:22 SGT cron has updated positions.

Usage:
  python scripts/refresh_exit_plans.py        # write to sheet
  python scripts/refresh_exit_plans.py --dry  # print, no write
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.sync import load_env             # noqa: E402
from src import sheets as sh              # noqa: E402
from src import schema as S               # noqa: E402
from src.exit_plan import compute_stock_exit_plan  # noqa: E402


def _setup_logger() -> logging.Logger:
    log_path = ROOT / ".state" / "refresh-exit-plans.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("refresh-exit-plans")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fh = logging.FileHandler(log_path)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(fh)
        sh_ = logging.StreamHandler()
        sh_.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logger.addHandler(sh_)
    return logger


def _latest_positions(client, account: str) -> list[dict]:
    """Return the latest-date set of positions for an account, parsed."""
    ss = sh._open_sheet(client)
    try:
        ws = ss.worksheet(f"positions_{account}")
    except Exception:
        return []
    rows = ws.get_all_values()
    if len(rows) < 2:
        return []
    hdr = rows[0]
    cols = {h: i for i, h in enumerate(hdr)}
    needed = ["date", "ticker", "qty", "avg_cost"]
    if not all(c in cols for c in needed):
        return []
    latest = max((r[cols["date"]] for r in rows[1:] if len(r) > cols["date"] and r[cols["date"]]), default="")
    if not latest:
        return []
    out = []
    for r in rows[1:]:
        if len(r) <= max(cols.values()):
            continue
        if r[cols["date"]] != latest:
            continue
        try:
            qty = float(r[cols["qty"]] or 0)
            avg = float(r[cols["avg_cost"]] or 0)
        except (ValueError, TypeError):
            continue
        if qty <= 0 or avg <= 0:
            continue
        out.append({
            "ticker": r[cols["ticker"]].strip().upper(),
            "qty": qty,
            "avg_cost": avg,
        })
    return out


def _live_prices(client) -> dict[str, float]:
    """ticker (uppercase) → current last price."""
    ss = sh._open_sheet(client)
    try:
        ws = ss.worksheet(S.LivePriceRow.TAB_NAME)
    except Exception:
        return {}
    rows = ws.get_all_values()
    if len(rows) < 2:
        return {}
    hdr = rows[0]
    c_tk = hdr.index("ticker") if "ticker" in hdr else -1
    c_last = hdr.index("last") if "last" in hdr else -1
    if c_tk < 0 or c_last < 0:
        return {}
    out: dict[str, float] = {}
    for r in rows[1:]:
        if len(r) > max(c_tk, c_last):
            try:
                out[r[c_tk].strip().upper()] = float(r[c_last] or 0)
            except (TypeError, ValueError):
                pass
    return out


def _compute_indicators(ticker: str, logger: logging.Logger) -> dict:
    """Pull 250d of OHLC from yfinance and compute the minimal set of
    indicators that `compute_stock_exit_plan` cares about.

    Returns {} on any fetch failure — exit_plan logic degrades gracefully
    (treats missing indicators as 0 and falls back to percentage stops).
    """
    try:
        import yfinance as yf
        # SGX tickers need the .SI suffix on yfinance
        yfsymbol = f"{ticker}.SI" if ticker in {"C6L", "G3B", "D05", "O39", "U11", "Z74", "V03"} else ticker
        hist = yf.Ticker(yfsymbol).history(period="1y", interval="1d", auto_adjust=False)
    except Exception as e:
        logger.warning(f"  {ticker}: yfinance fetch failed ({e})")
        return {}
    if hist.empty or len(hist) < 50:
        return {}

    close = hist["Close"].values
    high = hist["High"].values
    low = hist["Low"].values

    # SMA50 / SMA200
    sma_50 = float(close[-50:].mean()) if len(close) >= 50 else 0.0
    sma_200 = float(close[-200:].mean()) if len(close) >= 200 else 0.0

    # ATR(14) — average true range
    if len(hist) >= 15:
        prev_close = close[-15:-1]
        h = high[-14:]
        l = low[-14:]
        tr = [max(hi - lo, abs(hi - pc), abs(lo - pc)) for hi, lo, pc in zip(h, l, prev_close)]
        atr_14 = float(sum(tr) / len(tr))
    else:
        atr_14 = 0.0

    # Swing high/low over trailing 60d → support, resistance, fib retracements
    lookback = min(60, len(hist))
    window_high = float(high[-lookback:].max())
    window_low = float(low[-lookback:].min())
    rng = window_high - window_low
    support = window_low
    resistance = window_high
    fib_0382 = window_low + 0.382 * rng
    fib_0618 = window_low + 0.618 * rng
    fib_0764 = window_low + 0.764 * rng

    return {
        "atr_14": atr_14,
        "support": support,
        "resistance": resistance,
        "fib_0382": fib_0382,
        "fib_0618": fib_0618,
        "fib_0764": fib_0764,
        "sma_50": sma_50,
        "sma_200": sma_200,
        "swing_high": window_high,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry", action="store_true", help="Print plan, no sheet write")
    args = p.parse_args()

    logger = _setup_logger()
    logger.info(f"refresh_exit_plans start (dry={args.dry})")

    load_env()
    client = sh.authenticate()

    prices = _live_prices(client)
    logger.info(f"  loaded {len(prices)} live prices")

    today = datetime.now().strftime("%Y-%m-%dT%H%M%S")

    new_rows: list[S.ExitPlanRow] = []
    for account in ("caspar", "sarah"):
        positions = _latest_positions(client, account)
        logger.info(f"  {account}: {len(positions)} latest positions")
        for pos in positions:
            ticker = pos["ticker"]
            entry = pos["avg_cost"]
            current = prices.get(ticker, 0.0)
            if current <= 0:
                # Fall back to the avg_cost-area sheet value if live missing.
                # This happens for SGX tickers when TV price feed isn't running.
                logger.debug(f"    {account}/{ticker}: no live price, skipping")
                continue
            try:
                ind = _compute_indicators(ticker, logger)
                plan = compute_stock_exit_plan(
                    ticker=ticker,
                    entry_price=entry,
                    current_price=current,
                    qty=pos["qty"],
                    indicators=ind,
                )
            except Exception as e:
                logger.warning(f"    {account}/{ticker}: exit_plan failed ({e})")
                continue

            new_rows.append(S.ExitPlanRow(
                date=today,
                account=account,
                ticker=ticker,
                position_type="STOCK",
                category=plan["category"],
                is_blue_chip=plan["is_blue_chip"],
                entry=plan["entry"],
                current=plan["current"],
                qty=pos["qty"],
                upl_pct=plan["upl_pct"],
                stop_loss=plan["stop_loss"],
                stop_key=plan["stop_key"],
                target_1=plan["target_1"],
                target_2=plan["target_2"],
                time_stop_days=plan["time_stop_days"],
                days_held=plan["days_held"],
                profit_capture_pct=0.0,
                target_close_at=0.0,
                status=plan["status"],
                recommendation=plan["recommendation"],
                reasoning=plan["reasoning"],
            ))

    # Surface anything non-HEALTHY for quick visual review
    notable = [r for r in new_rows if r.status not in ("HEALTHY",)]
    if notable:
        logger.info(f"Non-HEALTHY exit_plans ({len(notable)}):")
        for r in notable:
            logger.info(f"  {r.account}/{r.ticker:6s} {r.status:18s} ${r.current:>9.2f}  stop ${r.stop_loss:>9.2f}  → {r.recommendation[:80]}")

    if args.dry:
        logger.info(f"[DRY] would write {len(new_rows)} rows to exit_plans")
        return 0

    if new_rows:
        sh.ensure_headers(client, S.ExitPlanRow.TAB_NAME, S.ExitPlanRow.HEADERS)
        sh.append_rows(client, S.ExitPlanRow.TAB_NAME, [r.to_row() for r in new_rows])
        logger.info(f"  ✓ wrote {len(new_rows)} fresh exit_plans rows")
    else:
        logger.info("  · no positions to plan")

    return 0


if __name__ == "__main__":
    sys.exit(main())
