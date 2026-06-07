"""Resolve USAspending recipient names to publicly-traded tickers.

The US government writes recipient names in many forms — the same parent
company can appear as "LOCKHEED MARTIN CORPORATION", "Lockheed Martin
Corp.", "LOCKHEED MARTIN CORP", "Lockheed Martin Aeronautics Company"
(subsidiary), and dozens of other variants. We need a stable lookup key
that collapses all of these to a canonical form.

Strategy:
  1. Maintain a manual seed table `recipient_ticker_map` (Sheet) with
     ~150 entries covering top contractors by dollar volume (~85% of
     spending). See scripts/init_recipient_map.py.
  2. Normalize lookup keys with `normalize()` — uppercase, strip
     punctuation, drop common corporate suffixes, sort tokens.
  3. Resolve unmapped names by exact normalized match first; fall back
     to `difflib.get_close_matches` with cutoff 0.85.

Performance: the map is loaded once per process via `lru_cache`. Lookup
is O(1) for exact match, O(n) for fuzzy fallback (n ≤ 200 — fast).
"""
from __future__ import annotations

import logging
import re
from difflib import get_close_matches
from functools import lru_cache

log = logging.getLogger(__name__)

# Strip everything except A-Z, 0-9, and spaces.
_PUNCT_RE = re.compile(r"[^A-Z0-9 ]+")

# Tokens to drop during normalization. Common legal-entity suffixes plus
# small joiner words. The goal is to make "LOCKHEED MARTIN CORPORATION"
# and "LOCKHEED MARTIN CORP" produce the same key.
_DROP_TOKENS = frozenset({
    # US entity types
    "CORP", "CORPORATION", "INC", "INCORPORATED",
    "LLC", "LLP", "LP", "LTD", "LIMITED",
    "CO", "COMPANY", "COMPANIES",
    "GROUP", "HOLDINGS", "HOLDING",
    # International entity types (UK, EU, etc.) — BAE Systems PLC, etc.
    "PLC", "AG", "SA", "NV", "AS", "BV", "GMBH", "OY", "AB",
    # Common joiner words
    "THE", "OF", "AND", "&",
    # Common gov-record artifacts (LP partnership runs etc.)
    "L", "P", "PA", "USA",
    # Punctuation residue after stripping
    "",
})


def normalize(name: str) -> str:
    """Normalize a recipient name to a stable lookup key.

    Steps:
      1. Uppercase
      2. Strip punctuation (replace with space)
      3. Tokenize, drop common corporate suffixes + joiners
      4. Sort tokens (so "LOCKHEED MARTIN" == "MARTIN LOCKHEED")
      5. Join with single spaces

    Examples:
      "Lockheed Martin Corporation" → "LOCKHEED MARTIN"
      "LOCKHEED-MARTIN, CORP."      → "LOCKHEED MARTIN"
      "The Boeing Company"          → "BOEING"
      "BAE Systems plc"             → "BAE SYSTEMS"
    """
    if not name:
        return ""
    upper = name.upper().strip()
    cleaned = _PUNCT_RE.sub(" ", upper)
    tokens = [t for t in cleaned.split() if t and t not in _DROP_TOKENS]
    if not tokens:
        return ""
    tokens.sort()
    return " ".join(tokens)


@lru_cache(maxsize=1)
def _load_map() -> dict[str, str]:
    """Load recipient_ticker_map from the Sheet.

    Returns {normalized_name: ticker}. Empty dict if the sheet is missing
    or empty (graceful degrade — fetch_gov_contracts will write everything
    with empty ticker, screener finds nothing actionable).

    Cached for the process lifetime. Call `_load_map.cache_clear()` from
    a test or `init_recipient_map.py` after modifying the sheet to force
    reload.
    """
    try:
        from src import sheets as sh
        from src import schema as S
    except ImportError:
        log.debug("sheets/schema imports failed — empty map fallback")
        return {}

    try:
        client = sh.authenticate()
        ss = sh._open_sheet(client)
        try:
            ws = ss.worksheet(S.RecipientTickerMapRow.TAB_NAME)
        except Exception as e:
            log.warning("recipient_ticker_map worksheet not found: %s", e)
            return {}
        rows = ws.get_all_values()
    except Exception as e:
        log.warning("Failed to load recipient_ticker_map: %s", e)
        return {}

    if len(rows) < 2:
        return {}
    hdr = rows[0]
    try:
        c_norm = hdr.index("recipient_name_normalized")
        c_tk = hdr.index("parent_ticker")
    except ValueError:
        log.warning(
            "recipient_ticker_map headers missing required columns: %s", hdr,
        )
        return {}

    out: dict[str, str] = {}
    for r in rows[1:]:
        if len(r) <= max(c_norm, c_tk):
            continue
        norm = (r[c_norm] or "").strip()
        ticker = (r[c_tk] or "").strip().upper()
        if norm and ticker:
            out[norm] = ticker
    log.info("Loaded %d entries from recipient_ticker_map", len(out))
    return out


def _token_overlap(a: str, b: str) -> float:
    """Jaccard similarity on token sets — prevents false matches where
    two names share boilerplate tokens ('GOVERNMENT', 'SERVICES') but
    differ on the actual company name.

    Returns 0.0-1.0.
    """
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def resolve(recipient_name: str, fuzzy: bool = True) -> str:
    """Resolve a recipient name to a ticker. Returns "" if not mapped.

    Args:
        recipient_name: raw name as it appears in USAspending (any case,
            with or without punctuation/suffixes).
        fuzzy: if True (default) and exact normalized match misses, try
            difflib.get_close_matches with cutoff 0.90, gated by a
            token-overlap check (≥ 0.50 Jaccard) to prevent false
            matches on boilerplate tokens like "GOVERNMENT SERVICES".

    Returns:
        Uppercase ticker symbol, or "" if no mapping found.
    """
    if not recipient_name:
        return ""
    key = normalize(recipient_name)
    if not key:
        return ""
    mapping = _load_map()
    if not mapping:
        return ""
    if key in mapping:
        return mapping[key]
    if fuzzy:
        # Cutoff 0.90 (was 0.85) + token overlap gate to prevent
        # "GOVERNMENT PAE SERVICES" → "GOVERNMENT PARSONS SERVICES"
        matches = get_close_matches(key, list(mapping.keys()), n=1, cutoff=0.90)
        if matches and _token_overlap(key, matches[0]) >= 0.50:
            log.debug("fuzzy: %r → %r (%s)", key, matches[0], mapping[matches[0]])
            return mapping[matches[0]]
    return ""


