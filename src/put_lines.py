"""
Cash-secured puts a book's cash can actually cover.

The options scan lists puts by yield across the whole market, most of them far
bigger than either book's cash. This turns its rows into a short list per book:
what fits the cash now, what fits once the month's deposit lands, and what the
smallest line needs when nothing does. No I/O: the scan and the DM do that.

RANKING. Tested on graded lines, one row per contract, Apr-Sep 2026, split at
1 Jul so each rule faced two separate periods:
  - a cushion of 9%+ beat a smaller one in both (+1.2 vs +0.0, +3.3 vs -0.3 % of strike);
  - a ticker's own past record predicted nothing (+0.76 vs +0.73), so it isn't used.
Profitable-first is a rule, not a finding: Caspar and Sarah don't sell losers, so
an assigned stock stays in the book. The history can't test it.

A line with no live quote stays listed before the open, marked and ranked last.
The re-check after the open re-quotes it and drops it if it still has none.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

MAX_QUOTE_AGE_DAYS = 4       # keeps Friday's scan on Monday morning
MIN_DTE = 21                 # closer than this, the exit rule would already close it
FILL_SHARE = 0.25            # assume a sell fills a quarter of the way up from the bid
MAX_SPREAD_PCT = 0.25        # of the mid; wider and the mid is not a price
MAX_SPREAD_USD = 0.10        # ...except a cheap option, where one tick is already this
MAX_MOVE_SINCE_QUOTE = 0.05  # the stock moved this far: strike and delta are stale
MIN_CUSHION = 0.02           # strike must still sit this far under the stock
CUSHION_TIER = 0.09          # the graded split, see the module docstring
NEXT_REPORT_AFTER_DAYS = 75  # next quarter's report comes at least this long after the last
MAX_PER_BOOK = 3             # lines shown per book
MAX_RUNG = 3                 # lines named on the "once the deposit lands" line

_FLOW = re.compile(r"[🟥🟧] ADVERSE FLOW[^|]*")


def _fnum(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def spread_ok(bid: float, ask: float) -> bool:
    return ask - bid <= max(MAX_SPREAD_PCT * (bid + ask) / 2, MAX_SPREAD_USD)


def _iso(expiry: str) -> str:
    s = str(expiry).replace("-", "")[:8]
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


@dataclass
class PutLine:
    ticker: str
    strike: float
    expiry: str             # YYYY-MM-DD
    dte: int
    delta: float            # at the scan; |delta| is the market's rough odds of assignment
    bid: float
    ask: float
    premium: float          # the scan's mid, or the last trade when it had no quote
    underlying: float
    scanned_at: str
    scan_ts: float | None = None  # when the row was scanned; only cash-fit rows carry it
    eps: float | None = None   # trailing EPS at the scan; None when the scan didn't look
    kind: str = ""             # "ETF" | "stock" | ""
    flow: str = ""             # the scan's adverse-flow tag
    earnings: str = ""         # "clear" | "none" (an ETF) | "unknown"
    last_report: str = ""      # YYYY-MM-DD, the latest report behind it
    moved: float = 0.0         # stock's move since the quote
    live: bool = False         # bid/ask re-quoted after the open

    @property
    def quoted(self) -> bool:
        return self.bid > 0 and self.ask >= self.bid

    @property
    def fill(self) -> float:
        return self.bid + (self.ask - self.bid) * FILL_SHARE if self.quoted else self.premium

    @property
    def credit(self) -> float:
        return self.fill * 100

    @property
    def collateral(self) -> float:
        return self.strike * 100

    @property
    def breakeven(self) -> float:
        return self.strike - self.fill

    @property
    def cushion(self) -> float:
        return 1 - self.breakeven / self.underlying if self.underlying else 0.0

    @property
    def ann_yield(self) -> float:
        return self.fill / self.strike * 365 / self.dte if self.strike and self.dte > 0 else 0.0

    @property
    def spread_ok(self) -> bool:
        return self.quoted and spread_ok(self.bid, self.ask)

    @property
    def loses_money(self) -> bool:
        return self.eps is not None and self.eps < 0


def parse_scan_rows(rows: list[dict], today: str) -> list[PutLine]:
    """The put rows of the options scan, each ticker from its newest scan only."""
    t0 = date.fromisoformat(today)
    cutoff = (t0 - timedelta(days=MAX_QUOTE_AGE_DAYS)).isoformat()
    puts = [r for r in rows if str(r.get("strategy") or "").upper() == "CSP"
            and str(r.get("date") or "")[:10] >= cutoff]
    newest: dict[str, str] = {}
    for r in puts:
        tk = str(r.get("ticker") or "").strip().upper()
        newest[tk] = max(newest.get(tk, ""), str(r.get("date") or "")[:10])
    out: dict[tuple, PutLine] = {}
    for r in puts:
        tk = str(r.get("ticker") or "").strip().upper()
        if str(r.get("date") or "")[:10] != newest[tk]:    # rows of one run differ by seconds
            continue
        strike, under = _fnum(r.get("strike")), _fnum(r.get("underlying_last"))
        if not tk or not strike or not under or not r.get("expiry"):
            continue
        try:
            expiry = _iso(r["expiry"])
            dte = (date.fromisoformat(expiry) - t0).days
        except ValueError:
            continue
        if dte < MIN_DTE:
            continue
        try:
            extra = json.loads(r.get("signals_json") or "{}")
        except (TypeError, ValueError):
            extra = {}
        if not isinstance(extra, dict):
            extra = {}
        flow = _FLOW.search(str(r.get("notes") or ""))
        out[(tk, strike, expiry)] = PutLine(
            ticker=tk, strike=strike, expiry=expiry, dte=dte,
            delta=_fnum(r.get("delta")) or 0.0, bid=_fnum(r.get("bid")) or 0.0,
            ask=_fnum(r.get("ask")) or 0.0, premium=_fnum(r.get("premium")) or 0.0,
            underlying=under, scanned_at=str(r.get("date") or ""), scan_ts=_fnum(extra.get("scan_ts")),
            eps=_fnum(extra.get("eps")),
            kind="" if "is_etf" not in extra else "ETF" if extra["is_etf"] else "stock",
            flow=flow.group(0).strip() if flow else "")
    return list(out.values())


def check_line(line: PutLine, last: float | None, upcoming: list[str], reported: str,
               kind: str, today: str) -> str | None:
    """Bring a line up to date. Returns why it's out, or None if it stays."""
    if not last:        # the scan's price may be days old, and nothing here can say so
        return "no price"
    line.moved = last / line.underlying - 1
    if abs(line.moved) > MAX_MOVE_SINCE_QUOTE:
        return f"moved {line.moved:+.0%} since the quote"
    line.underlying = last
    if line.strike > last * (1 - MIN_CUSHION):
        return "no cushion left"
    if line.quoted and not line.spread_ok:
        return "spread too wide"
    if kind:
        line.kind = kind
    if line.kind == "ETF":
        line.earnings = "none"
        return None
    ahead = sorted(d for d in upcoming if today <= d <= line.expiry)
    if ahead:
        return f"earnings {ahead[0]} before expiry"
    line.last_report = reported
    # No date ahead isn't proof there is none, unless the last report is recent
    # enough that the next one can't land before expiry.
    gap = (date.fromisoformat(line.expiry) - date.fromisoformat(reported)).days if reported else None
    line.earnings = "clear" if upcoming or (gap is not None and gap < NEXT_REPORT_AFTER_DAYS) else "unknown"
    return None


def rank(line: PutLine) -> tuple:
    """Best first. See the module docstring for why this order."""
    return (not line.quoted, line.earnings == "unknown", bool(line.flow), line.loses_money,
            line.cushion < CUSHION_TIER, -line.ann_yield, line.ticker)


@dataclass
class BookPuts:
    fits: list[PutLine] = field(default_factory=list)      # cash covers it now, best first
    rung: list[PutLine] = field(default_factory=list)      # needs the month's deposit too
    cheapest: PutLine | None = None                        # smallest line, when nothing fits
    free_cash: float | None = None                         # USD, net of cash securing open puts


def for_book(lines: list[PutLine], cash_usd: float, deposit_usd: float, nlv_usd: float,
             weights: dict[str, float], cap: float) -> BookPuts:
    """Sort checked lines into what this book's cash covers: one line per ticker,
    and none that would take a name past the book's concentration cap if assigned.
    A ticker with a line that fits now stays off the deposit rung."""
    ok = [ln for ln in sorted(lines, key=rank)
          if not (nlv_usd > 0 and weights.get(ln.ticker, 0.0) + ln.collateral / nlv_usd > cap)]
    fits, rung, seen = [], [], set()
    for ln in ok:
        if ln.collateral <= cash_usd and ln.ticker not in seen:
            seen.add(ln.ticker)
            fits.append(ln)
    for ln in ok:
        if cash_usd < ln.collateral <= cash_usd + deposit_usd and ln.ticker not in seen:
            seen.add(ln.ticker)
            rung.append(ln)
    out = BookPuts(fits=fits[:MAX_PER_BOOK], rung=rung[:MAX_RUNG], free_cash=cash_usd)
    if not fits and ok:
        out.cheapest = min(ok, key=lambda ln: (ln.collateral, rank(ln)))
    return out


def cash_securing_puts(option_rows: list[dict]) -> dict[str, float]:
    """USD already securing open short puts, per account, from the `options` tab's
    latest date. That cash can't secure a second put."""
    last = max((str(r.get("date") or "")[:10] for r in option_rows), default="")
    out: dict[str, float] = {}
    for r in option_rows:
        if str(r.get("date") or "")[:10] != last or str(r.get("right") or "").upper() != "P":
            continue
        qty, strike = _fnum(r.get("qty")), _fnum(r.get("strike"))
        if qty and qty < 0 and strike:
            acct = str(r.get("account") or "").strip().lower()
            out[acct] = out.get(acct, 0.0) + strike * 100 * -qty
    return out


# ── Graded record ────────────────────────────────────────────────────────────

@dataclass
class PutRecord:
    n: int
    kept: float      # share of lines that kept money
    avg: float       # average result, % of strike
    lost5: float     # share that lost over 5% of strike
    worst: float     # % of strike


def graded_contracts(rows: list[dict]) -> list[dict]:
    """One row per contract from `signal_outcomes`: the scan repeats a contract for
    days, which would count one trade many times. Keeps the stock's price at the
    first scan and the result at the latest grading."""
    first: dict[tuple, dict] = {}
    final: dict[tuple, dict] = {}
    for r in sorted(rows, key=lambda r: (str(r.get("scan_date")), str(r.get("eval_date")))):
        if r.get("strategy") != "CSP" or r.get("pnl_model") != "premium_v2":
            continue
        if _fnum(r.get("outcome_pnl_pct")) is None:
            continue
        k = (r.get("ticker"), r.get("strike"), r.get("expiry"))
        first.setdefault(k, r)
        final[k] = r
    return [{"ticker": k[0], "price": _fnum(first[k].get("price_at_scan")) or 0.0,
             "pnl": _fnum(final[k].get("outcome_pnl_pct")),
             "won": final[k].get("strategy_outcome") == "WIN"} for k in final]


def record_of(graded: list[dict], under_price: float | None = None) -> PutRecord | None:
    xs = [g for g in graded if under_price is None or 0 < g["price"] < under_price]
    if not xs:
        return None
    pnl = [g["pnl"] for g in xs]
    return PutRecord(n=len(xs), kept=sum(g["won"] for g in xs) / len(xs), avg=sum(pnl) / len(pnl),
                     lost5=sum(p < -5 for p in pnl) / len(pnl), worst=min(pnl))


UNDER_25 = 25.0


def record_text(graded: list[dict], lines: list[PutLine]) -> str:
    """The record of the lines most like these: the stocks-under-$25 band when
    every line is in it, every graded line otherwise."""
    cheap = bool(lines) and all(ln.underlying < UNDER_25 for ln in lines)
    rec = record_of(graded, UNDER_25 if cheap else None)
    if rec is None:
        return "No graded put lines yet."
    what = "puts on stocks under $25" if cheap else "put lines"
    avg = f"{rec.avg:+.1f}".replace("-", "−")
    worst = f"{rec.worst:+.0f}".replace("-", "−")
    return (f"Graded {what}: {rec.n}, {rec.kept:.0%} kept money, average {avg}% of the cash put up, "
            f"{rec.lost5:.0%} lost over 5%, worst {worst}%. Modelled at the mid, before costs.")
