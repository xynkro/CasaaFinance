"""screen_gov_confluence.py — daily confluence scorer.

Joins three feeds (gov_contracts + congress_trades + insider_transactions)
into a per-ticker confluence score and writes:

  1. gov_confluence_signals — one row per (date, ticker) where score >= 60
  2. decision_queue — appended rows for Tier A / B picks with strategy
     (BUY_DIP / LONG_CALL / PMCC) populated

Score formula (per design doc §3):
  score = 0.40 * contract_score + 0.30 * congress_score + 0.30 * insider_score

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

# Weights (sum to 1.00). Re-balanced from 40/30/30 to 35/25/25/15
# to add analyst consensus as the 4th vector. Inspired by QuiverQuant's
# Analyst Buys strategy (78% win rate, Sharpe 0.92 over 3y) showing
# weighted analyst signal adds real alpha when combined with cluster/
# insider data. Source: https://www.quiverquant.com/strategies/s/Analyst%20Buys/
W_CONTRACT = 0.35
W_CONGRESS = 0.25
W_INSIDER  = 0.25
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

def _build_signal_rows(stats: dict[str, TickerStats], today_iso: str) -> list[S.GovConfluenceSignalRow]:
    """Compute scores + materialise GovConfluenceSignalRow for all qualifying tickers."""
    out: list[S.GovConfluenceSignalRow] = []
    now_iso = S.now_sgt_iso()
    for ticker, ts in stats.items():
        # TTM revenue not wired in v1 — fall back to absolute-amount scoring
        contract_score, impact_pct = _score_contract(ts, ttm_revenue=None)
        congress_score = _score_congress(ts)
        insider_score = _score_insider(ts)
        analyst_score = _score_analyst(ts)
        score = (
            W_CONTRACT * contract_score
            + W_CONGRESS * congress_score
            + W_INSIDER  * insider_score
            + W_ANALYST  * analyst_score
        )
        if score < MIN_SCORE_TO_PERSIST:
            continue
        tier = _classify_tier(score, impact_pct, ts.has_multi_year)
        strategy = _recommend_strategy(score, tier)
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
            thesis_oneliner=_build_thesis(ts, contract_score, congress_score, insider_score, analyst_score),
            contributing_contracts=json.dumps([c["award_id"] for c in ts.contracts[:20]]),
            contributing_congress_trades=json.dumps([c["filing_id"] for c in ts.congress_buys[:20]]),
            contributing_insider_buys=json.dumps([b["id"] for b in ts.insider_buys[:20]]),
            updated_at=now_iso,
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

    signals = _build_signal_rows(stats, today_iso)
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
