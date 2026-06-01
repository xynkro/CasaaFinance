"""screen_gov_confluence.py — daily confluence scorer.

Joins three feeds (gov_contracts + congress_trades + insider_transactions)
into a per-ticker confluence score and writes:

  1. gov_confluence_signals — one row per (date, ticker) where score >= 60
  2. decision_queue — appended rows for Tier A / B picks with strategy
     (BUY_DIP / LONG_CALL / PMCC) populated

Score formula (literature-backed weights):
  score = 0.40 * contract + 0.30 * insider + 0.15 * congress + 0.15 * analyst

Action recommendation rules (rules-based; brain may override in daily-brief):
  Score 70-79 + Tier A     → BUY_DIP (cash buy, 1% NLV)
  Score 80-89              → LONG_CALL 0.50Δ 30-45 DTE
  Score 90+                → LONG_CALL 0.60Δ or PMCC if IV high

Schedule: 23:00 UTC = 07:00 SGT next day, Mon-Fri (after fetch_gov_contracts
06:00 + fetch_congress_trades 06:30, before daily-brief 07:43).

Usage:
  python scripts/screen_gov_confluence.py            # write
  python scripts/screen_gov_confluence.py --dry      # print, no sheet write
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.sync import load_env  # noqa: E402
from src import sheets as sh   # noqa: E402
from src import schema as S    # noqa: E402

log = logging.getLogger(__name__)

_fundamentals_cache: dict[str, tuple[float | None, float | None]] = {}


_FH_BASE = "https://finnhub.io/api/v1"


def _sanitize_fundamentals(
    rev: float | None, cap: float | None,
) -> tuple[float | None, float | None]:
    """Drop garbage values so materiality never divides by a bad denominator.

    yfinance's scraped .info occasionally returns revenue == market cap, or
    zero/negative. Treat non-positive as missing, and reject a revenue that
    exactly equals market cap (a known bad-data signature, e.g. PSN) so the
    contract falls back to the market-cap yardstick instead of a fake ratio.
    """
    r = float(rev) if (rev and rev > 0) else None
    c = float(cap) if (cap and cap > 0) else None
    if r is not None and c is not None and abs(r - c) < 1.0:
        r = None
    return r, c


def _finnhub_market_cap(ticker: str) -> float | None:
    """Market cap (USD) via Finnhub profile2 — clean units (reported in
    millions). Returns None for ETFs/unknown symbols or when the key is unset,
    so a fund's AUM never masquerades as a company valuation."""
    try:
        import os
        import requests
        key = os.getenv("FINNHUB_API_KEY")
        if not key:
            return None
        r = requests.get(
            f"{_FH_BASE}/stock/profile2",
            params={"symbol": ticker, "token": key},
            timeout=10,
        )
        if r.status_code != 200:
            return None
        data = r.json() or {}
        if str(data.get("type", "")).upper() in ("ETP", "ETF", "FUND"):
            return None
        mcap_m = data.get("marketCapitalization")
        return float(mcap_m) * 1e6 if mcap_m else None
    except Exception:
        return None


def _fetch_fundamentals(ticker: str) -> tuple[float | None, float | None]:
    """Fetch (TTM revenue, market cap) for sizing the bet vs the company.

    Market cap comes from Finnhub (reliable units) with yfinance as fallback;
    TTM revenue comes from yfinance. Both pass through _sanitize_fundamentals
    so one bad source can't poison the materiality ratios. Either element is
    None when unavailable (ETFs, delisted, or pre-revenue names)."""
    if ticker in _fundamentals_cache:
        return _fundamentals_cache[ticker]
    rev: float | None = None
    cap: float | None = None
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        _rev = info.get("totalRevenue") or info.get("revenue")
        rev = float(_rev) if _rev else None
        _cap = info.get("marketCap")
        cap = float(_cap) if _cap else None
    except Exception:
        pass
    fh_cap = _finnhub_market_cap(ticker)   # prefer Finnhub's cleaner market cap
    if fh_cap:
        cap = fh_cap
    rev, cap = _sanitize_fundamentals(rev, cap)
    _fundamentals_cache[ticker] = (rev, cap)
    return rev, cap


def _fetch_ttm_revenue(ticker: str) -> float | None:
    """Backward-compatible wrapper — TTM revenue only."""
    return _fetch_fundamentals(ticker)[0]


# Materiality thresholds. Two different yardsticks, because the two kinds of
# "smart money" move a stock through different mechanisms:
#   • A CONTRACT is a fundamental catalyst — it adds revenue. Size it vs TTM
#     revenue (falling back to market cap when revenue is unknown).
#   • INSIDER / CONGRESS buying is an equity FLOW — it's only stock-moving if
#     it's a meaningful slice of the company's market cap. A senator's $50k
#     buy on a $4T mega-cap is a rounding error; an insider cluster buying 1%
#     of a small-cap's float is a real flow.
# A contract = 20% of revenue is enormous; an equity flow = 1% of market cap is
# already enormous, so the flow bands sit an order of magnitude lower.
_MAT_REV_HUGE = 0.20        # contract ≥20% of revenue → HUGE
_MAT_REV_MATERIAL = 0.05    # ≥5%  → MATERIAL
_MAT_REV_NOTABLE = 0.01     # ≥1%  → NOTABLE
_MAT_CAP_HUGE = 0.01        # flow ≥1% of market cap → HUGE
_MAT_CAP_MATERIAL = 0.003   # ≥0.3% → MATERIAL
_MAT_CAP_NOTABLE = 0.001    # ≥0.1% → NOTABLE

_MAT_LABELS = ["IMMATERIAL", "NOTABLE", "MATERIAL", "HUGE"]


def _severity(value: float, huge: float, material: float, notable: float) -> int:
    """Map a ratio onto 0..3 (IMMATERIAL..HUGE) against three thresholds."""
    if value >= huge:
        return 3
    if value >= material:
        return 2
    if value >= notable:
        return 1
    return 0


def compute_materiality(
    contract_usd: float,
    insider_usd: float,
    ttm_revenue: float | None,
    market_cap: float | None,
    congress_usd: float = 0.0,
) -> dict:
    """Size the bet against the company so the user can judge stock-impact.

    Returns the per-leg ratios, the company's raw size (so the PWA can show
    "Company: $4.6T cap / $451B rev"), and a single `materiality` label that
    is the more material of two views:
      • the contract's revenue impact (fundamental catalyst), and
      • the insider+congress flow vs market cap (equity-flow impact).
    Every signal with activity and a known denominator gets a label — a tiny
    Congress buy on a mega-cap correctly reads IMMATERIAL ("won't move it").
    Label is "" only when the company's size couldn't be fetched.
    """
    contract_usd = contract_usd or 0.0
    insider_usd = insider_usd or 0.0
    congress_usd = congress_usd or 0.0
    rev = ttm_revenue if (ttm_revenue and ttm_revenue > 0) else 0.0
    cap = market_cap if (market_cap and market_cap > 0) else 0.0
    c_pct_rev = (contract_usd / rev) if rev > 0 else 0.0
    c_pct_cap = (contract_usd / cap) if cap > 0 else 0.0
    i_pct_cap = (insider_usd / cap) if cap > 0 else 0.0
    cg_pct_cap = (congress_usd / cap) if cap > 0 else 0.0
    flow_pct_cap = ((insider_usd + congress_usd) / cap) if cap > 0 else 0.0

    # Contract severity: vs revenue, falling back to market cap.
    contract_drive = c_pct_rev if c_pct_rev > 0 else c_pct_cap
    sev_contract = _severity(
        contract_drive, _MAT_REV_HUGE, _MAT_REV_MATERIAL, _MAT_REV_NOTABLE,
    )
    # Equity-flow severity: insider + congress buying vs market cap.
    sev_flow = _severity(
        flow_pct_cap, _MAT_CAP_HUGE, _MAT_CAP_MATERIAL, _MAT_CAP_NOTABLE,
    )

    has_activity = (contract_usd > 0) or (insider_usd > 0) or (congress_usd > 0)
    has_denominator = (rev > 0) or (cap > 0)
    if has_activity and has_denominator:
        label = _MAT_LABELS[max(sev_contract, sev_flow)]
    else:
        label = ""                       # no activity, or size unknown

    return {
        "contract_pct_rev": round(c_pct_rev, 4),
        "contract_pct_mktcap": round(c_pct_cap, 4),
        "insider_pct_mktcap": round(i_pct_cap, 4),
        "congress_pct_mktcap": round(cg_pct_cap, 4),
        "flow_pct_mktcap": round(flow_pct_cap, 4),
        "market_cap": cap,
        "ttm_revenue": rev,
        "materiality": label,
    }

# Lookback windows (per design doc §3)
CONTRACT_LOOKBACK_DAYS = 30
CONGRESS_LOOKBACK_DAYS = 60
INSIDER_LOOKBACK_DAYS = 90

# Score thresholds
# MIN_SCORE_TO_PERSIST=0: ALL scored signals flow to the sheet so the
# brain (daily brief / WSR) sees the full picture and makes its own
# decisions.  Tier A/B (70/80) still gate AUTO-entries into
# decision_queue, but the brain can override any signal regardless of
# score — it reads the complete gov_confluence_signals tab each morning.
MIN_SCORE_TO_PERSIST = 0
TIER_A_MIN_SCORE = 70
TIER_B_MIN_SCORE = 80
TIER_A_MIN_IMPACT_PCT = 0.01  # 1% TTM rev
TIER_B_MIN_IMPACT_PCT = 0.05  # 5% TTM rev

# Weights (sum to 1.00). Literature-backed rebalance:
#   Contracts ↑40%: Oxford RAPS (2023) — GD firms earn 50 bps/month alpha, Sharpe 0.91
#   Insider   ↑30%: Kang/Kim/Wang (2018) — cluster buys earn 3.8% in 21 days
#   Congress  ↓15%: Post-STOCK Act alpha dropped to 0.9%/yr (ScienceDirect 2024);
#                   only leadership trades retain edge (Wei & Zhou NBER 2025)
#   Analyst    15%: QuiverQuant 78% win rate — useful as confluence booster
W_CONTRACT = 0.40
W_CONGRESS = 0.15
W_INSIDER  = 0.30
W_ANALYST  = 0.15

# NAICS codes that get a small sector bonus (+5) — top federal-spending sectors
PRIORITY_NAICS = {
    "541512",  # Computer Systems Design Services
    "541330",  # Engineering Services
    "336411",  # Aircraft Manufacturing
    "541715",  # Research and Development in the Physical, Engineering, and Life Sciences
    "928110",  # National Security
    "541611",  # Administrative Management and General Management Consulting
    "237310",  # Highway, Street, and Bridge Construction
    "562910",  # Remediation Services
}


# ─────────────────────────────────────────────────────────────────────────────
# Per-ticker rolling state
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TickerStats:
    """Accumulator for one ticker's aggregated signals over the lookback windows."""
    ticker: str = ""
    # Contract data
    contracts: list[dict] = field(default_factory=list)
    contract_total_30d: float = 0.0
    contract_max_single: float = 0.0
    has_multi_year: bool = False
    has_recent_award: bool = False  # within 7d
    has_priority_naics: bool = False
    # Congress data
    congress_buys: list[dict] = field(default_factory=list)
    congress_amount_total: float = 0.0
    has_recent_congress: bool = False  # within 14d
    has_congress_cluster: bool = False  # 3+ unique politicians in trailing 30d
    # Insider data
    insider_buys: list[dict] = field(default_factory=list)
    insider_value_total: float = 0.0
    insider_unique_count: int = 0
    has_insider_cluster: bool = False  # 3+ insiders in same 30d window
    # Analyst data (Tweak #4) — looked up per-ticker, no aggregation
    analyst_consensus_score: float = 0.0  # [-2..+2] raw from analyst_consensus
    analyst_total_count: int = 0
    analyst_label: str = ""  # STRONG_BUY|BUY|HOLD|SELL|STRONG_SELL|""


# ─────────────────────────────────────────────────────────────────────────────
# Sheet readers
# ─────────────────────────────────────────────────────────────────────────────

def _setup_logging() -> logging.Logger:
    log_path = ROOT / ".state" / "screen-gov-confluence.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("screen-gov-confluence")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fh = logging.FileHandler(log_path)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(fh)
        sh_ = logging.StreamHandler()
        sh_.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logger.addHandler(sh_)
    return logger


def _safe_float(s: str) -> float:
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def _within_days(date_str: str, days: int, today: date | None = None) -> bool:
    """True if `date_str` (YYYY-MM-DD prefix) is within `days` of today."""
    if not date_str or len(date_str) < 10:
        return False
    today = today or date.today()
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    except ValueError:
        return False
    return (today - d).days <= days and (today - d).days >= 0


def _read_gov_contracts(client, today: date) -> dict[str, list[dict]]:
    """Read gov_contracts rows in last 30d, grouped by ticker.

    Filters out rows with empty `ticker` (unmapped recipients).
    """
    cutoff_iso = (today - timedelta(days=CONTRACT_LOOKBACK_DAYS)).isoformat()
    ss = sh._open_sheet(client)
    try:
        ws = ss.worksheet(S.GovContractRow.TAB_NAME)
    except Exception:
        log.warning("gov_contracts worksheet missing — empty contract data")
        return {}
    rows = ws.get_all_values()
    if len(rows) < 2:
        return {}
    hdr = rows[0]
    cols = {h: i for i, h in enumerate(hdr)}
    if "ticker" not in cols or "action_date" not in cols:
        log.warning("gov_contracts schema mismatch — skipping")
        return {}

    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for r in rows[1:]:
        ticker = (r[cols["ticker"]] if len(r) > cols["ticker"] else "").upper()
        if not ticker:
            continue
        action_date = (r[cols["action_date"]] if len(r) > cols["action_date"] else "")[:10]
        if not action_date or action_date < cutoff_iso:
            continue
        period_start = (r[cols.get("period_start", -1)] if cols.get("period_start", -1) >= 0 and len(r) > cols.get("period_start", -1) else "")[:10]
        period_end = (r[cols.get("period_end", -1)] if cols.get("period_end", -1) >= 0 and len(r) > cols.get("period_end", -1) else "")[:10]
        award_amount = _safe_float(r[cols["award_amount"]] if len(r) > cols.get("award_amount", -1) else "0")
        tcv = _safe_float(r[cols.get("tcv", -1)] if cols.get("tcv", -1) >= 0 and len(r) > cols.get("tcv", -1) else "0")
        naics = (r[cols.get("naics_code", -1)] if cols.get("naics_code", -1) >= 0 and len(r) > cols.get("naics_code", -1) else "").strip()
        award_id = (r[cols.get("award_id", -1)] if cols.get("award_id", -1) >= 0 and len(r) > cols.get("award_id", -1) else "")

        # Multi-year flag: period_end - period_start > 365 days
        is_multi_year = False
        if period_start and period_end:
            try:
                ps = datetime.strptime(period_start, "%Y-%m-%d").date()
                pe = datetime.strptime(period_end, "%Y-%m-%d").date()
                is_multi_year = (pe - ps).days > 365
            except ValueError:
                pass

        by_ticker[ticker].append({
            "award_id": award_id,
            "action_date": action_date,
            "award_amount": award_amount,
            "tcv": tcv,
            "naics_code": naics,
            "is_multi_year": is_multi_year,
        })
    log.info(f"gov_contracts: {sum(len(v) for v in by_ticker.values())} rows across {len(by_ticker)} tickers")
    return by_ticker


def _read_congress_trades(client, today: date) -> dict[str, list[dict]]:
    """Read congress_trades buys in last 60d, grouped by ticker."""
    cutoff_iso = (today - timedelta(days=CONGRESS_LOOKBACK_DAYS)).isoformat()
    ss = sh._open_sheet(client)
    try:
        ws = ss.worksheet(S.CongressTradeRow.TAB_NAME)
    except Exception:
        log.warning("congress_trades worksheet missing — empty congress data")
        return {}
    rows = ws.get_all_values()
    if len(rows) < 2:
        return {}
    hdr = rows[0]
    cols = {h: i for i, h in enumerate(hdr)}
    needed = ["ticker", "filing_date", "transaction_type", "amount_min", "amount_max", "filing_id"]
    if not all(c in cols for c in needed):
        log.warning("congress_trades schema mismatch — skipping")
        return {}

    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for r in rows[1:]:
        ticker = (r[cols["ticker"]] if len(r) > cols["ticker"] else "").upper()
        if not ticker:
            continue
        ttype = (r[cols["transaction_type"]] if len(r) > cols["transaction_type"] else "").lower()
        if ttype != "buy":
            continue
        filing_date = (r[cols["filing_date"]] if len(r) > cols["filing_date"] else "")[:10]
        if not filing_date or filing_date < cutoff_iso:
            continue
        amt_min = _safe_float(r[cols["amount_min"]] if len(r) > cols["amount_min"] else "0")
        amt_max = _safe_float(r[cols["amount_max"]] if len(r) > cols["amount_max"] else "0")
        midpoint = (amt_min + amt_max) / 2.0
        by_ticker[ticker].append({
            "filing_id": (r[cols["filing_id"]] if len(r) > cols["filing_id"] else ""),
            "filing_date": filing_date,
            "midpoint": midpoint,
            "politician_name": (r[cols.get("politician_name", -1)] if cols.get("politician_name", -1) >= 0 and len(r) > cols.get("politician_name", -1) else ""),
        })
    log.info(f"congress_trades buys: {sum(len(v) for v in by_ticker.values())} rows across {len(by_ticker)} tickers")
    return by_ticker


def _read_insider_buys(client, today: date) -> dict[str, list[dict]]:
    """Read insider_transactions purchases (transaction_code=P) in last 90d."""
    cutoff_iso = (today - timedelta(days=INSIDER_LOOKBACK_DAYS)).isoformat()
    ss = sh._open_sheet(client)
    try:
        ws = ss.worksheet(S.InsiderTransactionRow.TAB_NAME)
    except Exception:
        log.warning("insider_transactions worksheet missing — empty insider data")
        return {}
    rows = ws.get_all_values()
    if len(rows) < 2:
        return {}
    hdr = rows[0]
    cols = {h: i for i, h in enumerate(hdr)}
    if "ticker" not in cols or "transaction_date" not in cols:
        log.warning("insider_transactions schema mismatch — skipping")
        return {}

    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for r in rows[1:]:
        ticker = (r[cols["ticker"]] if len(r) > cols["ticker"] else "").upper()
        if not ticker:
            continue
        side = (r[cols.get("side", -1)] if cols.get("side", -1) >= 0 and len(r) > cols.get("side", -1) else "").lower()
        code = (r[cols.get("transaction_code", -1)] if cols.get("transaction_code", -1) >= 0 and len(r) > cols.get("transaction_code", -1) else "").upper()
        # Treat both P (open-market purchase) and side="buy" as buys
        if code != "P" and side != "buy":
            continue
        txn_date = (r[cols["transaction_date"]] if len(r) > cols["transaction_date"] else "")[:10]
        if not txn_date or txn_date < cutoff_iso:
            continue
        value = _safe_float(r[cols.get("value_usd", -1)] if cols.get("value_usd", -1) >= 0 and len(r) > cols.get("value_usd", -1) else "0")
        by_ticker[ticker].append({
            "id": (r[cols.get("id", -1)] if cols.get("id", -1) >= 0 and len(r) > cols.get("id", -1) else ""),
            "transaction_date": txn_date,
            "value_usd": value,
            "name": (r[cols.get("name", -1)] if cols.get("name", -1) >= 0 and len(r) > cols.get("name", -1) else ""),
        })
    log.info(f"insider_transactions buys: {sum(len(v) for v in by_ticker.values())} rows across {len(by_ticker)} tickers")
    return by_ticker


def _read_congress_sells(client, today: date) -> dict[str, list[dict]]:
    """Read congress_trades rows where transaction_type=sell in last 30d.

    Mirrors _read_congress_trades shape but flipped to sells. Used for
    Tweak #2 — TRIM candidate emission on currently-held tickers.
    """
    cutoff_iso = (today - timedelta(days=30)).isoformat()
    ss = sh._open_sheet(client)
    try:
        ws = ss.worksheet(S.CongressTradeRow.TAB_NAME)
    except Exception:
        log.warning("congress_trades worksheet missing — empty sells data")
        return {}
    rows = ws.get_all_values()
    if len(rows) < 2:
        return {}
    hdr = rows[0]
    cols = {h: i for i, h in enumerate(hdr)}
    needed = ["ticker", "filing_date", "transaction_type", "amount_min", "amount_max", "filing_id"]
    if not all(c in cols for c in needed):
        log.warning("congress_trades schema mismatch — skipping sells")
        return {}

    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for r in rows[1:]:
        ticker = (r[cols["ticker"]] if len(r) > cols["ticker"] else "").upper()
        if not ticker:
            continue
        ttype = (r[cols["transaction_type"]] if len(r) > cols["transaction_type"] else "").lower()
        if ttype != "sell":
            continue
        filing_date = (r[cols["filing_date"]] if len(r) > cols["filing_date"] else "")[:10]
        if not filing_date or filing_date < cutoff_iso:
            continue
        amt_min = _safe_float(r[cols["amount_min"]] if len(r) > cols["amount_min"] else "0")
        amt_max = _safe_float(r[cols["amount_max"]] if len(r) > cols["amount_max"] else "0")
        midpoint = (amt_min + amt_max) / 2.0
        by_ticker[ticker].append({
            "filing_id": (r[cols["filing_id"]] if len(r) > cols["filing_id"] else ""),
            "filing_date": filing_date,
            "midpoint": midpoint,
            "politician_name": (r[cols.get("politician_name", -1)] if cols.get("politician_name", -1) >= 0 and len(r) > cols.get("politician_name", -1) else ""),
        })
    log.info(f"congress_trades sells: {sum(len(v) for v in by_ticker.values())} rows across {len(by_ticker)} tickers")
    return by_ticker


def _read_held_tickers(client) -> set[str]:
    """Set of tickers currently held in either account (latest snapshot).

    Used to gate TRIM emission — we only emit TRIM signals for tickers
    we actually hold (Congress sells of stocks we don't own carry no
    actionable information for a long-only book).
    """
    ss = sh._open_sheet(client)
    held: set[str] = set()
    for tab in ("positions_caspar", "positions_sarah"):
        try:
            ws = ss.worksheet(tab)
        except Exception:
            continue
        rows = ws.get_all_values()
        if len(rows) < 2:
            continue
        hdr = rows[0]
        try:
            c_date = hdr.index("date")
            c_tk = hdr.index("ticker")
        except ValueError:
            continue
        latest = max((r[c_date] for r in rows[1:] if len(r) > c_date and r[c_date]), default="")
        if not latest:
            continue
        for r in rows[1:]:
            if len(r) > max(c_date, c_tk) and r[c_date] == latest and r[c_tk]:
                held.add(r[c_tk].strip().upper())
    log.info(f"held tickers across both accounts: {len(held)}")
    return held


def _read_analyst_consensus(client) -> dict[str, dict]:
    """Per-ticker latest analyst consensus from the weekly Finnhub cron.

    No date filter — `analyst_consensus` is upserted by ticker, so every
    row is current. Maps ticker → {consensus_score, label, total_count}.
    Missing sheet or schema mismatch: returns {} (analyst vector falls
    back to 0 for all tickers; not an error).

    Source data ref: scripts/finnhub_analyst.py (weekly cron),
    `consensus_score` field is weighted avg in [-2..+2].
    """
    ss = sh._open_sheet(client)
    try:
        ws = ss.worksheet(S.AnalystConsensusRow.TAB_NAME)
    except Exception:
        log.warning("analyst_consensus worksheet missing — analyst vector will be 0 for all tickers")
        return {}
    rows = ws.get_all_values()
    if len(rows) < 2:
        return {}
    hdr = rows[0]
    cols = {h: i for i, h in enumerate(hdr)}
    needed = ["ticker", "consensus_score", "consensus_label", "total_count"]
    if not all(c in cols for c in needed):
        log.warning("analyst_consensus schema mismatch — skipping analyst vector")
        return {}

    out: dict[str, dict] = {}
    for r in rows[1:]:
        ticker = (r[cols["ticker"]] if len(r) > cols["ticker"] else "").upper()
        if not ticker:
            continue
        out[ticker] = {
            "consensus_score": _safe_float(r[cols["consensus_score"]] if len(r) > cols["consensus_score"] else "0"),
            "label": r[cols["consensus_label"]] if len(r) > cols["consensus_label"] else "",
            "total_count": int(_safe_float(r[cols["total_count"]] if len(r) > cols["total_count"] else "0")),
        }
    log.info(f"analyst_consensus: {len(out)} tickers loaded")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Sector Gov Momentum — aggregate awards by NAICS 2-digit sector
# ─────────────────────────────────────────────────────────────────────────────

# NAICS 2-digit sector names for human-readable output
NAICS_SECTOR_NAMES: dict[str, str] = {
    "11": "Agriculture", "21": "Mining", "22": "Utilities",
    "23": "Construction", "31": "Manufacturing", "32": "Manufacturing",
    "33": "Manufacturing", "42": "Wholesale", "44": "Retail", "45": "Retail",
    "48": "Transport", "49": "Transport", "51": "Information",
    "52": "Finance", "53": "Real Estate", "54": "Professional/Scientific",
    "55": "Management", "56": "Admin/Waste", "61": "Education",
    "62": "Healthcare", "71": "Arts/Recreation", "72": "Accommodation/Food",
    "81": "Other Services", "92": "Public Admin",
}

# Sector momentum thresholds
SECTOR_MOMENTUM_RATIO = 1.5   # 30d rolling > 1.5× 90d average = hot sector
SECTOR_MOMENTUM_BONUS = 8     # score bonus for tickers in a hot sector


def _compute_sector_momentum(
    contracts_by_ticker: dict[str, list[dict]],
    today: date,
) -> dict[str, dict]:
    """
    Aggregate contract awards by NAICS 2-digit sector code.
    Compare 30-day rolling total vs 90-day rolling average.
    Returns {naics_2digit: {total_30d, avg_90d, ratio, is_hot, sector_name}}.

    A "hot" sector has 30d rolling > 1.5× the 90d daily average (scaled to 30d).
    This captures surges in federal spending that historically predict sector outperformance.
    """
    from collections import defaultdict

    # Flatten all contracts with date and NAICS
    all_contracts: list[dict] = []
    for ticker_contracts in contracts_by_ticker.values():
        for c in ticker_contracts:
            naics = (c.get("naics_code") or "").strip()
            if len(naics) < 2:
                continue
            all_contracts.append({
                "naics_2": naics[:2],
                "date": c.get("action_date", ""),
                "amount": c.get("award_amount", 0),
            })

    if not all_contracts:
        return {}

    cutoff_30d = (today - timedelta(days=30)).isoformat()
    cutoff_90d = (today - timedelta(days=90)).isoformat()

    # Aggregate by NAICS 2-digit
    sector_30d: dict[str, float] = defaultdict(float)
    sector_90d: dict[str, float] = defaultdict(float)

    for c in all_contracts:
        d = c["date"][:10] if c["date"] else ""
        naics_2 = c["naics_2"]
        amt = float(c["amount"])
        if d >= cutoff_30d:
            sector_30d[naics_2] += amt
        if d >= cutoff_90d:
            sector_90d[naics_2] += amt

    # Compute ratios
    result: dict[str, dict] = {}
    all_sectors = set(sector_30d) | set(sector_90d)
    for s in all_sectors:
        total_30d = sector_30d.get(s, 0)
        total_90d = sector_90d.get(s, 0)
        # Average daily spend over 90d, scaled to 30d for comparison
        avg_90d_daily = total_90d / 90 if total_90d > 0 else 0
        avg_90d_30d_equiv = avg_90d_daily * 30

        ratio = (total_30d / avg_90d_30d_equiv) if avg_90d_30d_equiv > 0 else 0
        is_hot = ratio >= SECTOR_MOMENTUM_RATIO and total_30d > 1_000_000  # min $1M to avoid noise

        result[s] = {
            "total_30d": total_30d,
            "avg_90d_30d_equiv": avg_90d_30d_equiv,
            "ratio": round(ratio, 2),
            "is_hot": is_hot,
            "sector_name": NAICS_SECTOR_NAMES.get(s, f"NAICS {s}"),
        }

    return result


def _ticker_naics_sectors(contracts: list[dict]) -> set[str]:
    """Return set of NAICS 2-digit sectors for a ticker's contracts."""
    sectors: set[str] = set()
    for c in contracts:
        naics = (c.get("naics_code") or "").strip()
        if len(naics) >= 2:
            sectors.add(naics[:2])
    return sectors


# ─────────────────────────────────────────────────────────────────────────────
# Scoring
# ─────────────────────────────────────────────────────────────────────────────

def _build_stats(
    contracts_by_ticker: dict[str, list[dict]],
    congress_by_ticker: dict[str, list[dict]],
    insider_by_ticker: dict[str, list[dict]],
    analyst_by_ticker: dict[str, dict],
    today: date,
) -> dict[str, TickerStats]:
    """Build per-ticker accumulators by walking each feed.

    Universe is union of contract/congress/insider tickers — analyst
    consensus alone does NOT qualify a ticker for a signal (Wall St
    "buys" without one of the other vectors carries no edge for our
    catalyst-based thesis). Analyst data is purely a confluence
    booster on tickers already flagged by the other three feeds.
    """
    all_tickers = set(contracts_by_ticker) | set(congress_by_ticker) | set(insider_by_ticker)
    out: dict[str, TickerStats] = {}

    for ticker in all_tickers:
        ts = TickerStats(ticker=ticker)

        # Contracts
        for c in contracts_by_ticker.get(ticker, []):
            ts.contracts.append(c)
            ts.contract_total_30d += c["award_amount"]
            ts.contract_max_single = max(ts.contract_max_single, c["award_amount"])
            if c["is_multi_year"]:
                ts.has_multi_year = True
            if _within_days(c["action_date"], 7, today):
                ts.has_recent_award = True
            if c["naics_code"] in PRIORITY_NAICS:
                ts.has_priority_naics = True

        # Congress
        for cg in congress_by_ticker.get(ticker, []):
            ts.congress_buys.append(cg)
            ts.congress_amount_total += cg["midpoint"]
            if _within_days(cg["filing_date"], 14, today):
                ts.has_recent_congress = True
        # Congress cluster bonus: 3+ unique politicians in trailing 30d.
        # Mirrors the existing insider cluster pattern — buyer diversity
        # is information beyond cumulative dollar amount (multiple
        # politicians independently choosing the same name).
        unique_politicians_30d: set[str] = set()
        for cg in congress_by_ticker.get(ticker, []):
            if _within_days(cg["filing_date"], 30, today):
                name = (cg.get("politician_name") or "").upper()
                if name:
                    unique_politicians_30d.add(name)
        ts.has_congress_cluster = len(unique_politicians_30d) >= 3

        # Insider
        unique_names = set()
        recent_30d_count = 0
        for ib in insider_by_ticker.get(ticker, []):
            ts.insider_buys.append(ib)
            ts.insider_value_total += ib["value_usd"]
            unique_names.add(ib["name"].upper())
            if _within_days(ib["transaction_date"], 30, today):
                recent_30d_count += 1
        ts.insider_unique_count = len(unique_names)
        # Cluster bonus: 3+ unique buyers in trailing 30d
        unique_30d = set()
        for ib in insider_by_ticker.get(ticker, []):
            if _within_days(ib["transaction_date"], 30, today):
                unique_30d.add(ib["name"].upper())
        ts.has_insider_cluster = len(unique_30d) >= 3

        # Analyst consensus lookup (Tweak #4) — no aggregation, just a
        # per-ticker snapshot. Missing tickers stay at default 0.
        ac = analyst_by_ticker.get(ticker)
        if ac:
            ts.analyst_consensus_score = ac["consensus_score"]
            ts.analyst_total_count = ac["total_count"]
            ts.analyst_label = ac["label"]

        out[ticker] = ts
    return out


def _score_contract(ts: TickerStats, ttm_revenue: float | None) -> tuple[float, float]:
    """Returns (contract_score, contract_impact_pct).

    impact_pct used for tier classification. Falls back to absolute-amount
    scoring when TTM revenue is unknown.
    """
    if not ts.contracts:
        return 0.0, 0.0

    if ttm_revenue and ttm_revenue > 0:
        impact_pct = ts.contract_total_30d / ttm_revenue
        # Map [0%, 20%] → [0, 100], cap at 100
        base = min(100.0, 100.0 * (impact_pct / 0.20))
    else:
        # Fallback: $50M rolling = 100. Above that capped.
        impact_pct = 0.0
        base = min(100.0, 100.0 * (ts.contract_total_30d / 50_000_000.0))

    bonus = 0.0
    if ts.has_multi_year:
        bonus += 15.0
    if ts.has_recent_award:
        bonus += 10.0
    if ts.has_priority_naics:
        bonus += 5.0
    score = max(0.0, min(100.0, base + bonus))
    return score, impact_pct


def _score_congress(ts: TickerStats) -> float:
    """Amount + recency + cluster (committees not populated yet).

    $1M total weighted = score 100 (clipped).
    Recency bonus +20 if any filing in last 14 days.
    Cluster bonus +20 if 3+ unique politicians bought in trailing 30d.
    Final value clipped to [0, 100].
    """
    if not ts.congress_buys:
        return 0.0
    base = min(100.0, ts.congress_amount_total / 10_000.0)  # $1M = 100
    if ts.has_recent_congress:
        base += 20.0
    if ts.has_congress_cluster:
        base += 20.0
    return max(0.0, min(100.0, base))


def _score_insider(ts: TickerStats) -> float:
    """Pure value-driven + cluster bonus for v1.

    $2M weighted total = score 100 (clipped).
    Cluster bonus +20 if 3+ unique insiders bought in trailing 30d.
    """
    if not ts.insider_buys:
        return 0.0
    base = min(100.0, ts.insider_value_total / 20_000.0)  # $2M = 100
    if ts.has_insider_cluster:
        base += 20.0
    return max(0.0, min(100.0, base))


def _score_analyst(ts: TickerStats) -> float:
    """Map analyst_consensus_score [-2..+2] → [0..100] (Tweak #4).

    Mechanic:
      - Below +1.0 (i.e. weaker than "BUY" consensus): score 0
        (consensus must reach BUY to count as a confluence vector;
         neutral/sell consensus is NOT a negative weight in this v1)
      - In [1.0, 2.0]: linear ramp 50 → 100
        (1.0 BUY → 50, 1.5 mid-BUY/STRONG → 75, 2.0 STRONG_BUY → 100)
      - <5 total analysts: half-weight to dampen small-sample bias

    Source: QuiverQuant Analyst Buys recipe. They weight forecasts by
    per-analyst historical track record (better-than-free-tier data);
    we approximate with the aggregate consensus from Finnhub free tier.
    """
    s = ts.analyst_consensus_score
    if s < 1.0:
        return 0.0
    base = 50.0 + 50.0 * (s - 1.0)  # 1.0 → 50, 2.0 → 100
    base = max(0.0, min(100.0, base))
    if ts.analyst_total_count < 5:
        base *= 0.5
    return base


def _compute_investment_score(ticker: str, confluence_score: float) -> float:
    """Composite investment score: 40% confluence + 30% fundamental + 30% technical.

    Fundamental: revenue growth, profit margin, debt/equity via yfinance.
    Technical: RSI health, SMA trend, 3-month momentum via yfinance history.
    """
    import yfinance as yf

    # Confluence component (40%)
    conf_component = min(confluence_score, 100.0) * 0.4

    # Fundamental component (30%)
    fund_score = 50.0  # neutral default
    try:
        info = yf.Ticker(ticker).info
        rev_growth = info.get("revenueGrowth") or 0
        profit_margin = info.get("profitMargins") or 0
        de = info.get("debtToEquity") or 0

        rg_pts = min(max(rev_growth * 100, -20), 40)  # -20 to +40
        pm_pts = min(max(profit_margin * 100, 0), 30)  # 0 to +30
        de_pts = max(30 - de / 5, 0) if de > 0 else 20  # lower debt = higher score

        fund_score = max(0, min(100, 30 + rg_pts + pm_pts + de_pts))
    except Exception:
        pass
    fund_component = fund_score * 0.3

    # Technical component (30%)
    tech_score = 50.0
    try:
        hist = yf.Ticker(ticker).history(period="3mo")
        if len(hist) >= 20:
            close = hist["Close"]
            price = float(close.iloc[-1])
            sma20 = float(close.rolling(20).mean().iloc[-1])
            sma50 = float(close.rolling(50).mean().iloc[-1]) if len(hist) >= 50 else sma20

            # RSI-14
            delta = close.diff()
            gain = delta.where(delta > 0, 0.0).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
            rs = gain.iloc[-1] / loss.iloc[-1] if loss.iloc[-1] > 0 else 100
            rsi = 100 - (100 / (1 + rs))

            # Score components
            trend_pts = 30 if price > sma50 else (15 if price > sma20 else 0)
            rsi_pts = 30 if 40 <= rsi <= 65 else (15 if 30 <= rsi <= 75 else 0)
            mom_3m = (price / float(close.iloc[0]) - 1) * 100
            mom_pts = min(max(mom_3m, -20), 40)

            tech_score = max(0, min(100, trend_pts + rsi_pts + mom_pts))
    except Exception:
        pass
    tech_component = tech_score * 0.3

    return round(conf_component + fund_component + tech_component, 1)


def _classify_tier(score: float, impact_pct: float, has_multi_year: bool) -> str:
    """A | B | "" per design doc §3."""
    if score >= TIER_B_MIN_SCORE and has_multi_year and impact_pct >= TIER_B_MIN_IMPACT_PCT:
        return "B"
    if score >= TIER_A_MIN_SCORE and impact_pct >= TIER_A_MIN_IMPACT_PCT:
        return "A"
    # Allow Tier A when revenue is unknown but score is high enough
    if score >= TIER_A_MIN_SCORE and impact_pct == 0.0:
        return "A"
    return ""


def _recommend_strategy(score: float, tier: str) -> str:
    """Map score+tier to BUY_DIP / LONG_CALL / PMCC."""
    if score >= 90:
        return "LONG_CALL"  # could be PMCC if IV high — brain decides at brief time
    if score >= 80:
        return "LONG_CALL"
    if score >= TIER_A_MIN_SCORE and tier == "A":
        return "BUY_DIP"
    return ""


def _build_action_text(ts: TickerStats, score: float, strategy: str) -> str:
    """One-line actionable summary for ping subject lines / log lines.

    Distinct from `_build_thesis` (which writes prose): this is the
    Telegram subject-line view — single line, dense stats, includes
    the recommended strategy and total score for at-a-glance scan.
    """
    parts = []
    if ts.contracts:
        parts.append(f"${ts.contract_total_30d/1e6:.1f}M contracts ({len(ts.contracts)})")
    if ts.congress_buys:
        parts.append(f"${ts.congress_amount_total/1e6:.2f}M Congress ({len(ts.congress_buys)})")
    if ts.insider_buys:
        parts.append(f"${ts.insider_value_total/1e6:.2f}M insider ({len(ts.insider_buys)})")
    body = " · ".join(parts)
    label = strategy or "WATCH"
    return f"{label} · score {score:.0f} · {body}" if body else f"{label} · score {score:.0f}"


def _build_thesis(
    ts: TickerStats,
    contract_score: float,
    congress_score: float,
    insider_score: float,
    analyst_score: float = 0.0,
) -> str:
    """Multi-sentence prose thesis in WSJ/Bloomberg style.

    Mirrors QuiverQuant's ChatGPT-Enhanced strategy format: 1-2 concise
    sentences citing the strongest catalyst(s) per signal, not a stat
    dump. Brain may rewrite/expand this at brief time; this is the
    rules-based default used for Telegram digests that fire BEFORE
    the brain runs.

    Source style ref: https://www.quiverquant.com/strategies/s/ChatGPT%20-%20Quiver%20Enhanced/
    """
    sentences: list[str] = []

    # Contract sentence — lead with the strongest contract fact.
    if ts.contracts:
        n = len(ts.contracts)
        total_m = ts.contract_total_30d / 1e6
        max_m = ts.contract_max_single / 1e6
        # Choose noun based on multi-year flag (IDIQ implies "contract")
        noun = "multi-year IDIQ" if ts.has_multi_year else "contract"
        sector_suffix = " in a top federal-spending sector" if ts.has_priority_naics else ""
        recency = "in the last 7 days" if ts.has_recent_award else "in the trailing 30 days"
        if n == 1:
            sentences.append(
                f"Captured a ${max_m:.1f}M {noun}{sector_suffix} {recency}."
            )
        else:
            # For stacks the noun is always plural "contracts"
            stack_suffix = " (multi-year IDIQ)" if ts.has_multi_year else ""
            sentences.append(
                f"Stacked {n} contracts totaling ${total_m:.1f}M (largest ${max_m:.1f}M){stack_suffix}{sector_suffix} {recency}."
            )

    # Confluence sentence — Congress + insider together.
    conf_bits: list[str] = []
    if ts.congress_buys:
        n_cg = len(ts.congress_buys)
        amt_m = ts.congress_amount_total / 1e6
        if ts.has_congress_cluster:
            conf_bits.append(f"{n_cg} Congress buys from 3+ distinct members totaling ${amt_m:.2f}M/30d")
        elif ts.has_recent_congress:
            conf_bits.append(f"{n_cg} Congress buys (${amt_m:.2f}M) with filings in last 14d")
        else:
            conf_bits.append(f"{n_cg} Congress buys totaling ${amt_m:.2f}M")
    if ts.insider_buys:
        n_ib = len(ts.insider_buys)
        ival_m = ts.insider_value_total / 1e6
        if ts.has_insider_cluster:
            conf_bits.append(f"insider cluster ({ts.insider_unique_count} unique buyers, ${ival_m:.2f}M)")
        else:
            conf_bits.append(f"{n_ib} insider buys worth ${ival_m:.2f}M")
    if conf_bits:
        sentences.append("Aligned " + " and ".join(conf_bits) + ".")

    # Analyst sentence (Tweak #4) — only when meaningful (BUY or STRONG_BUY
    # with >=5 covering analysts so we're not boosting on small-sample noise).
    if ts.analyst_label in ("STRONG_BUY", "BUY") and ts.analyst_total_count >= 5:
        label_pretty = ts.analyst_label.replace("_", " ").lower()
        sentences.append(
            f"Sell-side: {label_pretty} consensus across {ts.analyst_total_count} analysts."
        )

    # Score footer for transparency — terse breakdown including analyst.
    sentences.append(
        f"Score breakdown — contract {contract_score:.0f} / congress {congress_score:.0f} / "
        f"insider {insider_score:.0f} / analyst {analyst_score:.0f}."
    )

    return " ".join(sentences)


# ─────────────────────────────────────────────────────────────────────────────
# Output writers
# ─────────────────────────────────────────────────────────────────────────────

def _build_signal_rows(
    stats: dict[str, TickerStats],
    today_iso: str,
    sector_momentum: dict[str, dict] | None = None,
    contracts_by_ticker: dict[str, list[dict]] | None = None,
) -> list[S.GovConfluenceSignalRow]:
    """Compute scores + materialise GovConfluenceSignalRow for all qualifying tickers.

    Includes sector momentum bonus: tickers in "hot" NAICS sectors
    (30d spend > 1.5× 90d average) get a +8 score boost.
    """
    out: list[S.GovConfluenceSignalRow] = []
    now_iso = S.now_sgt_iso()
    sector_momentum = sector_momentum or {}
    contracts_by_ticker = contracts_by_ticker or {}

    for ticker, ts in stats.items():
        ttm_rev, mkt_cap = _fetch_fundamentals(ticker)
        contract_score, impact_pct = _score_contract(ts, ttm_revenue=ttm_rev)
        mat = compute_materiality(
            ts.contract_total_30d, ts.insider_value_total, ttm_rev, mkt_cap,
            congress_usd=ts.congress_amount_total,
        )
        congress_score = _score_congress(ts)
        insider_score = _score_insider(ts)
        analyst_score = _score_analyst(ts)
        score = (
            W_CONTRACT * contract_score
            + W_CONGRESS * congress_score
            + W_INSIDER  * insider_score
            + W_ANALYST  * analyst_score
        )

        # Sector momentum bonus: if this ticker's contracts are in a "hot" sector
        ticker_sectors = _ticker_naics_sectors(contracts_by_ticker.get(ticker, []))
        hot_sectors = [
            sector_momentum[s]["sector_name"]
            for s in ticker_sectors
            if s in sector_momentum and sector_momentum[s]["is_hot"]
        ]
        if hot_sectors:
            score += SECTOR_MOMENTUM_BONUS

        if score < MIN_SCORE_TO_PERSIST:
            continue
        tier = _classify_tier(score, impact_pct, ts.has_multi_year)
        strategy = _recommend_strategy(score, tier)
        # Build thesis with sector momentum note
        thesis = _build_thesis(ts, contract_score, congress_score, insider_score, analyst_score)
        if hot_sectors:
            thesis += f" Sector momentum: {', '.join(hot_sectors)} spending surging (30d > 1.5× 90d avg)."

        inv_score = _compute_investment_score(ticker, score)

        out.append(S.GovConfluenceSignalRow(
            date=today_iso,
            ticker=ticker,
            confluence_score=score,
            contract_score=contract_score,
            congress_score=congress_score,
            insider_score=insider_score,
            analyst_score=analyst_score,
            tier=tier,
            recommended_strategy=strategy,
            recommended_action=_build_action_text(ts, score, strategy),
            thesis_oneliner=thesis,
            contributing_contracts=json.dumps([c["award_id"] for c in ts.contracts[:20]]),
            contributing_congress_trades=json.dumps([c["filing_id"] for c in ts.congress_buys[:20]]),
            contributing_insider_buys=json.dumps([b["id"] for b in ts.insider_buys[:20]]),
            updated_at=now_iso,
            investment_score=inv_score,
            contract_usd=ts.contract_total_30d,
            contract_pct_rev=mat["contract_pct_rev"],
            contract_pct_mktcap=mat["contract_pct_mktcap"],
            insider_usd=ts.insider_value_total,
            insider_pct_mktcap=mat["insider_pct_mktcap"],
            materiality=mat["materiality"],
            market_cap=mat["market_cap"],
            ttm_revenue=mat["ttm_revenue"],
            congress_usd=ts.congress_amount_total,
            congress_pct_mktcap=mat["congress_pct_mktcap"],
        ))
    out.sort(key=lambda r: r.confluence_score, reverse=True)
    return out


def _upsert_signals(client, signals: list[S.GovConfluenceSignalRow], logger: logging.Logger) -> None:
    """Write today's signals, replacing any prior rows with the same (date, ticker)."""
    if not signals:
        return
    sh.ensure_headers(client, S.GovConfluenceSignalRow.TAB_NAME, S.GovConfluenceSignalRow.HEADERS)
    ss = sh._open_sheet(client)
    ws = ss.worksheet(S.GovConfluenceSignalRow.TAB_NAME)

    today_keys = {(s.date, s.ticker) for s in signals}
    existing = ws.get_all_values()
    keep = [existing[0]] if existing else [S.GovConfluenceSignalRow.HEADERS]
    if existing and len(existing) > 1:
        hdr = existing[0]
        c_date = hdr.index("date") if "date" in hdr else 0
        c_tk = hdr.index("ticker") if "ticker" in hdr else 1
        for r in existing[1:]:
            if len(r) > max(c_date, c_tk):
                if (r[c_date], r[c_tk]) not in today_keys:
                    keep.append(r)

    keep.extend([s.to_row() for s in signals])
    ws.clear()
    ws.update("A1", keep, value_input_option="USER_ENTERED")
    logger.info(f"  ✓ wrote {len(signals)} signals to {S.GovConfluenceSignalRow.TAB_NAME}")


def _append_to_decision_queue(client, signals: list[S.GovConfluenceSignalRow], logger: logging.Logger) -> int:
    """Append Tier A/B picks to decision_queue with appropriate strategy."""
    actionable = [s for s in signals if s.recommended_strategy and s.tier in ("A", "B")]
    if not actionable:
        return 0

    # Read existing decision_queue to avoid duplicating today's gov_confluence rows
    ss = sh._open_sheet(client)
    try:
        ws = ss.worksheet(S.DecisionRow.TAB_NAME)
    except Exception:
        sh.ensure_headers(client, S.DecisionRow.TAB_NAME, S.DecisionRow.HEADERS)
        ws = ss.worksheet(S.DecisionRow.TAB_NAME)
    existing = ws.get_all_values()
    today_existing: set[tuple[str, str]] = set()
    if len(existing) > 1:
        hdr = existing[0]
        try:
            c_date = hdr.index("date")
            c_tk = hdr.index("ticker")
            c_src = hdr.index("source") if "source" in hdr else -1
        except ValueError:
            c_date = c_tk = c_src = -1
        if c_date >= 0 and c_tk >= 0:
            for r in existing[1:]:
                if len(r) > max(c_date, c_tk):
                    src_ok = (c_src < 0) or (len(r) > c_src and r[c_src] == "gov_confluence")
                    if src_ok:
                        today_existing.add((r[c_date], r[c_tk]))

    new_rows = []
    for s in actionable:
        if (s.date, s.ticker) in today_existing:
            continue
        # Map to DecisionRow shape
        d = S.DecisionRow(
            date=s.date,
            account="caspar",  # default — brain may switch to sarah later
            ticker=s.ticker,
            bucket="GOV_CONFLUENCE",
            thesis_1liner=(s.recommended_action or "")[:500],
            conv=4 if s.tier == "B" else 3,
            entry=0.0,  # brain fills at brief time
            target=0.0,
            status="watching",
            strategy=s.recommended_strategy,
            right=("C" if s.recommended_strategy in ("LONG_CALL", "PMCC") else ""),
            strike=0.0,
            expiry="",
            premium_per_share=0.0,
            delta=0.50 if s.recommended_strategy == "LONG_CALL" else 0.0,
            annual_yield_pct=0.0,
            breakeven=0.0,
            cash_required=0.0,
            iv_rank=0.0,
            thesis_confidence=s.confluence_score / 100.0,
            thesis=s.thesis_oneliner,
            source="gov_confluence",
            qty=0,
            accumulation_plan="",
            gates="[]",
        )
        new_rows.append(d.to_row())

    if not new_rows:
        logger.info(f"  · {len(actionable)} actionable signals all already in decision_queue today")
        return 0

    sh.append_rows(client, S.DecisionRow.TAB_NAME, new_rows)
    logger.info(f"  ✓ appended {len(new_rows)} rows to {S.DecisionRow.TAB_NAME} (strategy=BUY_DIP/LONG_CALL/PMCC)")
    return len(new_rows)


# Thresholds for SELL → TRIM emission (Tweak #2).
# Conservative — we don't want noise. Either 2+ distinct politicians
# selling OR a single politician selling >= $500K midpoint qualifies.
TRIM_MIN_POLITICIANS = 2
TRIM_MIN_AMOUNT = 500_000.0


def _append_sell_signals_to_queue(
    client,
    sells_by_ticker: dict[str, list[dict]],
    held_tickers: set[str],
    today_iso: str,
    logger: logging.Logger,
) -> int:
    """Emit TRIM rows to decision_queue for currently-held tickers with
    a cluster of Congress sells. Long-only equivalent of QuiverQuant's
    Congress L/S short side — we don't short, but Congress sells of a
    name we OWN carry trim information.

    Gate: ticker must be currently held AND (>=2 unique politicians OR
    cumulative midpoint >= $500K). Brain reviews next morning before
    any actual trim action.
    """
    candidates: list[tuple[str, list[dict]]] = []
    for ticker, sells in sells_by_ticker.items():
        if ticker not in held_tickers:
            continue
        unique_politicians = {
            (s.get("politician_name") or "").upper()
            for s in sells
            if s.get("politician_name")
        }
        total_midpoint = sum(s["midpoint"] for s in sells)
        if len(unique_politicians) >= TRIM_MIN_POLITICIANS or total_midpoint >= TRIM_MIN_AMOUNT:
            candidates.append((ticker, sells))

    if not candidates:
        logger.info("  · no Congress-sell TRIM candidates among held tickers")
        return 0

    ss = sh._open_sheet(client)
    try:
        ws = ss.worksheet(S.DecisionRow.TAB_NAME)
    except Exception:
        sh.ensure_headers(client, S.DecisionRow.TAB_NAME, S.DecisionRow.HEADERS)
        ws = ss.worksheet(S.DecisionRow.TAB_NAME)
    existing = ws.get_all_values()
    today_existing: set[tuple[str, str]] = set()
    if len(existing) > 1:
        hdr = existing[0]
        try:
            c_date = hdr.index("date")
            c_tk = hdr.index("ticker")
            c_src = hdr.index("source") if "source" in hdr else -1
        except ValueError:
            c_date = c_tk = c_src = -1
        if c_date >= 0 and c_tk >= 0:
            for r in existing[1:]:
                if len(r) > max(c_date, c_tk):
                    src_ok = (c_src < 0) or (len(r) > c_src and r[c_src] == "gov_confluence_sell")
                    if src_ok:
                        today_existing.add((r[c_date], r[c_tk]))

    new_rows = []
    for ticker, sells in candidates:
        if (today_iso, ticker) in today_existing:
            continue
        unique_politicians = {
            (s.get("politician_name") or "").upper()
            for s in sells
            if s.get("politician_name")
        }
        n_pol = len(unique_politicians)
        total = sum(s["midpoint"] for s in sells)
        thesis = f"Congress sells: ${total/1e6:.2f}M from {n_pol} politician(s)/30d"
        d = S.DecisionRow(
            date=today_iso,
            account="caspar",  # brain reassigns to actual holder at brief time
            ticker=ticker,
            bucket="GOV_CONFLUENCE_TRIM",
            thesis_1liner=thesis,
            conv=2,  # lower than buys — review required
            entry=0.0,
            target=0.0,
            status="watching",
            strategy="TRIM",
            right="",
            strike=0.0,
            expiry="",
            premium_per_share=0.0,
            delta=0.0,
            annual_yield_pct=0.0,
            breakeven=0.0,
            cash_required=0.0,
            iv_rank=0.0,
            thesis_confidence=0.5,
            thesis=thesis,
            source="gov_confluence_sell",
            qty=0,
            accumulation_plan="",
            gates="[]",
        )
        new_rows.append(d.to_row())

    if not new_rows:
        logger.info(f"  · {len(candidates)} TRIM candidates all already in decision_queue today")
        return 0

    sh.append_rows(client, S.DecisionRow.TAB_NAME, new_rows)
    logger.info(f"  ✓ appended {len(new_rows)} TRIM rows to {S.DecisionRow.TAB_NAME}")
    return len(new_rows)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry", action="store_true", help="Print plan, no sheet write")
    args = p.parse_args()

    logger = _setup_logging()
    logger.info(f"screen_gov_confluence start (dry={args.dry})")

    load_env()
    client = sh.authenticate()
    today = date.today()
    today_iso = today.isoformat()

    contracts = _read_gov_contracts(client, today)
    congress = _read_congress_trades(client, today)
    insider = _read_insider_buys(client, today)
    # Tweak #2 — also pull Congress sells for the TRIM emitter.
    sells = _read_congress_sells(client, today)
    # Tweak #4 — analyst consensus as 4th confluence vector.
    analyst = _read_analyst_consensus(client)

    if not (contracts or congress or insider or sells):
        logger.info("All feeds empty — nothing to score")
        return 0

    stats = _build_stats(contracts, congress, insider, analyst, today)
    logger.info(f"Computed stats for {len(stats)} unique tickers")

    # Sector momentum: aggregate awards by NAICS 2-digit sector
    sector_mom = _compute_sector_momentum(contracts, today)
    hot = {s: v for s, v in sector_mom.items() if v["is_hot"]}
    if hot:
        logger.info(f"Sector momentum: {len(hot)} hot sectors:")
        for s, v in sorted(hot.items(), key=lambda x: x[1]["ratio"], reverse=True):
            logger.info(f"  NAICS {s} ({v['sector_name']}): "
                        f"30d ${v['total_30d']/1e6:.1f}M vs 90d-equiv ${v['avg_90d_30d_equiv']/1e6:.1f}M "
                        f"({v['ratio']:.1f}×)")
    else:
        logger.info("Sector momentum: no hot sectors detected")

    signals = _build_signal_rows(stats, today_iso, sector_momentum=sector_mom, contracts_by_ticker=contracts)
    logger.info(f"  · {len(signals)} signals scored >= {MIN_SCORE_TO_PERSIST}")

    if signals:
        logger.info("Top 10 by confluence score:")
        for s in signals[:10]:
            logger.info(
                f"  {s.ticker:6s}  score {s.confluence_score:5.1f}  "
                f"tier={s.tier or '-':1s}  strat={s.recommended_strategy or '-':10s}  "
                f"({s.thesis_oneliner})"
            )

    # Tweak #2 — gate TRIM emission on currently-held tickers.
    held = _read_held_tickers(client)

    if args.dry:
        logger.info("[DRY] no writes performed")
        # Report what TRIM emission WOULD do so we can verify behaviour pre-flight.
        sell_candidates = [
            (t, len({(s.get("politician_name") or "").upper() for s in v if s.get("politician_name")}),
                sum(s["midpoint"] for s in v))
            for t, v in sells.items()
            if t in held
            and (
                len({(s.get("politician_name") or "").upper() for s in v if s.get("politician_name")}) >= TRIM_MIN_POLITICIANS
                or sum(s["midpoint"] for s in v) >= TRIM_MIN_AMOUNT
            )
        ]
        if sell_candidates:
            logger.info(f"[DRY] would emit {len(sell_candidates)} TRIM candidates:")
            for t, n_pol, total in sell_candidates:
                logger.info(f"  · {t}: {n_pol} politicians, ${total/1e6:.2f}M total")
        else:
            logger.info("[DRY] no TRIM candidates (no overlap of Congress sells with held tickers)")
        return 0

    _upsert_signals(client, signals, logger)
    # NOTE: we no longer write directly to decision_queue here.
    # Gov confluence is ONE signal among many (RSI, EMA, SMA, P/E, etc.).
    # The brain (daily brief / WSR) reads gov_confluence_signals alongside
    # all other indicators and makes its own decisions with full technical
    # context.  Direct decision_queue writes from the screener produced
    # bare-bones rows ("Congress sells: $0.02M") with no technicals.
    logger.info(
        f"screen_gov_confluence done — {len(signals)} signals written to "
        f"gov_confluence_signals (brain incorporates into decisions)"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
