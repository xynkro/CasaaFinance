"""Options-domain schemas: positions, recommendations, defense, wheel legs,
yield/harvest/IV-surface/UOA scanners, GEX regime, and signal outcomes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from ._base import _num, _ts_suffix


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
class GexRegimeRow:
    """Daily dealer Gamma Exposure regime per index/ETF (SPY, QQQ).

    Read by the PWA (pre-market banner) and the paper executor (premium-selling
    gate): positive gamma → vol suppressed → friendly for CSP/CC/credit spreads;
    negative gamma → gap risk → sell premium with caution. See src/gex.py.
    """
    TAB_NAME = "gex_regime"
    HEADERS = [
        "date", "symbol", "spot",
        "net_gex",            # net dealer dollar-gamma ($ per 1% move; calls +, puts −)
        "gamma_flip",         # zero-gamma spot level (0 if none found)
        "flip_distance_pct",  # (spot − flip) / spot * 100
        "call_wall",          # largest call-gamma strike at/above spot (resistance)
        "put_wall",           # largest put-gamma strike at/below spot (support)
        "regime",             # POSITIVE_PINNED | NEGATIVE_TREND | NEUTRAL
        "premium_gate",       # SELL_OK | SELL_CAUTION | NORMAL
        "note",
        "updated_at",
    ]

    date: str
    symbol: str
    spot: float
    net_gex: float
    gamma_flip: float
    flip_distance_pct: float
    call_wall: float
    put_wall: float
    regime: str
    premium_gate: str
    note: str = ""
    updated_at: str = ""

    def to_row(self) -> List[str]:
        return [
            self.date, self.symbol, _num(self.spot, 2),
            _num(self.net_gex, 0), _num(self.gamma_flip, 2),
            _num(self.flip_distance_pct, 2),
            _num(self.call_wall, 2), _num(self.put_wall, 2),
            self.regime, self.premium_gate, self.note, self.updated_at,
        ]


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
