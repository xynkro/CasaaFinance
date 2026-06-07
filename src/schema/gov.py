# ── Government Spending Confluence Strategy ────────────────────────────────
# Five tabs powering the USAspending + CapitolTrades + insider feed
# combined into per-ticker confluence signals. Designed in
# docs/plans/2026-05-10-gov-spending-confluence-strategy-design.md.
"""Government-spending confluence schemas: contracts, congressional trades,
recipient→ticker mapping, unmapped recipients, and per-ticker confluence signals."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from ._base import _num


@dataclass
class GovContractRow:
    """One row per (award_id, modification) pulled from USAspending.gov.

    Daily snapshot fetched from `POST /api/v2/search/spending_by_award`
    filtered to yesterday's `action_date`. Recipient name is normalized
    upstream and `ticker` is resolved via `recipient_ticker_map` (empty
    if not in the seed map).
    """
    TAB_NAME = "gov_contracts"
    HEADERS = [
        "audit_ts", "award_id", "action_date",
        "recipient_name", "parent_recipient_name", "ticker",
        "award_amount", "tcv",
        "agency", "naics_code", "naics_description",
        "period_start", "period_end",
        "place_of_performance_state",
        "description",
    ]

    audit_ts: str
    award_id: str
    action_date: str
    recipient_name: str
    parent_recipient_name: str
    ticker: str
    award_amount: float
    tcv: float
    agency: str
    naics_code: str
    naics_description: str
    period_start: str
    period_end: str
    place_of_performance_state: str
    description: str

    def to_row(self) -> List[str]:
        return [
            self.audit_ts, self.award_id, self.action_date,
            self.recipient_name, self.parent_recipient_name, self.ticker,
            _num(self.award_amount), _num(self.tcv),
            self.agency, self.naics_code, self.naics_description,
            self.period_start, self.period_end,
            self.place_of_performance_state,
            (self.description or "")[:200],
        ]


@dataclass
class CongressTradeRow:
    """One row per CapitolTrades politician trade filing.

    Source scraped daily from capitoltrades.com/trades. STOCK Act lag is
    7-30 days post-trade so this is a confluence/confirmation signal,
    never the primary trigger. Amount is disclosed as a range bucket
    ($1M-$5M etc.); both endpoints stored for screener flexibility.
    """
    TAB_NAME = "congress_trades"
    HEADERS = [
        "audit_ts", "filing_id",
        "politician_id", "politician_name", "party", "chamber",
        "committees",
        "ticker", "issuer_name",
        "transaction_date", "filing_date",
        "transaction_type",
        "amount_min", "amount_max",
    ]

    audit_ts: str
    filing_id: str
    politician_id: str
    politician_name: str
    party: str
    chamber: str
    committees: str  # JSON-encoded array
    ticker: str
    issuer_name: str
    transaction_date: str
    filing_date: str
    transaction_type: str  # "buy" | "sell" | "exchange"
    amount_min: float
    amount_max: float

    def to_row(self) -> List[str]:
        return [
            self.audit_ts, self.filing_id,
            self.politician_id, self.politician_name, self.party, self.chamber,
            self.committees,
            self.ticker, self.issuer_name,
            self.transaction_date, self.filing_date,
            self.transaction_type,
            _num(self.amount_min), _num(self.amount_max),
        ]


@dataclass
class RecipientTickerMapRow:
    """Manual seed table mapping USAspending recipient names to public tickers.

    Maintained by hand. `recipient_name_normalized` is the lookup key
    (uppercase, punctuation-stripped, common-suffix-dropped, sorted token
    join — see src/recipient_ticker.py::normalize). Top ~150 entries cover
    ~85% of total contract dollar volume.
    """
    TAB_NAME = "recipient_ticker_map"
    HEADERS = [
        "recipient_name_normalized",
        "recipient_name_raw",
        "parent_ticker",
        "confidence",
        "notes",
        "updated_at",
    ]

    recipient_name_normalized: str
    recipient_name_raw: str
    parent_ticker: str
    confidence: str  # "high" | "medium" | "low"
    notes: str
    updated_at: str

    def to_row(self) -> List[str]:
        return [
            self.recipient_name_normalized, self.recipient_name_raw,
            self.parent_ticker, self.confidence, self.notes, self.updated_at,
        ]


@dataclass
class GovUnmappedRecipientRow:
    """Auto-flagged recipient names with award >= $5M not yet in the map.

    Auto-populated by the screener for weekly review. Caspar adds true
    publicly-listed names to recipient_ticker_map; ignores the rest
    (private companies, foreign entities without ADRs, etc.).
    """
    TAB_NAME = "gov_unmapped_recipients"
    HEADERS = [
        "first_seen_ts", "recipient_name", "recipient_name_normalized",
        "total_award_amount", "contract_count", "biggest_award_id",
        "agency", "last_seen_ts",
    ]

    first_seen_ts: str
    recipient_name: str
    recipient_name_normalized: str
    total_award_amount: float
    contract_count: int
    biggest_award_id: str
    agency: str
    last_seen_ts: str

    def to_row(self) -> List[str]:
        return [
            self.first_seen_ts, self.recipient_name, self.recipient_name_normalized,
            _num(self.total_award_amount), str(self.contract_count),
            self.biggest_award_id, self.agency, self.last_seen_ts,
        ]


@dataclass
class GovConfluenceSignalRow:
    """Per-ticker daily output of the confluence screener.

    Score = 0.40 * contract_score + 0.30 * congress_score + 0.30 * insider_score.
    Tier A = score >=70 AND contract_impact >= 1% TTM rev.
    Tier B = score >=80 AND multi-year contract AND contract_impact >= 5% TTM rev.
    Brain reads this in daily-brief / WSR and may override the rules-based
    `recommended_strategy`.
    """
    TAB_NAME = "gov_confluence_signals"
    HEADERS = [
        "date", "ticker",
        "confluence_score",
        "contract_score", "congress_score", "insider_score", "analyst_score",
        "tier",
        "recommended_strategy",
        "recommended_action",
        "thesis_oneliner",
        "contributing_contracts",
        "contributing_congress_trades",
        "contributing_insider_buys",
        "updated_at",
        "investment_score",
        # Materiality — how big is the bet vs the company, so you can judge
        # whether it can actually move the stock (appended; back-compatible).
        "contract_usd",          # 30d contract award total ($)
        "contract_pct_rev",      # contract_usd / TTM revenue (fraction)
        "contract_pct_mktcap",   # contract_usd / market cap (fraction)
        "insider_usd",           # 30d insider buy total ($)
        "insider_pct_mktcap",    # insider_usd / market cap (fraction)
        "materiality",           # HUGE | MATERIAL | NOTABLE | IMMATERIAL | ""
        # Company size + Congress flow (appended; back-compatible) so the PWA
        # can show the bet relative to the company's actual valuation.
        "market_cap",            # company market cap ($), 0 if unknown
        "ttm_revenue",           # trailing-twelve-month revenue ($), 0 if unknown
        "congress_usd",          # 60d Congress buy total ($, midpoint of ranges)
        "congress_pct_mktcap",   # congress_usd / market cap (fraction)
    ]

    date: str
    ticker: str
    confluence_score: float
    contract_score: float
    congress_score: float
    insider_score: float
    analyst_score: float = 0.0
    tier: str = ""  # "A" | "B" | ""
    recommended_strategy: str = ""  # "BUY_DIP" | "LONG_CALL" | "PMCC" | ""
    recommended_action: str = ""
    thesis_oneliner: str = ""
    contributing_contracts: str = ""  # JSON array of award_ids
    contributing_congress_trades: str = ""  # JSON array of filing_ids
    contributing_insider_buys: str = ""  # JSON array of insider tx ids
    updated_at: str = ""
    investment_score: float = 0.0  # composite: 40% confluence + 30% fundamental + 30% technical
    contract_usd: float = 0.0          # 30d contract award total ($)
    contract_pct_rev: float = 0.0      # contract_usd / TTM revenue (fraction)
    contract_pct_mktcap: float = 0.0   # contract_usd / market cap (fraction)
    insider_usd: float = 0.0           # 30d insider buy total ($)
    insider_pct_mktcap: float = 0.0    # insider_usd / market cap (fraction)
    materiality: str = ""              # HUGE | MATERIAL | NOTABLE | IMMATERIAL | ""
    market_cap: float = 0.0            # company market cap ($), 0 if unknown
    ttm_revenue: float = 0.0           # TTM revenue ($), 0 if unknown
    congress_usd: float = 0.0          # 60d Congress buy total ($)
    congress_pct_mktcap: float = 0.0   # congress_usd / market cap (fraction)

    def to_row(self) -> List[str]:
        return [
            self.date, self.ticker,
            _num(self.confluence_score, 1),
            _num(self.contract_score, 1),
            _num(self.congress_score, 1),
            _num(self.insider_score, 1),
            _num(self.analyst_score, 1),
            self.tier,
            self.recommended_strategy,
            self.recommended_action,
            self.thesis_oneliner,
            self.contributing_contracts,
            self.contributing_congress_trades,
            self.contributing_insider_buys,
            self.updated_at,
            _num(self.investment_score, 1),
            _num(self.contract_usd, 0),
            _num(self.contract_pct_rev, 4),
            _num(self.contract_pct_mktcap, 4),
            _num(self.insider_usd, 0),
            _num(self.insider_pct_mktcap, 4),
            self.materiality,
            _num(self.market_cap, 0),
            _num(self.ttm_revenue, 0),
            _num(self.congress_usd, 0),
            _num(self.congress_pct_mktcap, 4),
        ]
