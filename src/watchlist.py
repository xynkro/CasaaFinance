"""
watchlist.py — load `prompts/watchlist.yaml` and resolve its
__from_sheets_*__ sentinels into concrete ticker lists.

Public API:
  get_universe(client) -> dict[str, list[str]]
    Returns {category_name: [tickers]} for every section under `universe`.
    Sentinel sources are resolved live; literal `tickers:` lists pass
    through. Tickers are uppercased + de-duplicated within each category.

The brain prompts and the TV / screener scripts both call this. Keep the
return shape stable: callers depend on the category names matching the
YAML keys exactly (`held`, `stock_positions_sarah`, …).
"""
from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Any

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_YAML_PATH = _PROJECT_ROOT / "prompts" / "watchlist.yaml"


# --- sheet readers (small, defensive — never raise; return [] on miss) -----

def _safe_open(client) -> Any:
    """Open the configured sheet; return the spreadsheet handle or None."""
    try:
        from src import sheets as sh
        return sh._open_sheet(client)
    except Exception:
        return None


def _read_latest_tickers(client, tab_name: str, ticker_col_idx: int) -> list[str]:
    """Read the LATEST date's tickers from `tab_name`. Empty on any failure."""
    ss = _safe_open(client)
    if ss is None:
        return []
    try:
        ws = ss.worksheet(tab_name)
        rows = ws.get_all_values()
    except Exception:
        return []
    if len(rows) <= 1:
        return []
    last_date = max(((r[0] or "")[:10] for r in rows[1:]), default="")
    if not last_date:
        return []
    out: list[str] = []
    for r in rows[1:]:
        if not r or len(r) <= ticker_col_idx:
            continue
        if not (r[0] or "").startswith(last_date):
            continue
        t = (r[ticker_col_idx] or "").strip().upper()
        if t and t.isascii() and t.replace(".", "").isalnum():
            out.append(t)
    return out


def _read_recent_tickers(client, tab_name: str, ticker_col_idx: int,
                          days: int) -> list[str]:
    """Read tickers from `tab_name` whose date is within last `days`."""
    ss = _safe_open(client)
    if ss is None:
        return []
    try:
        ws = ss.worksheet(tab_name)
        rows = ws.get_all_values()
    except Exception:
        return []
    cutoff = datetime.date.today() - datetime.timedelta(days=days)
    out: list[str] = []
    for r in rows[1:]:
        if not r or len(r) <= ticker_col_idx:
            continue
        date_s = (r[0] or "")[:10]
        try:
            d = datetime.date.fromisoformat(date_s)
        except Exception:
            continue
        if d < cutoff:
            continue
        t = (r[ticker_col_idx] or "").strip().upper()
        if t and t.isascii() and t.replace(".", "").isalnum():
            out.append(t)
    return out


# --- sentinel resolver ------------------------------------------------------

def _resolve_source(client, source: str, fallback: list[str] | None) -> list[str]:
    """
    Map a __from_sheets_*__ sentinel to a fresh ticker list. Unknown
    sentinels return [] (logged at WARNING by the caller if needed).
    """
    if source == "__from_sheets__":
        # Held = options book underlyings (positions_caspar + positions_sarah
        # latest snapshot, intersected with current options book if present).
        a = _read_latest_tickers(client, "positions_caspar", 1)
        b = _read_latest_tickers(client, "positions_sarah", 1)
        opts = _read_latest_tickers(client, "options", 2)
        merged = sorted(set(a) | set(b) | set(opts))
        return merged or (fallback or [])

    if source == "__from_sheets_positions_sarah__":
        return _read_latest_tickers(client, "positions_sarah", 1) or (fallback or [])

    if source == "__from_sheets_positions_caspar__":
        return _read_latest_tickers(client, "positions_caspar", 1) or (fallback or [])

    if source == "__from_sheets_decision_queue_30d__":
        return _read_recent_tickers(client, "decision_queue", 2, 30) or (fallback or [])

    return fallback or []


# --- public API -------------------------------------------------------------

def _load_yaml() -> dict[str, Any]:
    if not _YAML_PATH.exists():
        raise FileNotFoundError(f"watchlist YAML missing: {_YAML_PATH}")
    return yaml.safe_load(_YAML_PATH.read_text()) or {}


def get_universe(client, logger: logging.Logger | None = None) -> dict[str, list[str]]:
    """
    Resolve the YAML into {category: [tickers]}. Live sheet reads happen
    at call time. Categories with empty resolved lists still appear in
    the output (callers may want to know they exist).

    Categories are returned in YAML insertion order (Python dict
    preserves it). Tickers within a category are de-duplicated +
    uppercased; ordering follows the YAML for hardcoded lists and
    sheet-row order for sentinel sources.
    """
    config = _load_yaml()
    sections = config.get("universe") or {}
    out: dict[str, list[str]] = {}

    for category, body in sections.items():
        body = body or {}
        source = body.get("source")
        fallback = list(body.get("fallback") or [])
        tickers = list(body.get("tickers") or [])

        if source:
            resolved = _resolve_source(client, source, fallback)
            if logger and not resolved:
                logger.warning(
                    f"[watchlist] {category}: sentinel {source} returned no "
                    f"tickers (and no fallback)"
                )
        else:
            resolved = tickers

        # Normalise + dedupe while preserving order.
        seen: set[str] = set()
        cleaned: list[str] = []
        for t in resolved:
            tt = (t or "").strip().upper()
            if not tt or tt in seen:
                continue
            seen.add(tt)
            cleaned.append(tt)
        out[category] = cleaned

    return out


def flatten(universe: dict[str, list[str]]) -> list[str]:
    """Convenience: dedupe across all categories, return sorted list."""
    s: set[str] = set()
    for tickers in universe.values():
        for t in tickers:
            s.add(t)
    return sorted(s)


# --- asset-class taxonomy (Risk Parity LITE) ------------------------------

# Cache the parsed `asset_classes:` map so repeated calls don't re-read YAML.
_ASSET_CLASS_CACHE: dict[str, str] | None = None


def _load_asset_classes() -> dict[str, str]:
    """Load the `asset_classes:` map from watchlist.yaml. Cached after first call."""
    global _ASSET_CLASS_CACHE
    if _ASSET_CLASS_CACHE is not None:
        return _ASSET_CLASS_CACHE
    try:
        config = _load_yaml()
    except FileNotFoundError:
        _ASSET_CLASS_CACHE = {}
        return _ASSET_CLASS_CACHE
    raw = config.get("asset_classes") or {}
    # Normalise — uppercase keys, str values.
    out: dict[str, str] = {}
    for k, v in raw.items():
        if not k or not v:
            continue
        out[str(k).strip().upper()] = str(v).strip()
    _ASSET_CLASS_CACHE = out
    return out


# Canonical asset-class values — single source of truth. Other modules
# (schema.py, risk_parity_audit.py) can import this for validation.
CANONICAL_ASSET_CLASSES = (
    "equity_us",
    "equity_us_dividend",
    "equity_intl",
    "bond_long",
    "bond_intermediate",
    "gold",
    "commodities_broad",
    "vol_long",
)


def get_asset_class(ticker: str) -> str:
    """
    Return the asset_class for a ticker, defaulting to 'equity_us' if absent.

    Reads `asset_classes:` map from prompts/watchlist.yaml. Lookup is
    case-insensitive on the ticker. Unknown tickers default to 'equity_us'
    — the conservative choice for an equity-anchored book that would rather
    over-attribute to the dominant class than under-count it.
    """
    if not ticker:
        return "equity_us"
    m = _load_asset_classes()
    return m.get(str(ticker).strip().upper(), "equity_us")
