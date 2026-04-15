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
    HEADERS = ["date", "bullet_1", "bullet_2", "bullet_3", "verdict", "sentiment"]

    date: str
    bullet_1: str
    bullet_2: str
    bullet_3: str
    verdict: str          # free text one-liner
    sentiment: str        # "bullish" | "neutral" | "bearish" (or emoji)

    def to_row(self, audit: bool = True) -> List[str]:
        d = _ts_suffix(self.date) if audit else self.date
        return [d, self.bullet_1, self.bullet_2, self.bullet_3, self.verdict, self.sentiment]


@dataclass
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
    return DailyBriefRow(
        date=str(sidecar.get("date", "")),
        bullet_1=bullets[0],
        bullet_2=bullets[1],
        bullet_3=bullets[2],
        verdict=str(sidecar.get("verdict", "")),
        sentiment=str(sidecar.get("sentiment", "")),
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
