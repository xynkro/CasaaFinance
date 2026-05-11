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
