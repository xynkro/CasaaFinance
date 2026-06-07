"""execute_decisions.py — read ACT_NOW decisions and place Alpaca orders.

Reads the decision_queue sheet for rows with status == "act_now" that
haven't been executed yet. Maps each decision's strategy to an Alpaca
order type and submits it.

Strategy → Alpaca mapping:
  BUY_DIP     → limit buy at entry price (or market if within 1%)
  TRIM        → market sell (partial qty if specified)
  CSP         → not yet supported (Alpaca options API separate)
  CC          → not yet supported
  LONG_CALL   → not yet supported
  LONG_PUT    → not yet supported
  PMCC        → not yet supported
  (empty)     → treated as BUY_DIP for share entries with bucket="BUY NOW"

Position sizing follows src/trading_rules.py limits. Each order is
capped at the category's max % of NLV.

After execution:
  - Updates decision_queue row status: act_now → filled (or failed)
  - Writes to alpaca_orders sheet for audit trail
  - Pings Telegram with order confirmation

Schedule: designed to run after the daily brief (07:45 SGT) or manually.

Usage:
  python scripts/execute_decisions.py            # execute
  python scripts/execute_decisions.py --dry      # print plan, no orders
  python scripts/execute_decisions.py --status   # show account + positions
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.sync import load_env              # noqa: E402
from src import sheets as sh               # noqa: E402
from src import schema as S                # noqa: E402
from src import alpaca as alp              # noqa: E402
from src import telegram as tg             # noqa: E402
from src.trading_rules import (            # noqa: E402
    SIZING_LIMITS_PCT_NETLIQ,
)


log = logging.getLogger(__name__)

# Strategies we can execute as stock orders today.
# Options strategies require Alpaca's options API (separate endpoint).
STOCK_STRATEGIES = {"BUY_DIP", "TRIM", ""}
OPTIONS_STRATEGIES = {"CSP", "CC", "LONG_CALL", "LONG_PUT", "PMCC"}

# Bucket aliases that imply a BUY when strategy is empty
BUY_BUCKETS = {"BUY NOW", "BUY_DIP", "WATCH", "BUY DIP"}

# Max % distance from entry to use market order instead of limit
MARKET_ORDER_THRESHOLD_PCT = 0.01  # 1%

# Ticker → category mapping (mirrors exit_plan logic)
BLUE_CHIPS = {"AAPL", "MSFT", "GOOGL", "GOOG", "MA", "V", "JPM", "JNJ", "PG", "HD", "UNH"}
QUALITY_GROWTH = {"AMD", "NVDA", "META", "NFLX", "AMZN", "CRM", "TSLA", "AVGO"}
SPEC_GROWTH = {"OPEN", "RDDT", "SOFI", "RKLB", "PLTR", "HOOD", "COIN", "MARA"}
LOTTERY = {"BBAI", "BTBT", "RCAT", "IONQ", "RGTI"}
LEVERAGED_ETF = {"TQQQ", "SSO", "UPRO", "SOXL", "LABU", "TNA"}
COMMODITY_ETF = {"SLV", "GLD", "GLDM", "USO", "UNG"}
CORE = {"SCHD", "SPY", "VOO", "VTI", "QQQ", "IVV", "VEA", "TLT"}


def _category(ticker: str) -> str:
    t = ticker.upper()
    if t in CORE:
        return "core"
    if t in BLUE_CHIPS:
        return "blue_chip"
    if t in QUALITY_GROWTH:
        return "quality_growth"
    if t in SPEC_GROWTH:
        return "spec_growth"
    if t in LOTTERY:
        return "lottery"
    if t in LEVERAGED_ETF:
        return "leveraged_etf"
    if t in COMMODITY_ETF:
        return "commodity_etf"
    return "spec_growth"  # default conservative


def _max_position_usd(nlv: float, ticker: str) -> float:
    """Max USD allocation for a single position."""
    cat = _category(ticker)
    pct = SIZING_LIMITS_PCT_NETLIQ.get(cat, 5.0)
    return nlv * pct / 100.0


def _setup_logging() -> logging.Logger:
    from src.logging_util import setup_file_logging
    return setup_file_logging("execute-decisions", ".state/execute-decisions.log")


def show_status(logger: logging.Logger) -> int:
    """Print account summary + positions. Read-only."""
    load_env()
    acct = alp.get_account()
    logger.info("═══ ALPACA PAPER ACCOUNT ═══")
    logger.info(f"  Portfolio Value:  ${float(acct['portfolio_value']):>12,.2f}")
    logger.info(f"  Cash:             ${float(acct['cash']):>12,.2f}")
    logger.info(f"  Buying Power:     ${float(acct['buying_power']):>12,.2f}")
    logger.info(f"  Equity:           ${float(acct['equity']):>12,.2f}")
    logger.info(f"  Status:           {acct['status']}")

    positions = alp.get_positions()
    if positions:
        logger.info(f"\n  Open Positions ({len(positions)}):")
        for p in positions:
            sym = p["symbol"]
            qty = float(p["qty"])
            avg = float(p["avg_entry_price"])
            cur = float(p["current_price"])
            upl = float(p["unrealized_pl"])
            upl_pct = float(p["unrealized_plpc"]) * 100
            mkt = float(p["market_value"])
            logger.info(
                f"    {sym:6} {qty:>8.2f} sh @ ${avg:>8.2f}  "
                f"now ${cur:>8.2f}  upl ${upl:>+9.2f} ({upl_pct:>+.1f}%)  "
                f"mkt ${mkt:>10,.2f}"
            )
    else:
        logger.info("\n  No open positions")

    orders = alp.get_orders(status="open")
    if orders:
        logger.info(f"\n  Open Orders ({len(orders)}):")
        for o in orders:
            logger.info(
                f"    {o['symbol']:6} {o['side']:4} {o['qty']} sh  "
                f"type={o['type']}  status={o['status']}  "
                f"limit={o.get('limit_price', '-')}  stop={o.get('stop_price', '-')}"
            )
    else:
        logger.info("\n  No open orders")

    clock = alp._get("clock")
    logger.info(f"\n  Market open: {clock['is_open']}")
    logger.info(f"  Next open:   {clock['next_open']}")
    logger.info(f"  Next close:  {clock['next_close']}")
    return 0


def _read_act_now_decisions(client) -> list[tuple[int, dict]]:
    """Read decision_queue rows with status == 'act_now'.

    Returns list of (row_index_1based, parsed_dict).
    """
    ss = sh._open_sheet(client)
    try:
        ws = ss.worksheet(S.DecisionRow.TAB_NAME)
    except Exception:
        return []
    rows = ws.get_all_values()
    if len(rows) < 2:
        return []
    hdr = rows[0]
    cols = {h: i for i, h in enumerate(hdr)}

    needed = ["ticker", "status", "strategy", "entry", "qty", "account", "bucket"]
    if not all(c in cols for c in needed):
        return []

    out = []
    for idx, r in enumerate(rows[1:], start=2):  # 1-based, skip header
        if len(r) <= cols["status"]:
            continue
        status = (r[cols["status"]] or "").strip().lower()
        if status != "act_now":
            continue

        try:
            entry = float(r[cols["entry"]] or 0)
        except (TypeError, ValueError):
            entry = 0.0
        try:
            qty = int(float(r[cols["qty"]] or 0))
        except (TypeError, ValueError):
            qty = 0

        out.append((idx, {
            "ticker": (r[cols["ticker"]] or "").strip().upper(),
            "strategy": (r[cols["strategy"]] or "").strip().upper(),
            "entry": entry,
            "qty": qty,
            "account": (r[cols["account"]] or "").strip().lower(),
            "bucket": (r[cols["bucket"]] or "").strip().upper(),
            "thesis_1liner": r[cols.get("thesis_1liner", 0)] if "thesis_1liner" in cols else "",
            "date": r[cols.get("date", 0)] if "date" in cols else "",
        }))
    return out


def _plan_order(
    decision: dict,
    nlv: float,
    existing_positions: dict[str, float],
    current_prices: dict[str, float],
) -> dict | None:
    """Plan an Alpaca order from a decision. Returns order spec or None (skip).

    Returns:
        {symbol, side, qty, order_type, limit_price?, reason} or None
    """
    ticker = decision["ticker"]
    strategy = decision["strategy"]
    entry = decision["entry"]
    planned_qty = decision["qty"]
    bucket = decision["bucket"]

    # Skip options strategies (not supported yet)
    if strategy in OPTIONS_STRATEGIES:
        return {"skip": True, "reason": f"options strategy {strategy} not yet supported on Alpaca"}

    # Determine side
    if strategy == "TRIM":
        side = "sell"
    elif strategy in ("BUY_DIP", "") and bucket in BUY_BUCKETS:
        side = "buy"
    elif strategy == "" and "SELL" in bucket:
        side = "sell"
    else:
        side = "buy"

    # Get current price
    cur_price = current_prices.get(ticker, 0.0)
    if cur_price <= 0:
        return {"skip": True, "reason": f"no current price for {ticker}"}

    # Position sizing for buys
    if side == "buy":
        max_usd = _max_position_usd(nlv, ticker)
        existing_usd = existing_positions.get(ticker, 0.0)
        remaining_usd = max(0, max_usd - existing_usd)

        if remaining_usd <= 0:
            return {"skip": True, "reason": f"already at max allocation ({_category(ticker)})"}

        if planned_qty > 0:
            order_usd = planned_qty * cur_price
            # Cap at remaining allocation
            if order_usd > remaining_usd:
                planned_qty = int(remaining_usd / cur_price)
                if planned_qty <= 0:
                    return {"skip": True, "reason": "planned qty exceeds allocation limit"}
        else:
            # No qty specified — size to 50% of remaining allocation
            planned_qty = max(1, int((remaining_usd * 0.5) / cur_price))

        # Determine order type
        if entry > 0:
            diff_pct = abs(cur_price - entry) / entry
            if diff_pct <= MARKET_ORDER_THRESHOLD_PCT:
                order_type = "market"
                limit_price = None
            else:
                order_type = "limit"
                limit_price = entry
        else:
            order_type = "market"
            limit_price = None

    else:  # sell / trim
        existing_qty = 0
        pos = existing_positions.get(ticker, 0.0)
        if pos > 0:
            # Look up actual share count
            try:
                p = alp.get_position(ticker)
                existing_qty = int(float(p["qty"])) if p else 0
            except Exception:
                existing_qty = 0

        if existing_qty <= 0:
            return {"skip": True, "reason": f"no shares to sell for {ticker}"}

        if planned_qty > 0:
            planned_qty = min(planned_qty, existing_qty)
        else:
            # Default trim = 50% of position
            planned_qty = max(1, existing_qty // 2)

        order_type = "market"
        limit_price = None

    spec = {
        "symbol": ticker,
        "side": side,
        "qty": planned_qty,
        "order_type": order_type,
        "time_in_force": "day",
    }
    if limit_price is not None:
        spec["limit_price"] = limit_price

    return spec


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--dry", action="store_true", help="Print plan, no orders")
    p.add_argument("--status", action="store_true", help="Show account + positions")
    args = p.parse_args()

    logger = _setup_logging()
    load_env()

    if args.status:
        return show_status(logger)

    logger.info(f"execute_decisions start (dry={args.dry})")

    # ── Read decisions ───────────────────────────────────────────────
    client = sh.authenticate()
    decisions = _read_act_now_decisions(client)
    logger.info(f"  found {len(decisions)} ACT_NOW decisions")

    if not decisions:
        logger.info("  nothing to execute")
        return 0

    # ── Get account state ────────────────────────────────────────────
    acct = alp.get_account()
    nlv = float(acct["portfolio_value"])
    logger.info(f"  NLV: ${nlv:,.2f}  buying_power: ${float(acct['buying_power']):,.2f}")

    # Current positions as {ticker: market_value}
    positions = alp.get_positions()
    existing = {p["symbol"].upper(): float(p["market_value"]) for p in positions}

    # Current prices from positions or latest quotes
    current_prices: dict[str, float] = {}
    for p in positions:
        current_prices[p["symbol"].upper()] = float(p["current_price"])

    # For tickers not in positions, fetch quotes
    for _, dec in decisions:
        tk = dec["ticker"]
        if tk not in current_prices:
            try:
                # Use Alpaca's latest quote endpoint
                quote = alp._get(f"stocks/{tk}/quotes/latest")
                ask = float(quote.get("quote", {}).get("ap", 0))
                bid = float(quote.get("quote", {}).get("bp", 0))
                current_prices[tk] = (ask + bid) / 2 if ask > 0 and bid > 0 else ask or bid
            except Exception:
                # Fall back to Alpaca's latest trade
                try:
                    trade = alp._get(f"stocks/{tk}/trades/latest")
                    current_prices[tk] = float(trade.get("trade", {}).get("p", 0))
                except Exception:
                    logger.warning(f"  {tk}: no price available")

    # ── Plan orders ──────────────────────────────────────────────────
    order_plans: list[tuple[int, dict, dict]] = []  # (row_idx, decision, order_spec)
    for row_idx, dec in decisions:
        spec = _plan_order(dec, nlv, existing, current_prices)
        if spec is None:
            continue
        if spec.get("skip"):
            logger.info(f"  SKIP {dec['ticker']}: {spec['reason']}")
            continue
        order_plans.append((row_idx, dec, spec))
        cur = current_prices.get(dec["ticker"], 0)
        logger.info(
            f"  PLAN {spec['side'].upper():4} {spec['qty']:>5} sh {spec['symbol']:6} "
            f"@ {spec['order_type']} {spec.get('limit_price', ''):>8}  "
            f"(cur ${cur:.2f}, cat={_category(spec['symbol'])})"
        )

    if not order_plans:
        logger.info("  no executable orders after planning")
        return 0

    if args.dry:
        logger.info(f"  [DRY] would submit {len(order_plans)} orders")
        return 0

    # ── Execute orders ───────────────────────────────────────────────
    ss = sh._open_sheet(client)
    ws = ss.worksheet(S.DecisionRow.TAB_NAME)
    hdr = ws.row_values(1)
    status_col_idx = hdr.index("status") + 1 if "status" in hdr else None

    results = []
    for row_idx, dec, spec in order_plans:
        try:
            order = alp.submit_order(
                symbol=spec["symbol"],
                qty=spec["qty"],
                side=spec["side"],
                order_type=spec["order_type"],
                time_in_force=spec.get("time_in_force", "day"),
                limit_price=spec.get("limit_price"),
            )
            order_id = order.get("id", "?")
            order_status = order.get("status", "?")
            logger.info(
                f"  ✓ {spec['side'].upper()} {spec['qty']} {spec['symbol']} "
                f"→ order {order_id} status={order_status}"
            )
            results.append({
                "ticker": spec["symbol"],
                "side": spec["side"],
                "qty": spec["qty"],
                "order_id": order_id,
                "order_status": order_status,
                "ok": True,
            })

            # Update decision_queue status → filled
            if status_col_idx:
                try:
                    ws.update_cell(row_idx, status_col_idx, "filled")
                except Exception as e:
                    logger.warning(f"  ⚠ failed to update row {row_idx} status: {e}")

        except Exception as e:
            logger.error(f"  ✗ {spec['side'].upper()} {spec['qty']} {spec['symbol']} FAILED: {e}")
            results.append({
                "ticker": spec["symbol"],
                "side": spec["side"],
                "qty": spec["qty"],
                "error": str(e),
                "ok": False,
            })
            # Update decision_queue status → failed
            if status_col_idx:
                try:
                    ws.update_cell(row_idx, status_col_idx, "failed")
                except Exception as e2:
                    logger.warning(f"  ⚠ failed to update row {row_idx} status: {e2}")

    # ── Telegram summary ─────────────────────────────────────────────
    import html as _html
    filled = [r for r in results if r["ok"]]
    failed = [r for r in results if not r["ok"]]
    lines = [f"<b>🤖 ALPACA EXECUTION</b> · {date.today().isoformat()}"]
    if filled:
        lines.append("")
        for r in filled:
            arrow = "🟢" if r["side"] == "buy" else "🔴"
            lines.append(
                f"  {arrow} {r['side'].upper()} {r['qty']} sh <b>${_html.escape(r['ticker'])}</b> "
                f"→ {r['order_status']}"
            )
    if failed:
        lines.append("")
        lines.append("⚠ <b>FAILED</b>")
        for r in failed:
            lines.append(f"  · ${_html.escape(r['ticker'])} {r['side']} — {_html.escape(r.get('error', '?')[:80])}")
    if not filled and not failed:
        lines.append("  (no orders executed)")

    try:
        tg.send(
            "\n".join(lines),
            parse_mode="HTML",
            message_thread_id=tg.MULTI_DAY_SWING_TOPIC,
            disable_web_page_preview=True,
        )
        logger.info("  ✓ Telegram execution summary sent")
    except Exception as e:
        logger.warning(f"  ⚠ Telegram ping failed (non-fatal): {e}")

    logger.info(f"  done: {len(filled)} filled, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
