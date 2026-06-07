"""Technical-scan + screener schemas: per-ticker technical scores, ranked
scan candidates, and weekly fresh-ticker screen candidates."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from ._base import _num, _ts_suffix


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
