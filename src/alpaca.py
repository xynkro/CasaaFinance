"""
Alpaca Paper Trading API client — thin wrapper over REST v2.

Provides read + write operations for the paper account. No external
library dependency — uses stdlib `requests` (already a project dep).

Env vars required:
  ALPACA_API_KEY_ID     — paper-api key
  ALPACA_API_SECRET_KEY — paper-api secret
  ALPACA_BASE_URL       — defaults to https://paper-api.alpaca.markets

All functions raise RuntimeError on auth / connectivity failure.
"""
from __future__ import annotations

import os
from typing import Literal

import requests

# `or` (not get-default): the CI env sets ALPACA_BASE_URL to an unset secret's
# EMPTY string, which get(key, default) returns as "" — fall back to the paper
# endpoint on empty/missing. Paper is the only supported mode.
_BASE = os.environ.get("ALPACA_BASE_URL") or "https://paper-api.alpaca.markets"


def _headers() -> dict[str, str]:
    key = os.environ.get("ALPACA_API_KEY_ID", "")
    secret = os.environ.get("ALPACA_API_SECRET_KEY", "")
    if not key or not secret:
        raise RuntimeError(
            "ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY not set in environment"
        )
    return {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
        "Content-Type": "application/json",
    }


def _url(path: str) -> str:
    return f"{_BASE}/v2/{path.lstrip('/')}"


def _get(path: str, params: dict | None = None) -> dict | list:
    r = requests.get(_url(path), headers=_headers(), params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def _post(path: str, body: dict | None = None) -> dict:
    r = requests.post(_url(path), headers=_headers(), json=body or {}, timeout=15)
    r.raise_for_status()
    return r.json()


# ────────────────────────────────────────────────────────────────────
# Read — account, positions, orders
# ────────────────────────────────────────────────────────────────────

def get_account() -> dict:
    """Full account snapshot (cash, equity, buying_power, etc.)."""
    return _get("account")


def get_positions() -> list[dict]:
    """All open positions."""
    return _get("positions")


# FinancePWA tags its scanner-executor orders with this client_order_id prefix.
# Other bots sharing the SAME Alpaca paper account (e.g. the ZeroDTE 0-DTE SPY
# bot, or the untagged decision-queue executor) use auto-generated UUIDs, so the
# prefix cleanly attributes positions back to FinancePWA's automated book.
FINANCEPWA_PREFIX = "casaa-"


def financepwa_symbols(orders: list[dict], prefix: str = FINANCEPWA_PREFIX) -> set[str]:
    """Symbols FinancePWA's tagged executor placed — underlyings + multi-leg
    option legs — from orders whose client_order_id starts with `prefix`.

    Use it to filter a shared Alpaca account's positions down to FinancePWA's
    own, so the SPY benchmark and the PWA Paper view aren't polluted by another
    bot trading the same account.
    """
    syms: set[str] = set()
    for o in orders or []:
        if not str(o.get("client_order_id", "") or "").startswith(prefix):
            continue
        if o.get("symbol"):
            syms.add(o["symbol"])
        for leg in (o.get("legs") or []):
            if leg.get("symbol"):
                syms.add(leg["symbol"])
    return syms


def get_position(ticker: str) -> dict | None:
    """Single position by symbol, or None if not held."""
    try:
        return _get(f"positions/{ticker.upper()}")
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return None
        raise


def get_orders(
    status: str = "open",
    limit: int = 50,
    direction: str = "desc",
) -> list[dict]:
    """List orders. status: open | closed | all."""
    return _get("orders", params={
        "status": status,
        "limit": limit,
        "direction": direction,
    })


# ────────────────────────────────────────────────────────────────────
# Write — submit / cancel orders
# ────────────────────────────────────────────────────────────────────

OrderSide = Literal["buy", "sell"]
OrderType = Literal["market", "limit", "stop", "stop_limit", "trailing_stop"]
TimeInForce = Literal["day", "gtc", "opg", "cls", "ioc", "fok"]


def submit_order(
    symbol: str,
    qty: float | int,
    side: OrderSide,
    order_type: OrderType = "market",
    time_in_force: TimeInForce = "day",
    limit_price: float | None = None,
    stop_price: float | None = None,
    trail_percent: float | None = None,
    client_order_id: str | None = None,
    extended_hours: bool = False,
) -> dict:
    """
    Submit a new order. Returns the order object from Alpaca.

    Args:
        symbol: ticker (e.g. "AAPL")
        qty: number of shares (fractional OK for market orders)
        side: "buy" or "sell"
        order_type: "market" | "limit" | "stop" | "stop_limit" | "trailing_stop"
        time_in_force: "day" | "gtc" | "opg" | "cls" | "ioc" | "fok"
        limit_price: required for limit / stop_limit
        stop_price: required for stop / stop_limit
        trail_percent: required for trailing_stop
        client_order_id: optional idempotency key (max 48 chars)
        extended_hours: True for extended-hours limit orders
    """
    body: dict = {
        "symbol": symbol.upper(),
        "qty": str(qty),
        "side": side,
        "type": order_type,
        "time_in_force": time_in_force,
    }
    if limit_price is not None:
        body["limit_price"] = str(round(limit_price, 2))
    if stop_price is not None:
        body["stop_price"] = str(round(stop_price, 2))
    if trail_percent is not None:
        body["trail_percent"] = str(trail_percent)
    if client_order_id:
        body["client_order_id"] = client_order_id[:48]
    if extended_hours:
        body["extended_hours"] = True
    return _post("orders", body)


def _notional_order_body(symbol: str, notional: float, side: OrderSide,
                         client_order_id: str | None) -> dict:
    """Pure builder for a notional (dollar-amount, fractional) order.

    Buy/sell $N of a stock — Alpaca fills a fractional quantity. Fractional/
    notional orders MUST be market + day (Alpaca constraint), so no limit price.
    This is what lets a small account own a slice of a $900 share.
    """
    body: dict = {
        "symbol": symbol.upper(),
        "notional": str(round(notional, 2)),
        "side": side,
        "type": "market",
        "time_in_force": "day",
    }
    if client_order_id:
        body["client_order_id"] = client_order_id[:48]
    return body


def submit_notional_order(symbol: str, notional: float, side: OrderSide = "buy",
                          client_order_id: str | None = None) -> dict:
    """Buy/sell a DOLLAR AMOUNT of a stock (fractional shares). Market + day."""
    return _post("orders", _notional_order_body(symbol, notional, side, client_order_id))


# ────────────────────────────────────────────────────────────────────
# Options — OCC symbols, single-leg + multi-leg (mleg) orders
# ────────────────────────────────────────────────────────────────────

PositionIntent = Literal["buy_to_open", "buy_to_close", "sell_to_open", "sell_to_close"]


def occ_symbol(underlying: str, expiry: str, right: str, strike: float) -> str:
    """Build an OCC option symbol, e.g. ('NVDA','2026-01-16','P',100) → NVDA260116P00100000.

    OCC = ROOT + YYMMDD + C/P + strike×1000 zero-padded to 8 digits.
    `expiry` accepts 'YYYY-MM-DD' or 'YYYYMMDD'. `right` accepts C/P/call/put.
    """
    e = str(expiry).replace("-", "")
    if len(e) != 8:
        raise ValueError(f"expiry must be YYYY-MM-DD or YYYYMMDD, got {expiry!r}")
    yymmdd = e[2:]
    r = "C" if str(right).upper().startswith("C") else "P"
    strike_milli = int(round(float(strike) * 1000))
    if strike_milli <= 0:
        raise ValueError(f"strike must be positive, got {strike!r}")
    return f"{underlying.upper()}{yymmdd}{r}{strike_milli:08d}"


def parse_occ_symbol(occ: str) -> dict | None:
    """Inverse of occ_symbol → {underlying, expiry (YYYY-MM-DD), right, strike},
    or None when `occ` is not an OCC option symbol (e.g. a plain equity ticker
    like 'AMD' — fractional growth buys live in the same account)."""
    s = str(occ or "")
    # OCC = ROOT(>=1) + YYMMDD(6) + C/P(1) + strike(8 digits) → min length 16.
    if (len(s) < 16 or not s[-8:].isdigit()
            or s[-9] not in ("C", "P") or not s[-15:-9].isdigit()):
        return None
    strike = int(s[-8:]) / 1000.0
    right = s[-9]
    yymmdd = s[-15:-9]
    underlying = s[:-15]
    expiry = f"20{yymmdd[:2]}-{yymmdd[2:4]}-{yymmdd[4:6]}"
    return {"underlying": underlying, "expiry": expiry, "right": right, "strike": strike}


def _option_order_body(
    symbol: str, qty: int, side: OrderSide,
    limit_price: float | None, time_in_force: TimeInForce,
    client_order_id: str | None,
) -> dict:
    """Pure builder for a single-leg option order body (unit-testable)."""
    body: dict = {
        "symbol": symbol.upper(),
        "qty": str(int(qty)),
        "side": side,
        "type": "limit" if limit_price is not None else "market",
        "time_in_force": time_in_force,
    }
    if limit_price is not None:
        body["limit_price"] = str(round(limit_price, 2))
    if client_order_id:
        body["client_order_id"] = client_order_id[:48]
    return body


def submit_option_order(
    symbol: str,
    qty: int,
    side: OrderSide,
    limit_price: float | None = None,
    time_in_force: TimeInForce = "day",
    client_order_id: str | None = None,
) -> dict:
    """Submit a SINGLE-LEG option order (OCC symbol, qty in contracts).

    side: "buy" (to open a long / close a short) or "sell" (to open a short /
    close a long). Use a limit_price for safety — options market orders fill
    through wide spreads. Idempotent if client_order_id is supplied.
    """
    return _post("orders", _option_order_body(
        symbol, qty, side, limit_price, time_in_force, client_order_id))


def _mleg_order_body(
    legs: list[dict], qty: int, limit_price: float | None,
    time_in_force: TimeInForce, client_order_id: str | None,
) -> dict:
    """Pure builder for a multi-leg (mleg) order body (unit-testable).

    Each leg: {"symbol": OCC, "position_intent": <PositionIntent>, "ratio_qty": int}.
    `limit_price` is the NET combo price (positive); for a credit spread it's the
    net credit you want to collect. `qty` multiplies the whole combo.
    """
    if not (2 <= len(legs) <= 4):
        raise ValueError(f"mleg needs 2-4 legs, got {len(legs)}")
    body: dict = {
        "order_class": "mleg",
        "qty": str(int(qty)),
        "type": "limit" if limit_price is not None else "market",
        "time_in_force": time_in_force,
        "legs": [
            {
                "symbol": leg["symbol"].upper(),
                "position_intent": leg["position_intent"],
                "ratio_qty": str(int(leg.get("ratio_qty", 1))),
                "side": "buy" if "buy" in leg["position_intent"] else "sell",
            }
            for leg in legs
        ],
    }
    if limit_price is not None:
        body["limit_price"] = str(round(abs(limit_price), 2))
    if client_order_id:
        body["client_order_id"] = client_order_id[:48]
    return body


def submit_mleg_order(
    legs: list[dict],
    qty: int = 1,
    limit_price: float | None = None,
    time_in_force: TimeInForce = "day",
    client_order_id: str | None = None,
) -> dict:
    """Submit a MULTI-LEG option order (vertical spread / iron condor / diagonal).

    legs: list of {"symbol": OCC, "position_intent": sell_to_open|buy_to_open|...,
                   "ratio_qty": 1}. 2 legs = vertical, 4 = iron condor.
    limit_price: net combo price (credit for credit spreads). NOTE: Alpaca's net
    debit/credit sign handling for mleg should be verified on paper before trusting
    fills — that's exactly what the paper run is for.
    """
    return _post("orders", _mleg_order_body(
        legs, qty, limit_price, time_in_force, client_order_id))


