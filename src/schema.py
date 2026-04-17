"""
Sheet tab schemas — dataclasses mirror the 7 tabs one-for-one.

Each class exposes:
  - TAB_NAME    : the literal Google Sheet tab name (must match)
  - HEADERS     : ordered list of column headers (row 1 in the tab)
  - to_row()    : returns a list[str] in HEADERS order for append_row()

If you change a schema here, update the sheet tab header row to match.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List


def _num(x, ndp: int = 2) -> str:
    """Format a number as fixed-decimal string, '' for None."""
    if x is None:
        return ""
    try:
        return f"{float(x):.{ndp}f}"
    except (TypeError, ValueError):
        return str(x)


def _ts_suffix(date: str) -> str:
    """Append HHMMSS to a YYYY-MM-DD date for audit-trail uniqueness on re-run."""
    return f"{date}T{datetime.now().strftime('%H%M%S')}"


@dataclass
class SnapshotCaspar:
    TAB_NAME = "snapshot_caspar"
    HEADERS = ["date", "net_liq_usd", "cash", "upl", "upl_pct"]

    date: str
    net_liq_usd: float
    cash: float
    upl: float
    upl_pct: float

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        return [d, _num(self.net_liq_usd), _num(self.cash), _num(self.upl), _num(self.upl_pct, 4)]


@dataclass
class SnapshotSarah:
    TAB_NAME = "snapshot_sarah"
    HEADERS = ["date", "net_liq_sgd", "cash_sgd", "upl_sgd", "upl_pct"]

    date: str
    net_liq_sgd: float
    cash_sgd: float
    upl_sgd: float
    upl_pct: float

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        return [d, _num(self.net_liq_sgd), _num(self.cash_sgd), _num(self.upl_sgd), _num(self.upl_pct, 4)]


@dataclass
class PositionRow:
    """Used for both positions_caspar and positions_sarah tabs."""
    HEADERS = ["date", "ticker", "qty", "avg_cost", "last", "mkt_val", "upl", "weight"]

    date: str
    ticker: str
    qty: float
    avg_cost: float
    last: float
    mkt_val: float
    upl: float
    weight: float

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        return [
            d, self.ticker,
            _num(self.qty, 4), _num(self.avg_cost, 4), _num(self.last, 4),
            _num(self.mkt_val), _num(self.upl), _num(self.weight, 4),
        ]


@dataclass
class DecisionRow:
    TAB_NAME = "decision_queue"
    HEADERS = ["date", "account", "ticker", "bucket", "thesis_1liner", "conv", "entry", "target", "status"]

    date: str
    account: str          # "caspar" | "sarah"
    ticker: str
    bucket: str           # e.g. "BUY NOW" | "WATCH" | "CSP" | "PMCC" | "WHEEL"
    thesis_1liner: str
    conv: float           # 0.0 – 1.0
    entry: float
    target: float
    status: str           # "pending" | "filled" | "killed"

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        return [
            d, self.account, self.ticker, self.bucket, self.thesis_1liner,
            _num(self.conv, 2), _num(self.entry, 4), _num(self.target, 4), self.status,
        ]


@dataclass
class DailyBriefRow:
    TAB_NAME = "daily_brief_latest"
    HEADERS = [
        "date", "bullet_1", "bullet_2", "bullet_3", "verdict", "sentiment",
        "headline", "overnight", "premarket", "catalysts", "commodities",
        "posture", "watch", "raw_md",
    ]

    date: str
    bullet_1: str = ""
    bullet_2: str = ""
    bullet_3: str = ""
    verdict: str = ""
    sentiment: str = ""
    headline: str = ""      # opening line of the brief (big summary)
    overnight: str = ""     # e.g. "S&P 6,886 (+1.02%) | Nasdaq +1.23% | VIX 18.59 -2.77%"
    premarket: str = ""     # e.g. "ES +0.22% | Brent $99 | Gold $4,748"
    catalysts: str = ""     # pipe-separated, e.g. "20:30 PPI|Fed speakers|Q1 earnings"
    commodities: str = ""   # pipe-separated, e.g. "WTI $93 | Gold $4800 | USD/SGD 1.2733"
    posture: str = ""       # free text, e.g. "POSTURE CHANGE: YES. ..."
    watch: str = ""         # pipe-separated watchlist items
    raw_md: str = ""        # full original brief text for in-app detail view

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        return [
            d, self.bullet_1, self.bullet_2, self.bullet_3, self.verdict, self.sentiment,
            self.headline, self.overnight, self.premarket, self.catalysts, self.commodities,
            self.posture, self.watch, self.raw_md,
        ]


@dataclass
class WsrArchiveRow:
    TAB_NAME = "wsr_archive"
    HEADERS = ["date", "title", "drive_file_id", "drive_url"]

    date: str
    title: str
    drive_file_id: str
    drive_url: str = ""

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        url = self.drive_url or f"https://drive.google.com/file/d/{self.drive_file_id}/view"
        return [d, self.title, self.drive_file_id, url]


@dataclass
class MacroRow:
    TAB_NAME = "macro"
    HEADERS = ["date", "vix", "dxy", "us_10y", "spx", "usd_sgd"]

    date: str
    vix: float | None = None
    dxy: float | None = None
    us_10y: float | None = None
    spx: float | None = None
    usd_sgd: float | None = None

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        return [d, _num(self.vix, 2), _num(self.dxy, 3), _num(self.us_10y, 3),
                _num(self.spx, 2), _num(self.usd_sgd, 4)]


@dataclass
class OptionRow:
    """Options positions with moneyness, assignment confidence, and wheel context."""
    TAB_NAME = "options"
    HEADERS = [
        "date", "account", "ticker", "right", "strike", "expiry",
        "qty", "credit", "last", "mkt_val", "upl",
        "underlying_last", "moneyness", "dte",
        "assignment_risk", "wheel_leg", "adj_cost_basis",
        "momentum_5d", "trend_risk",
        "confidence_pct", "confidence_reasoning",
        "volatility_annual", "rsi_14", "sma_20", "sma_50",
    ]

    date: str
    account: str            # "caspar" | "sarah"
    ticker: str             # underlying symbol
    right: str              # "C" (call) | "P" (put)
    strike: float
    expiry: str             # "YYYYMMDD"
    qty: float              # negative = short
    credit: float           # premium received per share (avg_cost_credit / multiplier)
    last: float             # current option price per share
    mkt_val: float
    upl: float
    underlying_last: float  # current stock price
    moneyness: str          # "ITM" | "ATM" | "OTM"
    dte: int                # days to expiry
    assignment_risk: str    # "LOW" | "MED" | "HIGH"
    wheel_leg: str          # "CC" | "CSP" | "LONG_CALL" | "LONG_PUT"
    adj_cost_basis: float   # stock avg_cost - accumulated premiums
    momentum_5d: float = 0.0      # 5-day price rate of change %
    trend_risk: str = "?"         # "SAFE" | "DRIFTING" | "CONVERGING" | "BREACHING"
    confidence_pct: int = 0       # 0-100 probability of assignment
    confidence_reasoning: str = ""  # multi-factor explanation
    volatility_annual: float = 0.0  # annualized σ from 30-60d
    rsi_14: float = 50.0          # 14-day RSI
    sma_20: float = 0.0           # 20-day SMA
    sma_50: float = 0.0           # 50-day SMA

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        return [
            d, self.account, self.ticker, self.right,
            _num(self.strike, 2), self.expiry,
            _num(self.qty, 0), _num(self.credit, 4), _num(self.last, 4),
            _num(self.mkt_val, 2), _num(self.upl, 2),
            _num(self.underlying_last, 4), self.moneyness, str(self.dte),
            self.assignment_risk, self.wheel_leg, _num(self.adj_cost_basis, 4),
            _num(self.momentum_5d, 2), self.trend_risk,
            str(self.confidence_pct), self.confidence_reasoning,
            _num(self.volatility_annual, 4), _num(self.rsi_14, 1),
            _num(self.sma_20, 2), _num(self.sma_50, 2),
        ]


@dataclass
class TechnicalScoreRow:
    """Daily per-ticker technical indicators + strategy scores + entry/exit signal."""
    TAB_NAME = "technical_scores"
    HEADERS = [
        "date", "ticker", "close", "trend",
        "rsi_14", "stoch_k", "stoch_d",
        "macd_hist", "macd_cross",
        "bb_pct_b", "bb_squeeze",
        "wvf", "wvf_bottom",
        "sma_20", "sma_50", "sma_200",
        "support", "resistance",
        "fib_0236", "fib_0382", "fib_050", "fib_0618", "fib_0764",
        "vol_ratio", "vol_spike_type", "candle_pattern",
        "divergence", "momentum_5d", "momentum_20d",
        "volatility_annual", "catalyst_flag", "vol_regime",
        "earnings_date", "earnings_days_away",
        "score_buy", "score_csp", "score_cc",
        "score_long_call", "score_long_put",
        "entry_exit_signal", "top_drivers",
    ]

    date: str
    ticker: str
    close: float
    trend: str
    rsi_14: float
    stoch_k: float
    stoch_d: float
    macd_hist: float
    macd_cross: str
    bb_pct_b: float
    bb_squeeze: bool
    wvf: float
    wvf_bottom: bool
    sma_20: float
    sma_50: float
    sma_200: float
    support: float
    resistance: float
    fib_0236: float
    fib_0382: float
    fib_050: float
    fib_0618: float
    fib_0764: float
    vol_ratio: float
    vol_spike_type: str
    candle_pattern: str
    divergence: str
    momentum_5d: float
    momentum_20d: float
    volatility_annual: float
    catalyst_flag: bool
    vol_regime: str
    earnings_date: str
    earnings_days_away: int
    score_buy: float
    score_csp: float
    score_cc: float
    score_long_call: float
    score_long_put: float
    entry_exit_signal: str
    top_drivers: str   # pipe-separated e.g. "CSP: +MACD cross|+Fib position"

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        return [
            d, self.ticker, _num(self.close, 4), self.trend,
            _num(self.rsi_14, 1), _num(self.stoch_k, 1), _num(self.stoch_d, 1),
            _num(self.macd_hist, 4), self.macd_cross,
            _num(self.bb_pct_b, 3), "TRUE" if self.bb_squeeze else "",
            _num(self.wvf, 2), "TRUE" if self.wvf_bottom else "",
            _num(self.sma_20, 4), _num(self.sma_50, 4), _num(self.sma_200, 4),
            _num(self.support, 4), _num(self.resistance, 4),
            _num(self.fib_0236, 4), _num(self.fib_0382, 4), _num(self.fib_050, 4),
            _num(self.fib_0618, 4), _num(self.fib_0764, 4),
            _num(self.vol_ratio, 2), self.vol_spike_type, self.candle_pattern,
            self.divergence, _num(self.momentum_5d, 2), _num(self.momentum_20d, 2),
            _num(self.volatility_annual, 4),
            "TRUE" if self.catalyst_flag else "", self.vol_regime,
            self.earnings_date, str(self.earnings_days_away) if self.earnings_days_away >= 0 else "",
            _num(self.score_buy, 1), _num(self.score_csp, 1), _num(self.score_cc, 1),
            _num(self.score_long_call, 1), _num(self.score_long_put, 1),
            self.entry_exit_signal, self.top_drivers,
        ]


@dataclass
class WheelNextLegRow:
    """Per-open-option next-leg recommendation."""
    TAB_NAME = "wheel_next_leg"
    HEADERS = [
        "date", "account", "ticker", "current_right", "current_strike",
        "current_expiry", "current_dte", "current_status",
        "next_action", "next_strategy", "next_right", "next_strike",
        "next_expiry", "next_dte", "next_delta",
        "next_premium", "next_yield_pct", "next_breakeven",
        "recommendation", "reasoning", "confidence",
    ]

    date: str
    account: str
    ticker: str
    current_right: str
    current_strike: float
    current_expiry: str
    current_dte: int
    current_status: str      # "HOLD" | "EXPIRING_WORTHLESS" | "LIKELY_ASSIGNED" | "ROLL"
    next_action: str         # "LET_EXPIRE" | "ROLL_UP" | "ROLL_OUT" | "CLOSE" | "NEW_LEG"
    next_strategy: str       # "CSP" | "CC" | "SWITCH" | "WAIT"
    next_right: str
    next_strike: float
    next_expiry: str
    next_dte: int
    next_delta: float
    next_premium: float
    next_yield_pct: float
    next_breakeven: float
    recommendation: str      # one-line actionable
    reasoning: str           # explainability
    confidence: int          # 0-100

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        return [
            d, self.account, self.ticker, self.current_right,
            _num(self.current_strike, 2), self.current_expiry, str(self.current_dte),
            self.current_status,
            self.next_action, self.next_strategy, self.next_right,
            _num(self.next_strike, 2) if self.next_strike else "",
            self.next_expiry, str(self.next_dte) if self.next_dte else "",
            _num(self.next_delta, 3) if self.next_delta else "",
            _num(self.next_premium, 2) if self.next_premium else "",
            _num(self.next_yield_pct, 1) if self.next_yield_pct else "",
            _num(self.next_breakeven, 2) if self.next_breakeven else "",
            self.recommendation, self.reasoning, str(self.confidence),
        ]


@dataclass
class ScanResultRow:
    """Daily cross-ticker scan result — a ranked CSP or CC candidate."""
    TAB_NAME = "scan_results"
    HEADERS = [
        "date", "ticker", "strategy", "right", "strike", "expiry", "dte",
        "delta", "premium", "bid", "ask",
        "annual_yield_pct", "cash_required", "breakeven",
        "iv", "iv_rank", "spread_pct",
        "underlying_last", "technical_score", "composite_score",
        "catalyst_flag",
    ]

    date: str
    ticker: str
    strategy: str              # "CSP" | "CC"
    right: str                 # "P" | "C"
    strike: float
    expiry: str                # "YYYYMMDD"
    dte: int
    delta: float
    premium: float
    bid: float
    ask: float
    annual_yield_pct: float
    cash_required: float
    breakeven: float
    iv: float                  # implied vol from chain
    iv_rank: float             # 0-100 proxy
    spread_pct: float          # bid-ask spread as % of mid
    underlying_last: float
    technical_score: float
    composite_score: float     # 0-100
    catalyst_flag: bool

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        return [
            d, self.ticker, self.strategy, self.right,
            _num(self.strike, 2), self.expiry, str(self.dte),
            _num(self.delta, 3), _num(self.premium, 4),
            _num(self.bid, 4), _num(self.ask, 4),
            _num(self.annual_yield_pct, 2), _num(self.cash_required, 2),
            _num(self.breakeven, 2),
            _num(self.iv, 4), _num(self.iv_rank, 1), _num(self.spread_pct, 2),
            _num(self.underlying_last, 4),
            _num(self.technical_score, 1), _num(self.composite_score, 1),
            "TRUE" if self.catalyst_flag else "",
        ]


@dataclass
class OptionsDefenseRow:
    """Daily defense alert for an open option position — what to do TODAY."""
    TAB_NAME = "options_defense"
    HEADERS = [
        "date", "account", "ticker", "right", "strike",
        "severity", "title", "description", "action", "delta_info",
    ]

    date: str
    account: str
    ticker: str
    right: str
    strike: float
    severity: str      # CRITICAL | HIGH | MEDIUM | INFO
    title: str
    description: str
    action: str
    delta_info: str

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        return [
            d, self.account, self.ticker, self.right,
            _num(self.strike, 2),
            self.severity, self.title, self.description,
            self.action, self.delta_info,
        ]


@dataclass
class ExitPlanRow:
    """Daily exit plan for each open position (stock or option)."""
    TAB_NAME = "exit_plans"
    HEADERS = [
        "date", "account", "ticker", "position_type",
        "category", "is_blue_chip",
        "entry", "current", "qty", "upl_pct",
        "stop_loss", "stop_key", "target_1", "target_2",
        "time_stop_days", "days_held",
        "profit_capture_pct", "target_close_at",
        "status", "recommendation", "reasoning",
    ]

    date: str
    account: str
    ticker: str
    position_type: str        # "STOCK" | "OPTION_CSP" | "OPTION_CC" | "OPTION_OTHER"
    category: str             # "blue_chip" | "etf_broad" | "etf_commodity" | "etf_leveraged" | "speculative"
    is_blue_chip: bool
    entry: float
    current: float
    qty: float
    upl_pct: float
    stop_loss: float
    stop_key: str             # Which rule dominated (pct/support/fib/atr/sma_200)
    target_1: float
    target_2: float
    time_stop_days: int       # 0 if none
    days_held: int            # 0 if unknown
    profit_capture_pct: float # For options; 0 for stocks
    target_close_at: float    # Option target close price; 0 for stocks
    status: str               # HEALTHY/WARNING/STOP_TRIGGERED/T1_HIT/T2_HIT/TIME_STOP/ROLL_OR_ASSIGN/PROFIT_TARGET_HIT/LET_EXPIRE/BREACH_WARNING/CATALYST_WARNING
    recommendation: str
    reasoning: str

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        return [
            d, self.account, self.ticker, self.position_type,
            self.category, "TRUE" if self.is_blue_chip else "",
            _num(self.entry, 4), _num(self.current, 4),
            _num(self.qty, 2), _num(self.upl_pct, 4),
            _num(self.stop_loss, 4), self.stop_key,
            _num(self.target_1, 4), _num(self.target_2, 4),
            str(self.time_stop_days), str(self.days_held),
            _num(self.profit_capture_pct, 1),
            _num(self.target_close_at, 4),
            self.status, self.recommendation, self.reasoning,
        ]


@dataclass
class OptionRecommendationRow:
    """Actionable option strategy recommendations (from ad-hoc scans or analysis)."""
    TAB_NAME = "option_recommendations"
    HEADERS = [
        "date", "source", "account", "ticker", "strategy", "right",
        "strike", "expiry", "premium_per_share", "delta",
        "annual_yield_pct", "breakeven", "cash_required",
        "iv_rank", "thesis_confidence", "thesis", "status",
    ]

    date: str                # YYYY-MM-DD — when the recommendation was generated
    source: str              # filename or source identifier
    account: str             # "caspar" | "sarah"
    ticker: str
    strategy: str            # "CSP" | "CC" | "PMCC" | "IRON_CONDOR" | etc
    right: str               # "C" | "P"
    strike: float
    expiry: str              # "YYYYMMDD" or approximate like "May24"
    premium_per_share: float
    delta: float
    annual_yield_pct: float
    breakeven: float
    cash_required: float
    iv_rank: float
    thesis_confidence: float  # 0.0 - 1.0 from the analyst
    thesis: str              # free text judgement
    status: str = "proposed"  # "proposed" | "executed" | "skipped" | "expired"

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        return [
            d, self.source, self.account, self.ticker, self.strategy, self.right,
            _num(self.strike, 2), self.expiry,
            _num(self.premium_per_share, 4), _num(self.delta, 4),
            _num(self.annual_yield_pct, 2), _num(self.breakeven, 2),
            _num(self.cash_required, 2), _num(self.iv_rank, 0),
            _num(self.thesis_confidence, 2), self.thesis, self.status,
        ]


@dataclass
class TradeRow:
    """Individual trade/execution from IBKR."""
    TAB_NAME = "trades"
    HEADERS = [
        "date", "time", "account", "symbol", "sec_type",
        "right", "strike", "expiry",
        "side", "qty", "price", "commission", "realized_pnl",
    ]

    date: str
    time: str               # ISO timestamp
    account: str
    symbol: str
    sec_type: str            # "STK" | "OPT"
    right: str               # "C" | "P" | "" for stocks
    strike: float            # 0 for stocks
    expiry: str              # "" for stocks
    side: str                # "BOT" | "SLD"
    qty: float
    price: float
    commission: float
    realized_pnl: float

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        return [
            d, self.time, self.account, self.symbol, self.sec_type,
            self.right, _num(self.strike, 2) if self.strike else "",
            self.expiry, self.side,
            _num(self.qty, 0), _num(self.price, 4),
            _num(self.commission, 2), _num(self.realized_pnl, 2),
        ]


# ---------- Factory helpers to build rows from pipeline JSON ----------

def snapshot_caspar_from_ledger(ledger: dict, date: str) -> SnapshotCaspar:
    """Build SnapshotCaspar from WSR analysis_ledger.json."""
    p = ledger.get("portfolio", {})
    net_liq = float(p.get("net_liq", 0.0))
    cash = float(p.get("cash", 0.0))
    # Aggregate UPL across positions
    positions = p.get("positions") or []
    upl = sum(float(pos.get("upl", 0.0)) for pos in positions)
    upl_pct = (upl / net_liq) if net_liq else 0.0
    return SnapshotCaspar(
        date=date, net_liq_usd=net_liq, cash=cash, upl=upl, upl_pct=upl_pct,
    )


def positions_caspar_from_ledger(ledger: dict, date: str) -> List[PositionRow]:
    out = []
    for pos in (ledger.get("portfolio", {}).get("positions") or []):
        out.append(PositionRow(
            date=date,
            ticker=str(pos.get("ticker", "")),
            qty=float(pos.get("qty", 0.0)),
            avg_cost=float(pos.get("cost_basis", pos.get("avg_cost", 0.0))),
            last=float(pos.get("last", 0.0)),
            mkt_val=float(pos.get("mkt_val", 0.0)),
            upl=float(pos.get("upl", 0.0)),
            weight=float(pos.get("weight", 0.0)),
        ))
    return out


def snapshot_sarah_from_ledger(ledger: dict, date: str) -> SnapshotSarah | None:
    """Only present if WSR v0.5+ emits ledger.sarah_portfolio. Returns None if absent."""
    sp = ledger.get("sarah_portfolio")
    if not sp:
        return None
    net_liq = float(sp.get("net_liq", 0.0))
    cash = float(sp.get("cash", 0.0))
    positions = sp.get("positions") or []
    upl = sum(float(pos.get("upl", 0.0)) for pos in positions)
    upl_pct = (upl / net_liq) if net_liq else 0.0
    return SnapshotSarah(
        date=date, net_liq_sgd=net_liq, cash_sgd=cash, upl_sgd=upl, upl_pct=upl_pct,
    )


def positions_sarah_from_ledger(ledger: dict, date: str) -> List[PositionRow]:
    out = []
    sp = ledger.get("sarah_portfolio") or {}
    for pos in (sp.get("positions") or []):
        out.append(PositionRow(
            date=date,
            ticker=str(pos.get("ticker", "")),
            qty=float(pos.get("qty", 0.0)),
            avg_cost=float(pos.get("cost_basis", pos.get("avg_cost", 0.0))),
            last=float(pos.get("last", 0.0)),
            mkt_val=float(pos.get("mkt_val", 0.0)),
            upl=float(pos.get("upl", 0.0)),
            weight=float(pos.get("weight", 0.0)),
        ))
    return out


def macro_from_ledger(ledger: dict, date: str) -> MacroRow:
    m = ledger.get("macro") or {}
    return MacroRow(
        date=date,
        vix=m.get("vix"),
        dxy=m.get("dxy"),
        us_10y=m.get("us_10y"),
        spx=m.get("spx"),
        usd_sgd=m.get("usd_sgd"),
    )


def daily_from_sidecar(sidecar: dict) -> DailyBriefRow:
    bullets = sidecar.get("bullets") or ["", "", ""]
    bullets = (bullets + ["", "", ""])[:3]
    # Optional rich sections — join lists with "|" for storage in a single sheet cell
    def _join(v):
        if isinstance(v, list):
            return " | ".join(str(x) for x in v)
        return str(v or "")
    return DailyBriefRow(
        date=str(sidecar.get("date", "")),
        bullet_1=bullets[0],
        bullet_2=bullets[1],
        bullet_3=bullets[2],
        verdict=str(sidecar.get("verdict", "")),
        sentiment=str(sidecar.get("sentiment", "")),
        headline=str(sidecar.get("headline", "")),
        overnight=_join(sidecar.get("overnight")),
        premarket=_join(sidecar.get("premarket")),
        catalysts=_join(sidecar.get("catalysts")),
        commodities=_join(sidecar.get("commodities")),
        posture=str(sidecar.get("posture", "")),
        watch=_join(sidecar.get("watch")),
        raw_md=str(sidecar.get("raw_md", "")),
    )


# ---------- Factory helpers to build rows from IBKR grab JSON ----------

def snapshot_caspar_from_grab(grab: dict) -> SnapshotCaspar:
    """Build SnapshotCaspar from PortfolioGrab JSON (accounts.caspar)."""
    date = str(grab.get("grab_date", ""))
    c = grab.get("accounts", {}).get("caspar", {})
    s = c.get("summary", {})
    net_liq = float(s.get("net_liquidation", 0.0))
    cash = float(s.get("total_cash", 0.0))
    upl = float(s.get("unrealized_pnl", 0.0))
    upl_pct = (upl / net_liq) if net_liq else 0.0
    return SnapshotCaspar(date=date, net_liq_usd=net_liq, cash=cash, upl=upl, upl_pct=upl_pct)


def snapshot_sarah_from_grab(grab: dict) -> SnapshotSarah:
    """Build SnapshotSarah from PortfolioGrab JSON (accounts.sarah)."""
    date = str(grab.get("grab_date", ""))
    sa = grab.get("accounts", {}).get("sarah", {})
    s = sa.get("summary", {})
    net_liq = float(s.get("net_liquidation_sgd", 0.0))
    cash = float(s.get("total_cash_sgd", 0.0))
    upl = float(s.get("unrealized_pnl_mixed", 0.0))
    upl_pct = (upl / net_liq) if net_liq else 0.0
    return SnapshotSarah(date=date, net_liq_sgd=net_liq, cash_sgd=cash, upl_sgd=upl, upl_pct=upl_pct)


def positions_caspar_from_grab(grab: dict) -> List[PositionRow]:
    """Build Caspar position rows from grab JSON. Stocks only (sec_type=STK)."""
    date = str(grab.get("grab_date", ""))
    c = grab.get("accounts", {}).get("caspar", {})
    net_liq = float(c.get("summary", {}).get("net_liquidation", 0.0))
    out = []
    for pos in (c.get("positions") or []):
        if pos.get("sec_type") != "STK":
            continue
        mkt_val = float(pos.get("mkt_val", 0.0))
        out.append(PositionRow(
            date=date,
            ticker=str(pos.get("symbol", "")),
            qty=float(pos.get("qty", 0.0)),
            avg_cost=float(pos.get("avg_cost", 0.0)),
            last=float(pos.get("last", 0.0)),
            mkt_val=mkt_val,
            upl=float(pos.get("upl", 0.0)),
            weight=mkt_val / net_liq if net_liq else 0.0,
        ))
    return out


def positions_sarah_from_grab(grab: dict) -> List[PositionRow]:
    """Build Sarah position rows from grab JSON. Stocks only (sec_type=STK), options skipped."""
    date = str(grab.get("grab_date", ""))
    sa = grab.get("accounts", {}).get("sarah", {})
    net_liq = float(sa.get("summary", {}).get("net_liquidation_sgd", 0.0))
    out = []
    for pos in (sa.get("positions") or []):
        if pos.get("sec_type") != "STK":
            continue
        mkt_val = float(pos.get("mkt_val", 0.0))
        out.append(PositionRow(
            date=date,
            ticker=str(pos.get("symbol", "")),
            qty=float(pos.get("qty", 0.0)),
            avg_cost=float(pos.get("avg_cost", 0.0)),
            last=float(pos.get("last", 0.0)),
            mkt_val=mkt_val,
            upl=float(pos.get("upl", 0.0)),
            weight=mkt_val / net_liq if net_liq else 0.0,
        ))
    return out


def decisions_from_ledger(ledger: dict, date: str) -> List[DecisionRow]:
    """
    WSR ledger may carry 'decisions' directly OR we parse from md.
    Prefer ledger.decisions if present (cleaner contract).
    """
    out = []
    for d in (ledger.get("decisions") or []):
        out.append(DecisionRow(
            date=date,
            account=str(d.get("account", "caspar")),
            ticker=str(d.get("ticker", "")),
            bucket=str(d.get("bucket", "")),
            thesis_1liner=str(d.get("thesis_1liner", d.get("thesis", "")))[:500],
            conv=float(d.get("conv", 0.0)),
            entry=float(d.get("entry", 0.0)),
            target=float(d.get("target", 0.0)),
            status=str(d.get("status", "pending")),
        ))
    return out
