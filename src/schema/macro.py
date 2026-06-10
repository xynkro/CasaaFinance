"""Macro + market-regime + calendar + news/insider + live-price + risk-parity
schemas, and the macro factory helper."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from ._base import _num, _ts_suffix


@dataclass
class MacroRow:
    TAB_NAME = "macro"
    # spx_above_200sma is APPENDED LAST (same precedent as SignalOutcomeRow's
    # pnl_model) so legacy 6-col rows stay positionally aligned on read-back.
    # Written by macro_grab (SPX close vs its 200-day SMA); read by the macro
    # gate + paper executor as the trend-halt input. TRUE/FALSE, '' = unknown
    # (downstream treats unknown as degraded → reduced sizing, never full-size).
    HEADERS = ["date", "vix", "dxy", "us_10y", "spx", "usd_sgd", "spx_above_200sma"]

    date: str
    vix: float | None = None
    dxy: float | None = None
    us_10y: float | None = None
    spx: float | None = None
    usd_sgd: float | None = None
    spx_above_200sma: bool | None = None

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        sa = "" if self.spx_above_200sma is None else ("TRUE" if self.spx_above_200sma else "FALSE")
        return [d, _num(self.vix, 2), _num(self.dxy, 3), _num(self.us_10y, 3),
                _num(self.spx, 2), _num(self.usd_sgd, 4), sa]


@dataclass
class RegimeSignalRow:
    """
    Daily snapshot of one regime indicator. Append-only audit trail.
    The brain (Opus WSR Full / Lite) reads the latest row per `source` to
    ground its regime classification rather than vibes-classifying.

    Sources expected:
      - "market_breadth"      (no API key — runs every day)
      - "ftd"                 (FMP key required)
      - "distribution_day"    (FMP key required)
      - "macro_regime"        (FMP key required)
      - "market_top"          (FMP key required + breadth args)
    """
    TAB_NAME = "regime_signals"
    HEADERS = [
        "date", "source", "score", "label", "summary", "raw_json",
    ]

    date: str
    source: str         # see docstring above
    score: float        # 0-100 normalized per-source
    label: str          # short tag e.g. "Weakening" | "FTD_CONFIRMED" | "HIGH_RISK"
    summary: str        # 1-line human-readable
    raw_json: str       # full skill output (truncated to 5KB)

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        # Truncate raw_json to 5KB to stay well below Sheets cell limit (50K).
        raw = self.raw_json or ""
        if len(raw) > 5000:
            raw = raw[:5000] + "...[truncated]"
        return [d, self.source, _num(self.score, 1), self.label, self.summary, raw]


@dataclass
class ExposurePostureRow:
    """
    Daily exposure-coach output — synthesizes regime_signals + portfolio
    state into a single posture decision. Brain reads latest row to constrain
    new entries vs cash priority.
    """
    TAB_NAME = "exposure_posture"
    HEADERS = [
        "date", "exposure_ceiling_pct", "bias", "participation",
        "recommendation", "confidence", "rationale", "components_json",
    ]

    date: str
    exposure_ceiling_pct: float       # 0-100
    bias: str                         # "GROWTH" | "VALUE" | "NEUTRAL"
    participation: str                # "BROAD" | "NARROW"
    recommendation: str               # "NEW_ENTRY_ALLOWED" | "REDUCE_ONLY" | "CASH_PRIORITY"
    confidence: str                   # "HIGH" | "MEDIUM" | "LOW"
    rationale: str                    # multi-sentence explanation incl. headroom
    components_json: str              # all 8 component scores as JSON

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        comp = self.components_json or ""
        if len(comp) > 5000:
            comp = comp[:5000] + "...[truncated]"
        return [
            d, _num(self.exposure_ceiling_pct, 0),
            self.bias, self.participation, self.recommendation,
            self.confidence, self.rationale, comp,
        ]


@dataclass
class RiskParityAuditRow:
    """
    Daily diversification hygiene check — Risk Parity LITE.

    For each (account, asset_class), records the current capital
    allocation, an estimated annualised vol, the implied risk
    contribution, the configured target weight, and a rebalance
    suggestion. 8 asset classes × 2 accounts = 16 rows per run.

    Read by the brain prompts (Agent 2) to require at least one
    underweight-class proposal per WSR run, and surfaced in the PWA
    Risk Parity LITE panel.

    Targets live in `config/risk_parity_targets.yaml` — equity stays
    dominant (this is a wheel-strategy book) but bonds/gold/vol are
    held to a non-zero floor for diversification.
    """
    TAB_NAME = "risk_parity_audit"
    HEADERS = [
        "date", "account",                  # "caspar" | "sarah"
        "asset_class",                      # one of 8 canonical values
        "capital_pct",                      # % of NLV in this class (capital weight)
        "vol_pct",                          # estimated annualized vol of holdings in this class
        "risk_contribution_pct",            # capital_pct × vol_pct, normalized so total = 100%
        "target_pct",                       # configured target (per-account)
        "delta_pct",                        # capital_pct - target_pct (positive = over)
        "rebalance_action",                 # "OVERWEIGHT" | "UNDERWEIGHT" | "ON_TARGET"
        "rebalance_amount_usd",             # $ amount to shift to hit target
        "rationale",                        # 1-line explanation
    ]

    date: str
    account: str               # "caspar" | "sarah"
    asset_class: str           # one of CANONICAL_ASSET_CLASSES
    capital_pct: float         # 0-100
    vol_pct: float             # 0-100 (annualized)
    risk_contribution_pct: float  # 0-100, normalized
    target_pct: float          # 0-100
    delta_pct: float           # signed
    rebalance_action: str      # "OVERWEIGHT" | "UNDERWEIGHT" | "ON_TARGET"
    rebalance_amount_usd: float
    rationale: str

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        return [
            d, self.account, self.asset_class,
            _num(self.capital_pct, 2), _num(self.vol_pct, 2),
            _num(self.risk_contribution_pct, 2),
            _num(self.target_pct, 2), _num(self.delta_pct, 2),
            self.rebalance_action,
            _num(self.rebalance_amount_usd, 2),
            self.rationale,
        ]


@dataclass
class EarningsRow:
    """
    Earnings calendar entry — one row per (ticker, quarter). Refreshed
    daily by `scripts/finnhub_calendars.py` from Finnhub's
    `calendar/earnings` endpoint.

    The brain reads this in:
      - Daily Brief: "today's earnings" section (companies reporting BMO/AMC)
      - WSR Lite: "Friday earnings preview" + "DTE-inside earnings" warnings
      - WSR Full: "earnings within 14 days" table per portfolio + watchlist

    PWA shows an earnings badge ("ER 5/15") on Decision cards when the
    ticker has earnings inside the option DTE — flags assignment-risk.

    UPSERT key: (ticker, year, quarter). Re-pulls overwrite the same
    row when actual EPS/revenue land post-print.
    """
    TAB_NAME = "earnings_calendar"
    HEADERS = [
        "date",            # earnings date YYYY-MM-DD
        "ticker",
        "hour",            # "bmo" (before mkt open) | "amc" (after mkt close) | "dmh" (during)
        "year", "quarter",
        "eps_estimate", "eps_actual",
        "revenue_estimate", "revenue_actual",
        "surprise_pct",    # ((actual - estimate) / abs(estimate)) × 100; "" if not yet reported
        "updated_at",      # SGT iso "YYYY-MM-DDTHHMMSS"
    ]

    date: str
    ticker: str
    hour: str
    year: int
    quarter: int
    eps_estimate: float | None
    eps_actual: float | None
    revenue_estimate: float | None
    revenue_actual: float | None
    surprise_pct: float | None
    updated_at: str

    def to_row(self, audit: bool = True) -> List[str]:
        return [
            self.date, self.ticker, self.hour,
            str(self.year), str(self.quarter),
            _num(self.eps_estimate, 4) if self.eps_estimate is not None else "",
            _num(self.eps_actual, 4) if self.eps_actual is not None else "",
            _num(self.revenue_estimate, 0) if self.revenue_estimate is not None else "",
            _num(self.revenue_actual, 0) if self.revenue_actual is not None else "",
            _num(self.surprise_pct, 2) if self.surprise_pct is not None else "",
            self.updated_at,
        ]


@dataclass
class EconomicEventRow:
    """
    Economic event calendar — macro releases (CPI/NFP/FOMC/GDP) for the
    next 14 days. Refreshed daily by `scripts/finnhub_calendars.py`.

    The brain reads this in:
      - Daily Brief: "today's macro events" section with importance flag
      - WSR Lite: "next 72-hour catalyst window" warnings
      - WSR Full: "macro week-ahead" table

    PWA shows a "Macro this week" widget on Home for the next 7 days of
    HIGH-importance events.

    UPSERT key: (date, time, country, event). Same event re-pulled for
    forecast/actual updates without duplication.
    """
    TAB_NAME = "economic_calendar"
    HEADERS = [
        "date",          # YYYY-MM-DD
        "time",          # HH:MM (local — UTC if Finnhub doesn't specify)
        "country",       # ISO-2 e.g. "US" | "EU" | "CN"
        "event",         # human label e.g. "CPI MoM"
        "impact",        # "low" | "medium" | "high"
        "forecast",
        "actual",
        "previous",
        "unit",          # "%" | "K" | "B" etc.
        "updated_at",
    ]

    date: str
    time: str
    country: str
    event: str
    impact: str
    forecast: str
    actual: str
    previous: str
    unit: str
    updated_at: str

    def to_row(self, audit: bool = True) -> List[str]:
        return [
            self.date, self.time, self.country, self.event, self.impact,
            self.forecast, self.actual, self.previous, self.unit,
            self.updated_at,
        ]


@dataclass
class AnalystConsensusRow:
    """
    Wall Street consensus per ticker — count of analysts in each rating
    bucket. Refreshed weekly by `scripts/finnhub_analyst.py` from
    Finnhub `stock/recommendation`.

    Free tier covers recommendation distribution but NOT price targets
    (premium only). The brain still gets the most useful signal: how
    many sell-side analysts are positive vs neutral vs negative.

    Brain reads this in:
      - WSR Full: "analyst consensus shifts since last WSR" — flag
        upgrades (more buys) or downgrades (more sells)
      - Decision card thesis: "Wall St: 42 buy / 4 hold / 1 sell" anchor
        for share recs (gives the user a quick "vs consensus" reference)

    PWA shows an analyst chip on Decision cards.

    UPSERT key: ticker — one row per ticker (latest period only).
    """
    TAB_NAME = "analyst_consensus"
    HEADERS = [
        "ticker",
        "period",            # YYYY-MM-DD (Finnhub publishes monthly)
        "strong_buy_count",
        "buy_count",
        "hold_count",
        "sell_count",
        "strong_sell_count",
        "total_count",
        "consensus_score",   # weighted avg in [-2..+2]
        "consensus_label",   # "STRONG_BUY" | "BUY" | "HOLD" | "SELL" | "STRONG_SELL"
        "updated_at",
    ]

    ticker: str
    period: str
    strong_buy_count: int
    buy_count: int
    hold_count: int
    sell_count: int
    strong_sell_count: int
    total_count: int
    consensus_score: float
    consensus_label: str
    updated_at: str

    def to_row(self, audit: bool = True) -> List[str]:
        return [
            self.ticker, self.period,
            str(self.strong_buy_count), str(self.buy_count),
            str(self.hold_count), str(self.sell_count),
            str(self.strong_sell_count), str(self.total_count),
            _num(self.consensus_score, 2),
            self.consensus_label, self.updated_at,
        ]


@dataclass
class NewsSentimentRow:
    """
    Per-ticker company news + heuristic sentiment. Refreshed 4×/day by
    `scripts/finnhub_news_insider.py` from Finnhub `company-news`.

    Free tier doesn't expose Finnhub's premium ML sentiment, so we run a
    cheap keyword-based heuristic (-1.0 to +1.0) at write time. The
    brain (Opus) does the actual semantic analysis when it reads the
    rows — heuristic just prioritises what to surface.

    Brain reads this in:
      - Daily Brief: per-position sentiment alerts (sentiment < -0.5 in
        last 24h → flag in the brief)
      - WSR Lite: "news sentiment changes since Monday WSR"
      - WSR Full: per-position news context for synthesis

    PWA shows a sentiment dot on Decision cards (green/amber/red) when
    fresh news exists for the ticker.

    UPSERT key: (id) — Finnhub article ID is unique. Re-pulls dedupe.
    """
    TAB_NAME = "news_sentiment"
    HEADERS = [
        "id",                # Finnhub article id (UPSERT key)
        "datetime",          # SGT iso "YYYY-MM-DDTHHMMSS" (article timestamp)
        "ticker",
        "headline",
        "summary",
        "source",            # publisher name e.g. "Yahoo" / "Reuters"
        "url",
        "sentiment_score",   # -1.0 (very neg) → +1.0 (very pos), heuristic
        "sentiment_label",   # "negative" | "neutral" | "positive"
        "category",          # "company" | "general" | "earnings" | etc.
        "updated_at",
    ]

    id: str
    datetime: str
    ticker: str
    headline: str
    summary: str
    source: str
    url: str
    sentiment_score: float
    sentiment_label: str
    category: str
    updated_at: str

    def to_row(self, audit: bool = True) -> List[str]:
        # Truncate summary to 1KB to stay below Sheets cell limit and
        # keep the row scannable.
        summary = self.summary or ""
        if len(summary) > 1000:
            summary = summary[:1000] + "...[truncated]"
        return [
            self.id, self.datetime, self.ticker, self.headline, summary,
            self.source, self.url,
            _num(self.sentiment_score, 3),
            self.sentiment_label, self.category, self.updated_at,
        ]


@dataclass
class InsiderTransactionRow:
    """
    Insider buy/sell filings from SEC Form 4 (via Finnhub). Refreshed
    daily by `scripts/finnhub_news_insider.py`.

    Brain reads this in:
      - Daily Brief: "unusual insider activity" flag if any portfolio
        ticker has a >$1M buy or >$5M sell in last 7 days
      - WSR Full: "insider net flow last 7d" per portfolio + watchlist
      - Aggressive watch: heavy insider buying on a watchlist ticker
        bumps it into the BUY_DIP queue with elevated conviction

    UPSERT key: (id) — Finnhub assigns SEC filing id, unique per row.

    Transaction codes:
      P = open market purchase (BUY signal)
      S = open market sale     (SELL signal)
      A = grant/award
      M = exercise of options  (typically followed by S — see filings)
      G = bona fide gift
      D = sale to issuer
    """
    TAB_NAME = "insider_transactions"
    HEADERS = [
        "id",                  # SEC filing id (UPSERT key)
        "transaction_date",
        "filing_date",
        "ticker",
        "name",                # insider name
        "shares",              # signed: positive=acquired, negative=disposed
        "transaction_code",    # P / S / A / M / G / D
        "side",                # "buy" | "sell" | "grant" | "exercise" | "other"
        "transaction_price",   # per-share price (0 for grants)
        "value_usd",           # |shares × price| approximate $ value
        "is_derivative",       # TRUE/FALSE
        "shares_after",        # holdings post-transaction
        "updated_at",
    ]

    id: str
    transaction_date: str
    filing_date: str
    ticker: str
    name: str
    shares: float
    transaction_code: str
    side: str
    transaction_price: float
    value_usd: float
    is_derivative: bool
    shares_after: float
    updated_at: str

    def to_row(self, audit: bool = True) -> List[str]:
        return [
            self.id, self.transaction_date, self.filing_date, self.ticker,
            self.name, _num(self.shares, 0),
            self.transaction_code, self.side,
            _num(self.transaction_price, 4), _num(self.value_usd, 0),
            "TRUE" if self.is_derivative else "FALSE",
            _num(self.shares_after, 0),
            self.updated_at,
        ]


@dataclass
class MacroAlertStateRow:
    """
    Per-event ledger for macro Telegram pings — used by `scripts/trigger_alerts.py`
    to ensure EACH event fires exactly once, regardless of how many cron
    runs straddle its window.

    Two event types share this sheet:
      - blackout : a high-impact US event entering the ±15min window.
                   event_key = ISO-time of the event itself (deterministic).
      - hot_news : a Finnhub general-news headline matching HOT_KEYWORDS.
                   event_key = Finnhub news ID (deterministic).

    Older-than-7-days rows are pruned on every write so the sheet
    doesn't grow unbounded.
    """
    TAB_NAME = "macro_alerts_state"
    HEADERS = [
        "event_key",       # UPSERT key — "blackout:NFP-2026-05-08T13:30Z" / "news:12345"
        "event_type",      # "blackout" | "hot_news"
        "event_summary",   # human-readable for debugging
        "event_time",      # SGT iso of the event itself (or news datetime)
        "alerted_at",      # SGT iso when the Telegram fired
        "updated_at",      # SGT iso of the last cron pass that touched this row
    ]

    event_key: str
    event_type: str
    event_summary: str
    event_time: str
    alerted_at: str
    updated_at: str

    def to_row(self, audit: bool = True) -> List[str]:
        return [
            self.event_key, self.event_type, self.event_summary,
            self.event_time, self.alerted_at, self.updated_at,
        ]


@dataclass
class MacroLeanRow:
    """One row/day: the net macro-surprise lean from today's US releases (written
    by trigger_alerts via the macro_playbook). build_daily_plan reads it to tilt
    sizing (hawkish/risk_off → trim growth adds; dovish/risk_on → lean in), and
    the PWA shows it as a regime banner. News as INPUT, never a trade signal."""
    TAB_NAME = "macro_lean"
    HEADERS = ["date", "net_lean", "summary", "updated_at"]

    date: str
    net_lean: str          # hawkish | dovish | risk_on | risk_off | neutral
    summary: str           # e.g. "Core CPI→hawkish · GDP→risk_on"
    updated_at: str = ""

    def to_row(self) -> List[str]:
        return [self.date, self.net_lean, self.summary, self.updated_at]


@dataclass
class LivePriceRow:
    """
    Near-realtime price feed — one upserted row per portfolio ticker.

    Refreshed every 5 minutes by `scripts/tv_price_refresh.py` using
    TradingView's public scanner endpoint (the same data source as
    `tv_signals_run.py`). The PWA Portfolio overlays this onto the
    positions tabs so `mkt_val` / `upl` reflect the current price, not
    the last-grab price (which can be 15+ min stale).

    UPSERT semantics: keyed by `ticker` only. Each refresh replaces the
    row for any returned ticker, otherwise appends. The tab stays tiny
    (~30 rows total — one per active portfolio ticker).

    Why TradingView, not Yahoo?
      - Already used for tv_signals daily (consistency)
      - More reliable than Yahoo (no IP throttling/CORS)
      - Faster: single batched POST returns all tickers
      - Updates near-realtime during US market hours
    """
    TAB_NAME = "live_prices"
    HEADERS = [
        "ticker",          # key (no exchange prefix)
        "exchange",        # "NASDAQ" | "NYSE" | "AMEX" | "SGX"
        "last",            # current price
        "change_pct",      # day-over-day % change
        "volume",          # day's volume
        "updated_at",      # SGT-anchored ISO "YYYY-MM-DDTHHMMSS"
        "source",          # "tv" | "yahoo" (which feed wrote this row)
    ]

    ticker: str
    exchange: str
    last: float
    change_pct: float
    volume: int
    updated_at: str        # SGT iso
    source: str = "tv"

    def to_row(self, audit: bool = True) -> List[str]:
        return [
            self.ticker, self.exchange,
            _num(self.last, 4), _num(self.change_pct, 4),
            str(int(self.volume)) if self.volume else "0",
            self.updated_at,
            self.source,
        ]


def macro_from_ledger(ledger: dict, date: str) -> MacroRow:
    m = ledger.get("macro") or {}
    return MacroRow(
        date=date,
        vix=m.get("vix"),
        dxy=m.get("dxy"),
        us_10y=m.get("us_10y"),
        spx=m.get("spx"),
        usd_sgd=m.get("usd_sgd"),
        spx_above_200sma=m.get("spx_above_200sma"),  # absent in ledgers → '' cell
    )
