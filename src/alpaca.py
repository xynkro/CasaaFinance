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

_BASE = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")


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


def _delete(path: str) -> dict | None:
    r = requests.delete(_url(path), headers=_headers(), timeout=15)
    r.raise_for_status()
    if r.status_code == 204:
        return None
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


def get_order(order_id: str) -> dict:
    """Get a single order by ID."""
    return _get(f"orders/{order_id}")


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


def parse_occ_symbol(occ: str) -> dict:
    """Inverse of occ_symbol → {underlying, expiry (YYYY-MM-DD), right, strike}."""
    # strike = last 8 digits, right = char before that, date = 6 before that
    strike = int(occ[-8:]) / 1000.0
    right = occ[-9]
    yymmdd = occ[-15:-9]
    underlying = occ[:-15]
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


def get_option_positions() -> list[dict]:
    """Open positions that are options (asset_class == 'us_option')."""
    return [p for p in get_positions() if p.get("asset_class") == "us_option"]


def cancel_order(order_id: str) -> None:
    """Cancel an open order by ID."""
    _delete(f"orders/{order_id}")


def cancel_all_orders() -> list[dict]:
    """Cancel all open orders. Returns list of cancelled orders."""
    r = requests.delete(
        _url("orders"),
        headers=_headers(),
        timeout=15,
    )
    r.raise_for_status()
    return r.json() if r.status_code != 207 else r.json()


def close_position(symbol: str) -> dict:
    """Liquidate an entire position."""
    return _delete(f"positions/{symbol.upper()}")


# ────────────────────────────────────────────────────────────────────
# Helpers — portfolio summary, NLV, buying power
# ────────────────────────────────────────────────────────────────────

def portfolio_value() -> float:
    """Current portfolio value (equity)."""
    return float(get_account()["portfolio_value"])


def buying_power() -> float:
    """Available buying power."""
    return float(get_account()["buying_power"])


def cash() -> float:
    """Cash balance."""
    return float(get_account()["cash"])


def is_market_open() -> bool:
    """Whether US market is currently open for trading."""
    clock = _get("clock")
    return clock.get("is_open", False)


def next_market_open() -> str:
    """ISO timestamp of next market open."""
    clock = _get("clock")
    return clock.get("next_open", "")


def next_market_close() -> str:
    """ISO timestamp of next market close."""
    clock = _get("clock")
    return clock.get("next_close", "")
