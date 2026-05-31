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
from datetime import datetime, timezone, timedelta
from typing import List


# All sheet audit timestamps are SGT-anchored so Mac-written rows
# (datetime.now() = local SGT) and cloud-written rows (GH Actions UTC)
# sort lexicographically into a single chronological order. Without this,
# UTC-13:54 cloud writes appear "before" SGT-21:53 Mac writes in string
# sort, even though they happened ~minutes apart in real time.
SGT = timezone(timedelta(hours=8), name="SGT")


def now_sgt_iso() -> str:
    """Current SGT instant as 'YYYY-MM-DDTHHMMSS' for sheet audit suffixes."""
    return datetime.now(SGT).strftime("%Y-%m-%dT%H%M%S")


def now_sgt_date() -> str:
    """Current SGT calendar date as 'YYYY-MM-DD'."""
    return datetime.now(SGT).strftime("%Y-%m-%d")


def _num(x, ndp: int = 2) -> str:
    """Format a number as fixed-decimal string, '' for None."""
    if x is None:
        return ""
    try:
        return f"{float(x):.{ndp}f}"
    except (TypeError, ValueError):
        return str(x)


def _ts_suffix(date: str) -> str:
    """Append HHMMSS (SGT) to a YYYY-MM-DD date for audit-trail uniqueness."""
    return f"{date}T{datetime.now(SGT).strftime('%H%M%S')}"


@dataclass
class SnapshotCaspar:
    TAB_NAME = "snapshot_caspar"
    HEADERS = ["date", "net_liq_usd", "cash", "upl", "upl_pct", "excess_liq"]

    date: str
    net_liq_usd: float
    cash: float
    upl: float
    upl_pct: float
    excess_liq: float = 0.0    # IBKR excess liquidity — margin headroom for sizing

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        return [d, _num(self.net_liq_usd), _num(self.cash), _num(self.upl),
                _num(self.upl_pct, 4), _num(self.excess_liq)]


@dataclass
class SnapshotSarah:
    TAB_NAME = "snapshot_sarah"
    HEADERS = ["date", "net_liq_sgd", "cash_sgd", "upl_sgd", "upl_pct", "excess_liq_sgd"]

    date: str
    net_liq_sgd: float
    cash_sgd: float
    upl_sgd: float
    upl_pct: float
    excess_liq_sgd: float = 0.0    # IBKR excess liquidity (SGD) — margin headroom

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        return [d, _num(self.net_liq_sgd), _num(self.cash_sgd), _num(self.upl_sgd),
                _num(self.upl_pct, 4), _num(self.excess_liq_sgd)]


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
    HEADERS = [
        "date", "account", "ticker", "bucket", "thesis_1liner", "conv", "entry", "target", "status",
        # Unified options-spec extension (Phase A of decisions-ideas-merge).
        # All fields below are optional — share entries default to "" / 0.
        "strategy",            # "" | "BUY_DIP" | "TRIM" | "CSP" | "CC" | "PMCC" | "LONG_CALL" | "LONG_PUT"
        "right",               # "" | "C" | "P"
        "strike",              # 0 for share entries
        "expiry",              # "" | "YYYYMMDD"
        "premium_per_share",   # 0 for shares
        "delta",               # 0 for shares
        "annual_yield_pct",    # 0 for shares
        "breakeven",           # 0 if not applicable
        "cash_required",       # 0 if not applicable
        "iv_rank",             # 0 if not applicable (0-100 scale)
        "thesis_confidence",   # 0.0 - 1.0 (brain analytic signal, separate from gut-feel `conv`)
        "thesis",              # full multi-sentence brain thesis (separate from thesis_1liner)
        "source",              # "" | "wsr_full" | "wsr_lite" | "manual" | "risk_parity"
        # --- accumulation extension (Phase 5b — Risk Parity tranche plans) ---
        # Both fields appended at END so existing index-based access in
        # push_decisions / risk_parity_recommend (which reads r[9]=strategy,
        # r[11]=strike for upsert keys) is preserved.
        "qty",                 # planned total share/contract count (int as string; 0 if unknown)
        "accumulation_plan",   # pipe-separated tranches: "5sh now | 5sh +30d | 5sh on -5% pullback to $79.20"
        # --- structured gates (Phase 6 — TriggerBadge reliability) ---
        # JSON-encoded array of gate strings, format "<type>:<required>".
        # Replaces brittle accumulation_plan string-parsing in the PWA's
        # evaluateTrigger(). Recognised types: exposure, tv_daily, tv_weekly,
        # earnings_clear (no required value), regime_above:<score>.
        # Empty string = no gates → treat trigger as ungated.
        # Examples:
        #   '["exposure:NEW_ENTRY_ALLOWED", "tv_daily:BUY"]'
        #   '["earnings_clear"]'
        "gates",
    ]

    date: str
    account: str          # "caspar" | "sarah"
    ticker: str
    bucket: str           # e.g. "BUY NOW" | "WATCH" | "CSP" | "PMCC" | "WHEEL"
    thesis_1liner: str
    conv: float           # 1-5 gut-feel conviction (kept distinct from thesis_confidence)
    entry: float
    target: float
    status: str           # "pending" | "watching" | "filled" | "killed" | "expired"
    # --- options-spec extension (all optional, default to "" / 0 for share entries) ---
    strategy: str = ""
    right: str = ""
    strike: float = 0.0
    expiry: str = ""
    premium_per_share: float = 0.0
    delta: float = 0.0
    annual_yield_pct: float = 0.0
    breakeven: float = 0.0
    cash_required: float = 0.0
    iv_rank: float = 0.0
    thesis_confidence: float = 0.0
    thesis: str = ""
    source: str = ""
    # --- accumulation extension (Phase 5b) ---
    qty: int = 0
    accumulation_plan: str = ""
    # --- structured gates (Phase 6) ---
    # JSON-encoded array of gate strings (or empty). The push_decisions
    # script accepts either a pre-encoded string OR a list[str] and
    # normalises to a JSON string before storing.
    gates: str = ""

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        return [
            d, self.account, self.ticker, self.bucket, self.thesis_1liner,
            _num(self.conv, 0), _num(self.entry, 4), _num(self.target, 4), self.status,
            self.strategy, self.right,
            _num(self.strike, 2), self.expiry,
            _num(self.premium_per_share, 4), _num(self.delta, 4),
            _num(self.annual_yield_pct, 2), _num(self.breakeven, 2),
            _num(self.cash_required, 2), _num(self.iv_rank, 0),
            _num(self.thesis_confidence, 2), self.thesis, self.source,
            str(int(self.qty)) if self.qty else "",
            self.accumulation_plan,
            self.gates,
        ]


@dataclass
class DailyBriefRow:
    TAB_NAME = "daily_brief_latest"
    HEADERS = [
        "date", "bullet_1", "bullet_2", "bullet_3", "verdict", "sentiment",
        "headline", "overnight", "premarket", "catalysts", "commodities",
        "posture", "watch", "raw_md",
        "earnings_today", "macro_today", "negative_news", "insider_alert",
        "gov_confluence",
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
    earnings_today: str = ""   # pipe-separated, e.g. "NVDA AMC est $1.79|WIX BMO est $1.26"
    macro_today: str = ""      # pipe-separated, e.g. "13:30 US CPI MoM est 0.3%|Fed Cook 09:45 ET"
    negative_news: str = ""    # pipe-separated, e.g. "BYND -0.7 'Restructuring talks fail'"
    insider_alert: str = ""    # pipe-separated, e.g. "NVDA Huang sold 50k @ $213 = $10.6M"
    gov_confluence: str = ""   # pipe-separated, e.g. "AVAV score 87 Tier-A → BUY_DIP"

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        return [
            d, self.bullet_1, self.bullet_2, self.bullet_3, self.verdict, self.sentiment,
            self.headline, self.overnight, self.premarket, self.catalysts, self.commodities,
            self.posture, self.watch, self.raw_md,
            self.earnings_today, self.macro_today, self.negative_news,
            self.insider_alert, self.gov_confluence,
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
        "catalyst_flag", "notes", "signals_json",
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
    notes: str = ""            # multi-leg detail (IC/PCS/CCS/PMCC legs)
    signals_json: str = ""     # JSON snapshot of the 16 technical signals at scan time
                               # (incl. IV-aware iv_rv_ratio) so signal_feedback can
                               # validate against the EXACT inputs, not a reconstruction

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
            self.notes,
            self.signals_json,
        ]


@dataclass
class WsrSummaryRow:
    """Latest WSR markdown parsed into a structured summary for the Home page."""
    TAB_NAME = "wsr_summary"
    HEADERS = [
        "date", "source", "verdict", "confidence", "regime",
        "macro_read", "action_summary", "options_summary",
        "redteam_summary", "week_events", "raw_md",
    ]

    date: str
    source: str
    verdict: str
    confidence: float
    regime: str
    macro_read: str
    action_summary: str
    options_summary: str
    redteam_summary: str = ""
    week_events: str = ""
    raw_md: str = ""

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        return [
            d, self.source, self.verdict, _num(self.confidence, 2),
            self.regime, self.macro_read, self.action_summary,
            self.options_summary, self.redteam_summary,
            self.week_events, self.raw_md,
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
    status: str               # HEALTHY/WARNING/STOP_TRIGGERED/T1_HIT/T2_HIT/TIME_STOP/ROLL_OR_ASSIGN/STOP_ROLL/PROFIT_TARGET_HIT/LET_EXPIRE/BREACH_WARNING/CATALYST_WARNING
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
class ScreenCandidateRow:
    """
    Weekly fresh-ticker screen output (vcp + canslim). Sunday before WSR Full
    so the WSR brain has fresh names rather than recycling the watchlist.
    """
    TAB_NAME = "screen_candidates"
    HEADERS = [
        "date", "source", "ticker", "sector", "score",
        "trigger_price", "stop_price", "rationale",
    ]

    date: str
    source: str          # "vcp" | "canslim"
    ticker: str
    sector: str
    score: float         # 0-100 quality
    trigger_price: float # entry trigger (pivot for VCP, blank for CANSLIM)
    stop_price: float    # implied stop
    rationale: str       # why this passed the screen

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        return [
            d, self.source, self.ticker, self.sector,
            _num(self.score, 1),
            _num(self.trigger_price, 4) if self.trigger_price else "",
            _num(self.stop_price, 4) if self.stop_price else "",
            self.rationale,
        ]


@dataclass
class TvSignalRow:
    """
    Daily TradingView 26-indicator consensus per (ticker, interval).
    Written by `scripts/tv_signals_run.py`. Two rows per active ticker
    each run — one for `interval=1d`, one for `interval=1W`.

    The brain uses these as a multi-timeframe confluence check on its own
    thesis. See `prompts/cron_wsr_full.md` and `cron_wsr_lite.md` for the
    decision rules (TF divergence flag, RSI extremes, BUY_DIP gating).

    The PWA Decisions tab also surfaces a small TV consensus chip per
    DecisionCard so the user can see the external sanity-check at a
    glance.

    Source data: TradingView's public scanner endpoint
    (`https://scanner.tradingview.com/america/scan`). No API key required.
    The endpoint returns Recommend.All / Recommend.MA / Recommend.Other
    in [-1, +1] which we map to STRONG_BUY/BUY/NEUTRAL/SELL/STRONG_SELL
    using the same thresholds as the `tradingview-ta` library:
        score >  +0.5 -> STRONG_BUY
        score >  +0.1 -> BUY
        score >= -0.1 -> NEUTRAL
        score >= -0.5 -> SELL
        score <  -0.5 -> STRONG_SELL

    Buy/sell/neutral counts: the scanner endpoint does NOT break out the
    individual classifications across the 26 indicators (12 MAs + 14
    oscillators) — that requires a per-symbol call which is rate-limited.
    We approximate from the MA + Other scores: each MA contributes BUY or
    SELL only (no neutrals), 15 MAs total (1 of the indicators is
    Pivot.M.Classic which doesn't classify, and Ichimoku/VWMA/HullMA9 use
    Rec.* values), so MA buy_count = round(15 * (1 + ma_score) / 2);
    each oscillator can be BUY/SELL/NEUTRAL, 11 oscillators, and we
    approximate similarly. Approximations are within ~1-2 of TV's UI
    display and good enough for confluence checks.

    `recommendation` is the LABEL on the All score; the score itself is
    written too (in `score_all`) for finer-grained brain logic.
    """
    TAB_NAME = "tv_signals"
    HEADERS = [
        "date", "ticker", "exchange",          # identity
        "interval",                            # "1d" | "1W" | "1M"
        "recommendation",                      # STRONG_BUY | BUY | NEUTRAL | SELL | STRONG_SELL | ERROR: ...
        "buy_count", "sell_count", "neutral_count",
        "score_all", "score_ma", "score_other",
        "close", "volume", "change_pct",
        "rsi", "macd", "macd_signal",
        "ema20", "ema50", "ema200",
        "adx", "bb_upper", "bb_lower",
        "stoch_k", "stoch_d", "cci20",
    ]

    date: str
    ticker: str
    exchange: str           # "NASDAQ" | "NYSE" | "AMEX" | "" (errored)
    interval: str           # "1d" | "1W" | "1M"
    recommendation: str     # see class docstring; or "ERROR: <reason>"
    buy_count: int          # approximated, see class docstring
    sell_count: int
    neutral_count: int
    score_all: float        # -1.0 to +1.0 (raw Recommend.All)
    score_ma: float
    score_other: float
    close: float
    volume: float
    change_pct: float
    rsi: float
    macd: float
    macd_signal: float
    ema20: float
    ema50: float
    ema200: float
    adx: float
    bb_upper: float
    bb_lower: float
    stoch_k: float
    stoch_d: float
    cci20: float

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        return [
            d, self.ticker, self.exchange, self.interval,
            self.recommendation,
            str(self.buy_count), str(self.sell_count), str(self.neutral_count),
            _num(self.score_all, 4), _num(self.score_ma, 4), _num(self.score_other, 4),
            _num(self.close, 4), _num(self.volume, 0), _num(self.change_pct, 2),
            _num(self.rsi, 1), _num(self.macd, 4), _num(self.macd_signal, 4),
            _num(self.ema20, 4), _num(self.ema50, 4), _num(self.ema200, 4),
            _num(self.adx, 2), _num(self.bb_upper, 4), _num(self.bb_lower, 4),
            _num(self.stoch_k, 1), _num(self.stoch_d, 1), _num(self.cci20, 2),
        ]


@dataclass
class OptionsYieldCandidateRow:
    """
    Weekly wide-universe options-yield screener output. Sunday between
    screen-candidates (11:00 UTC) and WSR Full (11:37 UTC) so the brain
    has fresh CSP/CC strategy candidates to propose.

    The brain was previously refreshing existing options positions but
    proposing zero NEW CSP/CC entries because nothing surfaced fresh
    high-yield setups. This row supplies the candidate pool — top 20
    ranked by composite (annualised yield + IV rank + delta sweet-spot
    + spread + liquidity) across a wide wheel-target universe.

    See `scripts/options_yield_screener.py` for the generator.
    """
    TAB_NAME = "options_yield_candidates"
    HEADERS = [
        "date", "ticker",                    # identity
        "strategy",                          # "CSP" | "CC"
        "right", "strike", "expiry",         # contract spec
        "dte",                               # days to expiry
        "underlying_last",                   # current spot
        "delta",                             # 0.20-0.30 typical
        "premium",                           # mid (bid+ask)/2
        "annual_yield_pct",                  # premium / strike × 365/dte × 100
        "iv", "iv_rank",                     # implied vol + rank 0-100
        "moneyness",                         # "OTM" typically (we filter for it)
        "spread_pct",                        # bid-ask spread / mid
        "open_interest", "volume",           # liquidity check
        "score",                             # composite 0-100 ranking
        "rationale",                         # 1-line "why this candidate"
    ]

    date: str
    ticker: str
    strategy: str            # "CSP" | "CC"
    right: str               # "P" | "C"
    strike: float
    expiry: str              # "YYYYMMDD"
    dte: int
    underlying_last: float
    delta: float
    premium: float
    annual_yield_pct: float
    iv: float
    iv_rank: float
    moneyness: str           # "OTM" typically
    spread_pct: float        # 0.0-1.0 fractional (bid-ask / mid)
    open_interest: int
    volume: int
    score: float             # 0-100 composite
    rationale: str

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        return [
            d, self.ticker, self.strategy, self.right,
            _num(self.strike, 2), self.expiry, str(self.dte),
            _num(self.underlying_last, 4),
            _num(self.delta, 4), _num(self.premium, 4),
            _num(self.annual_yield_pct, 2),
            _num(self.iv, 4), _num(self.iv_rank, 1),
            self.moneyness, _num(self.spread_pct, 4),
            str(self.open_interest), str(self.volume),
            _num(self.score, 1), self.rationale,
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
class ApiUsageRow:
    """
    Per-workflow Anthropic API usage + cost log. Populated by
    `scripts/api_usage_scrape.py` parsing the result JSON that
    claude-code-action writes at the end of each brain run:

        {"type":"result","subtype":"success","is_error":false,
         "duration_ms":1271673,"num_turns":62,
         "total_cost_usd":5.671771,"permission_denials_count":0}

    UPSERT key: `run_id` (one row per GH Actions run). Re-scrapes are
    idempotent. The Settings panel reads this for MTD spend +
    per-workflow + recent-runs tables.

    NOTE: only Anthropic costs are tracked here. Finnhub/TV/Yahoo are
    free tier. FMP is the user's separate paid subscription (not
    metered per-call by us).
    """
    TAB_NAME = "api_usage"
    HEADERS = [
        "date",            # SGT iso "YYYY-MM-DDTHHMMSS" (run completion time)
        "run_id",          # GH Actions run id (UPSERT key)
        "workflow",        # "daily-brief" | "wsr-full" | "wsr-lite" | "market-scan" | etc.
        "model",           # "claude-opus-4-7" | "claude-sonnet-4-5"
        "status",          # "success" | "failure" | "cancelled"
        "num_turns",
        "duration_ms",
        "total_cost_usd",
        "updated_at",      # SGT iso when this row was scraped
    ]

    date: str
    run_id: str
    workflow: str
    model: str
    status: str
    num_turns: int
    duration_ms: int
    total_cost_usd: float
    updated_at: str

    def to_row(self, audit: bool = True) -> List[str]:
        return [
            self.date, self.run_id, self.workflow, self.model, self.status,
            str(self.num_turns), str(self.duration_ms),
            _num(self.total_cost_usd, 4), self.updated_at,
        ]


@dataclass
class TriggerAlertRow:
    """
    Per-decision trigger-state ledger — used by `scripts/trigger_alerts.py`
    to detect *transitions* into ACT_NOW so we don't fire the same
    Telegram twice within a single trigger window.

    One row per `decision_key` (`<date>|<account>|<ticker>|<strategy>|<strike>`).
    UPSERT semantics: every trigger-alerts cron run rewrites the row's
    `last_state` and `updated_at`; `last_alert_at` only updates when we
    actually send a Telegram (so we can compare to detect re-fires).

    Re-firing rule: an ACT_NOW transition is counted as new only if the
    PREVIOUS row's `last_state` was NOT already act_now. Returning to
    act_now after a brief dip back to "ready" or "close" within the
    same calendar day still counts as the same fire (we suppress).
    """
    TAB_NAME = "trigger_alerts"
    HEADERS = [
        "decision_key",        # UPSERT key
        "ticker",
        "account",
        "strategy",
        "last_state",          # "dormant" | "close" | "ready" | "act_now"
        "last_alert_state",    # state at last Telegram fire
        "last_alert_at",       # SGT iso (only updates when we ACTUALLY send)
        "current_price",
        "entry_price",
        "blocking_gates",      # pipe-separated, for the user's reference
        "updated_at",          # SGT iso (always updates per cron run)
    ]

    decision_key: str
    ticker: str
    account: str
    strategy: str
    last_state: str
    last_alert_state: str = ""
    last_alert_at: str = ""
    current_price: float = 0.0
    entry_price: float = 0.0
    blocking_gates: str = ""
    updated_at: str = ""

    def to_row(self, audit: bool = True) -> List[str]:
        return [
            self.decision_key, self.ticker, self.account, self.strategy,
            self.last_state, self.last_alert_state, self.last_alert_at,
            _num(self.current_price, 4), _num(self.entry_price, 4),
            self.blocking_gates, self.updated_at,
        ]


@dataclass
class TelegramOffsetRow:
    """
    Single-row tracker for Telegram getUpdates offset.

    The portfolio responder cron polls getUpdates every N min; offset is
    the highest update_id we've already processed + 1, so subsequent
    polls skip over already-handled messages. Survives across GH Actions
    runs because GH cron containers are ephemeral.

    Always exactly one data row (key="last") — UPSERT on every run.
    """
    TAB_NAME = "telegram_offset"
    HEADERS = ["key", "last_update_id", "updated_at"]

    key: str
    last_update_id: int
    updated_at: str

    def to_row(self, audit: bool = True) -> List[str]:
        return [self.key, str(self.last_update_id), self.updated_at]


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
    """Build Sarah position rows from grab JSON. Stocks only — options
    flow through options_from_grab() and the unified `options` sheet."""
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


def options_from_grab(grab: dict, account: str) -> List[OptionRow]:
    """
    Build OptionRow rows for one account from grab JSON. Both Caspar and
    Sarah's options live in the unified `options` sheet (the `account`
    column disambiguates).

    IBKR-known fields (qty, credit, last, mkt_val, upl) populated from the
    grab. Cloud-derived fields (underlying_last, moneyness, dte,
    assignment_risk, momentum_5d, trend_risk, sigma, RSI, SMAs) left blank
    — options_refresh_cloud.py fills them within 30 min during US session.
    Mac-tethered fields (wheel_leg, adj_cost_basis, confidence_pct,
    confidence_reasoning) left blank — daily_tracker.py fills them at
    06:00 SGT when it runs nightly.
    """
    date = str(grab.get("grab_date", ""))
    acct = grab.get("accounts", {}).get(account, {})
    out: List[OptionRow] = []
    for opt in (acct.get("options") or []):
        if opt.get("sec_type") != "OPT":
            continue
        try:
            qty = float(opt.get("qty", 0.0))
            avg_cost_credit = float(opt.get("avg_cost_credit", opt.get("avg_cost", 0.0)))
            multiplier = float(opt.get("multiplier", 100))
            credit = avg_cost_credit / multiplier if multiplier else avg_cost_credit / 100
            strike = float(opt.get("strike", 0.0))
        except (ValueError, TypeError):
            continue
        if not opt.get("symbol") or not opt.get("expiry"):
            continue
        out.append(OptionRow(
            date=date,
            account=account,
            ticker=str(opt["symbol"]),
            right=str(opt.get("right", "")).strip().upper(),
            strike=strike,
            expiry=str(opt["expiry"]),
            qty=qty,
            credit=credit,
            last=float(opt.get("last", 0.0)),
            mkt_val=float(opt.get("mkt_val", 0.0)),
            upl=float(opt.get("upl", 0.0)),
            # cloud-derived (options_refresh_cloud.py fills within 30min):
            underlying_last=0.0,
            moneyness="",
            dte=0,
            assignment_risk="",
            # Mac-derived (daily_tracker.py fills at 06:00 SGT):
            wheel_leg="",
            adj_cost_basis=0.0,
            momentum_5d=0.0,
            trend_risk="?",
            confidence_pct=0,
            confidence_reasoning="",
            volatility_annual=0.0,
            rsi_14=50.0,
            sma_20=0.0,
            sma_50=0.0,
        ))
    return out


def decisions_from_ledger(ledger: dict, date: str) -> List[DecisionRow]:
    """
    WSR ledger may carry 'decisions' directly OR we parse from md.
    Prefer ledger.decisions if present (cleaner contract).

    Mirrors the parsing in scripts/push_decisions.py so both write paths
    produce key-consistent rows under the (date, account, ticker, strategy,
    strike) compound upsert key. Legacy ledgers that only carry the original
    9 fields still produce well-formed rows (just with empty strategy / 0
    strike / etc.).
    """
    out = []
    for d in (ledger.get("decisions") or []):
        out.append(DecisionRow(
            date=date,
            account=str(d.get("account", "caspar")),
            ticker=str(d.get("ticker", "")),
            bucket=str(d.get("bucket", "")),
            thesis_1liner=str(d.get("thesis_1liner", d.get("thesis", "")))[:500],
            conv=round(float(d.get("conv", 3) or 3)),
            entry=float(d.get("entry", 0.0)),
            target=float(d.get("target", 0.0)),
            status=str(d.get("status", "pending")),
            # Optional options-spec fields — default "" / 0 for share entries.
            strategy=(str(d.get("strategy", "") or "")).strip().upper(),
            right=(str(d.get("right", "") or "")).strip().upper(),
            strike=float(d.get("strike", 0) or 0),
            expiry=(str(d.get("expiry", "") or "")).strip(),
            premium_per_share=float(d.get("premium_per_share", 0) or 0),
            delta=float(d.get("delta", 0) or 0),
            annual_yield_pct=float(d.get("annual_yield_pct", 0) or 0),
            breakeven=float(d.get("breakeven", 0) or 0),
            cash_required=float(d.get("cash_required", 0) or 0),
            iv_rank=float(d.get("iv_rank", 0) or 0),
            thesis_confidence=float(d.get("thesis_confidence", 0) or 0),
            thesis=(str(d.get("thesis", "") or "")).strip(),
            source=(str(d.get("source", "") or "")).strip(),
            qty=int(d.get("qty", 0) or 0),
            accumulation_plan=(str(d.get("accumulation_plan", "") or "")).strip(),
        ))
    return out


# ── Government Spending Confluence Strategy ────────────────────────────────
# Five new tabs powering the USAspending + CapitolTrades + insider feed
# combined into per-ticker confluence signals. Designed in
# docs/plans/2026-05-10-gov-spending-confluence-strategy-design.md.

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
        ]


@dataclass
class AlpacaSnapshotRow:
    """Paper account snapshot — written by sync_alpaca.py on each run."""
    TAB_NAME = "snapshot_alpaca"
    HEADERS = ["date", "net_liq", "cash", "buying_power", "long_value", "short_value"]

    date: str
    net_liq: str = "0"
    cash: str = "0"
    buying_power: str = "0"
    long_value: str = "0"
    short_value: str = "0"

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        return [d, self.net_liq, self.cash, self.buying_power, self.long_value, self.short_value]


@dataclass
class AlpacaPositionRow:
    """One row per open Alpaca paper position."""
    TAB_NAME = "positions_alpaca"
    HEADERS = ["date", "ticker", "qty", "avg_cost", "last", "mkt_val", "upl", "upl_pct", "side"]

    date: str
    ticker: str
    qty: str = "0"
    avg_cost: str = "0"
    last: str = "0"
    mkt_val: str = "0"
    upl: str = "0"
    upl_pct: str = "0"
    side: str = "long"

    def to_row(self) -> List[str]:
        return [self.date, self.ticker, self.qty, self.avg_cost, self.last,
                self.mkt_val, self.upl, self.upl_pct, self.side]


@dataclass
class PaperBenchmarkRow:
    """'Did this pick beat just holding SPY?' — per open paper position + a TOTAL
    row. Compares each position's P&L to the P&L the SAME entry capital would
    have made in SPY over the SAME holding window, isolating the picks' edge from
    the paper account's idle cash. The honest answer to 'does the active book
    beat the index'."""
    TAB_NAME = "paper_benchmark"
    HEADERS = [
        "date", "ticker", "entry_date", "days_held", "cost_basis",
        "position_pl", "spy_return_pct", "spy_equiv_pl", "alpha_pl", "beat_spy",
    ]

    date: str
    ticker: str
    entry_date: str
    days_held: int
    cost_basis: float
    position_pl: float
    spy_return_pct: float
    spy_equiv_pl: float
    alpha_pl: float
    beat_spy: bool

    def to_row(self) -> List[str]:
        return [self.date, self.ticker, self.entry_date, str(self.days_held),
                _num(self.cost_basis, 2), _num(self.position_pl, 2),
                _num(self.spy_return_pct, 2), _num(self.spy_equiv_pl, 2),
                _num(self.alpha_pl, 2), "TRUE" if self.beat_spy else ""]


@dataclass
class HarvestScanRow:
    """Premium Harvest scanner output — one row per candidate per day.

    Each row carries entry/maintenance/exit signal blocks as JSON strings
    so the PWA and Telegram can render full lifecycle plans.
    """
    TAB_NAME = "harvest_scan"
    HEADERS = [
        "date", "ticker", "strategy", "strike", "expiry", "dte",
        "credit", "annual_yield_pct", "iv_rank", "conviction",
        "underlying_last", "cash_required", "breakeven",
        "sr_context", "macro_regime", "vix",
        "entry_signals", "maintenance_signals", "exit_signals",
        "notes",
    ]

    date: str
    ticker: str
    strategy: str           # HARVEST_CSP
    strike: float
    expiry: str             # YYYYMMDD
    dte: int
    credit: float
    annual_yield_pct: float
    iv_rank: float
    conviction: int         # 0-100
    underlying_last: float
    cash_required: float
    breakeven: float
    sr_context: str         # "near support $98 (7%) · RSI 42"
    macro_regime: str       # STANDARD | CAUTION | HALTED
    vix: float
    entry_signals: str      # JSON dict
    maintenance_signals: str  # JSON dict
    exit_signals: str       # JSON dict
    notes: str              # e.g. "call_strike=140" for strangles

    def to_row(self) -> List[str]:
        return [
            self.date, self.ticker, self.strategy,
            _num(self.strike, 2), self.expiry, str(self.dte),
            _num(self.credit, 2), _num(self.annual_yield_pct, 1),
            _num(self.iv_rank, 1), str(self.conviction),
            _num(self.underlying_last, 2), _num(self.cash_required, 2),
            _num(self.breakeven, 2),
            self.sr_context, self.macro_regime, _num(self.vix, 1),
            self.entry_signals, self.maintenance_signals, self.exit_signals,
            self.notes,
        ]


@dataclass
class IvSurfaceScanRow:
    """IV surface scanner output — one row per option contract per day.

    The key metric is iv_excess: actual IV minus fitted IV surface value
    in percentage points. Positive = rich premium (sell candidate).
    Negative = cheap (skip or buy).
    """
    TAB_NAME = "iv_surface_scan"
    HEADERS = [
        "date", "ticker", "type", "strike", "expiry", "dte", "spot",
        "iv", "iv_fitted", "iv_excess",
        "delta", "bid", "ask", "mid", "ann_yield_pct",
        "oi", "volume", "spread_pct",
        "assignment_risk", "earnings_before_expiry",
    ]

    date: str
    ticker: str
    type: str               # "P" or "C"
    strike: float
    expiry: str             # YYYY-MM-DD
    dte: int
    spot: float
    iv: float               # actual implied vol (0-1 scale)
    iv_fitted: float        # fitted surface value
    iv_excess: float        # iv - iv_fitted in percentage points
    delta: float            # Black-Scholes delta
    bid: float
    ask: float
    mid: float
    ann_yield_pct: float    # annualised yield on capital at risk
    oi: int                 # open interest
    volume: int
    spread_pct: float       # bid-ask spread as %
    assignment_risk: str    # "LOW" | "MEDIUM" | "HIGH"
    earnings_before_expiry: bool

    def to_row(self) -> List[str]:
        return [
            self.date, self.ticker, self.type,
            _num(self.strike, 2), self.expiry, str(self.dte),
            _num(self.spot, 2),
            _num(self.iv, 4), _num(self.iv_fitted, 4),
            _num(self.iv_excess, 2),
            _num(self.delta, 4),
            _num(self.bid, 2), _num(self.ask, 2), _num(self.mid, 2),
            _num(self.ann_yield_pct, 1),
            str(self.oi), str(self.volume),
            _num(self.spread_pct, 1),
            self.assignment_risk,
            "TRUE" if self.earnings_before_expiry else "",
        ]


# ── outcome_pnl_pct semantics version ────────────────────────────────────────
# The premium-inclusive P&L fix (settles at the strike, nets the credit) changed
# what outcome_pnl_pct MEANS. Rows written before the fix carry the old raw/
# capped stock-return proxy and an empty/absent pnl_model; rows written after are
# stamped PNL_MODEL_PREMIUM. Downstream consumers (option_scanner.realized_kelly_inputs,
# the Phase-2 weight regression) filter to PNL_MODEL_PREMIUM so the two semantics
# are never blended. signal_feedback appends (no UPSERT), so the historical rows
# are versioned in place rather than destructively backfilled.
PNL_MODEL_PREMIUM = "premium_v2"      # premium-inclusive, settles at the strike
PNL_MODEL_LEGACY = "stock_proxy_v1"   # pre-fix raw/capped stock-return proxy (historical only)


@dataclass
class SignalOutcomeRow:
    """Per-pick signal outcome — matches scan picks to forward price action.

    Enables empirical weight calibration: which signals in technical_score.py
    ACTUALLY predicted profitable setups vs which are noise?

    Written weekly by scripts/signal_feedback.py. Each row captures:
      - The scan pick identity (date, ticker, strategy, strike, expiry)
      - The 16 normalized signal values at scan time (reconstructed from
        yfinance OHLCV via compute_indicators + compute_signals)
      - Forward price returns at evaluation horizon
      - Strategy-specific outcome (WIN/LOSS/SCRATCH)

    The weight optimizer (Phase 2) reads these rows and runs OLS regression
    outcome ~ beta_i * signal_i to derive empirically-optimal weights, then
    compares to STRATEGY_WEIGHTS in technical_score.py.

    UPSERT key: (scan_date, ticker, strategy, strike, expiry) — one outcome
    per unique pick. Re-runs overwrite with updated forward data.
    """
    TAB_NAME = "signal_outcomes"
    HEADERS = [
        "scan_date", "eval_date", "ticker", "strategy",
        "scan_composite", "scan_technical",
        "strike", "expiry", "dte",
        "price_at_scan", "price_at_eval",
        "fwd_return_pct", "strategy_outcome", "outcome_pnl_pct",
        # 16 normalized signal values at scan time [-1, +1]
        "sig_rsi", "sig_macd", "sig_macd_cross", "sig_bb_pct_b",
        "sig_bb_squeeze", "sig_wvf", "sig_trend", "sig_momentum",
        "sig_volume_spike", "sig_divergence", "sig_candle",
        "sig_fib_support", "sig_volatility", "sig_vol_regime",
        "sig_iv_rv_ratio", "sig_term_structure",
        # outcome_pnl_pct semantics version (see PNL_MODEL_* above). Appended
        # LAST so legacy 30-col rows stay positionally aligned on read-back.
        "pnl_model",
    ]

    scan_date: str
    eval_date: str          # date outcome was evaluated
    ticker: str
    strategy: str           # CSP | CC | BUY | LONG_CALL | LONG_PUT
    scan_composite: float   # composite_score from scan_results
    scan_technical: float   # technical_score from scan_results
    strike: float
    expiry: str             # YYYYMMDD
    dte: int
    price_at_scan: float    # underlying_last from scan row
    price_at_eval: float    # price at expiry or +30d
    fwd_return_pct: float   # (price_at_eval / price_at_scan - 1) * 100
    strategy_outcome: str   # WIN | LOSS | SCRATCH
    outcome_pnl_pct: float  # estimated strategy P&L %
    # Signal values (from compute_signals at scan date)
    sig_rsi: float = 0.0
    sig_macd: float = 0.0
    sig_macd_cross: float = 0.0
    sig_bb_pct_b: float = 0.0
    sig_bb_squeeze: float = 0.0
    sig_wvf: float = 0.0
    sig_trend: float = 0.0
    sig_momentum: float = 0.0
    sig_volume_spike: float = 0.0
    sig_divergence: float = 0.0
    sig_candle: float = 0.0
    sig_fib_support: float = 0.0
    sig_volatility: float = 0.0
    sig_vol_regime: float = 0.0
    sig_iv_rv_ratio: float = 0.0
    sig_term_structure: float = 0.0
    pnl_model: str = PNL_MODEL_PREMIUM   # semantics of outcome_pnl_pct (see PNL_MODEL_* above)

    def to_row(self) -> List[str]:
        return [
            self.scan_date, self.eval_date, self.ticker, self.strategy,
            _num(self.scan_composite, 1), _num(self.scan_technical, 1),
            _num(self.strike, 2), self.expiry, str(self.dte),
            _num(self.price_at_scan, 4), _num(self.price_at_eval, 4),
            _num(self.fwd_return_pct, 2), self.strategy_outcome,
            _num(self.outcome_pnl_pct, 2),
            _num(self.sig_rsi, 3), _num(self.sig_macd, 3),
            _num(self.sig_macd_cross, 3), _num(self.sig_bb_pct_b, 3),
            _num(self.sig_bb_squeeze, 3), _num(self.sig_wvf, 3),
            _num(self.sig_trend, 3), _num(self.sig_momentum, 3),
            _num(self.sig_volume_spike, 3), _num(self.sig_divergence, 3),
            _num(self.sig_candle, 3), _num(self.sig_fib_support, 3),
            _num(self.sig_volatility, 3), _num(self.sig_vol_regime, 3),
            _num(self.sig_iv_rv_ratio, 3), _num(self.sig_term_structure, 3),
            self.pnl_model,
        ]


@dataclass
class UoaAlertRow:
    """Unusual Options Activity alert — one row per alert per day.

    Flags abnormal volume/OI patterns that may indicate informed money,
    institutional positioning, or large directional bets.
    """
    TAB_NAME = "uoa_alerts"
    HEADERS = [
        "date", "ticker", "alert_type", "side", "strike", "expiry", "dte",
        "volume", "open_interest", "vol_oi_ratio", "implied_vol",
        "notional", "moneyness", "underlying_last", "option_price",
        "severity", "detail",
    ]

    date: str
    ticker: str
    alert_type: str         # VOL_OI_SPIKE | STRIKE_CONC | OTM_FLOW | PC_SKEW
    side: str               # CALL | PUT
    strike: float
    expiry: str             # YYYY-MM-DD
    dte: int
    volume: int
    open_interest: int
    vol_oi_ratio: float
    implied_vol: float      # 0-1 scale
    notional: float         # dollar value of flow
    moneyness: str          # ITM | ATM | OTM | FAR_OTM
    underlying_last: float
    option_price: float     # mid price per share (bid+ask)/2
    severity: int           # 1=notable, 2=significant, 3=extreme
    detail: str             # human-readable explanation

    def to_row(self) -> List[str]:
        return [
            self.date, self.ticker, self.alert_type, self.side,
            _num(self.strike, 2), self.expiry, str(self.dte),
            str(self.volume), str(self.open_interest),
            _num(self.vol_oi_ratio, 1), _num(self.implied_vol, 4),
            _num(self.notional, 0), self.moneyness,
            _num(self.underlying_last, 2), _num(self.option_price, 2),
            str(self.severity), self.detail,
        ]
