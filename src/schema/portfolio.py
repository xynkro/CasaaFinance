"""Portfolio + account snapshot schemas (IBKR + Alpaca) and their factory helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from ._base import _num, _ts_suffix


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
    HEADERS = ["date", "ticker", "qty", "avg_cost", "last", "mkt_val", "upl", "upl_pct", "side",
               "origin"]   # "casaa" = FinancePWA's automated book | "external" = other bot (ZeroDTE/decisions)

    date: str
    ticker: str
    qty: str = "0"
    avg_cost: str = "0"
    last: str = "0"
    mkt_val: str = "0"
    upl: str = "0"
    upl_pct: str = "0"
    side: str = "long"
    origin: str = "casaa"

    def to_row(self) -> List[str]:
        return [self.date, self.ticker, self.qty, self.avg_cost, self.last,
                self.mkt_val, self.upl, self.upl_pct, self.side, self.origin]


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
