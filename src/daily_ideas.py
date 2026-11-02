"""Daily ideas DM — one Telegram message a day that carries specific, sized
buy/watch ideas to Caspar's DM, each with its source's graded record vs SPY.

Design agreed with Caspar on 2026-10-31, from a mock built on live Sheet data:

  - Every idea source is graded the same way: fill at its trigger, hold 20
    trading days, compare with SPY over the identical days. The t-stat is
    clustered by entry week, so one basket of same-week ideas counts as one
    piece of evidence, not thirty.
  - Tier by that record: ahead of SPY beyond noise → 5% of the account;
    can't tell from SPY → 2% probation; behind beyond noise → watch only.
  - Size = tier % × account net liq, rounded down to whole shares/contracts.
    If that rounds to zero, one unit is allowed when it costs no more than
    1.5× the size; otherwise that account gets no size.
  - Budget = cash on hand + the month's deposit. The DM says which ideas fit
    now and which wait for the deposit. Deposit amounts live in the Sheet
    (`monthly_deposits` tab), never in this public repo.
  - Both books in one DM, each with its own section. It names account cash,
    so it only ever goes to the personal DM lane, which fails closed.
  - Two sends (Caspar, 2026-11-02): a pre-open plan with a direction block,
    then a re-check ~15 min after the US open on live prices, so an idea whose
    stop broke this morning is dropped. The re-check says only what changed,
    and only it goes in the graded ledger.
  - Take-profit exits (Caspar, 2026-11-01: "If it goes up, we sell and take
    profits"): the WSR's TRIM rows on positions that are in profit, at the
    WSR's own share count. Graded by the same rule from the other side — did
    the stock lag SPY over the 20 sessions after the trim filled? Trims of
    losers and hold-list names are never shown (never-sell-a-loser rule).

Pure logic only — no Sheet, network or Telegram calls. scripts/daily_ideas_dm.py
does the I/O and tests/test_daily_ideas.py covers the rules.
"""
from __future__ import annotations

import bisect
import html
import math
import re
import statistics as st
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from zoneinfo import ZoneInfo

HOLD_DAYS = 20          # trading days each graded idea is held
COST_PER_SIDE = 0.001   # slippage and commission allowance per trade: 10 bps
FILL_WINDOW = 10        # trading days a buy-dip trigger has to fill
SIZE_PCT = {"green": 0.05, "yellow": 0.02, "red": 0.0}
TIER_EMOJI = {"green": "🟢", "yellow": "🟡", "red": "🔴"}
STALE_AFTER_REPORT_DAYS = 30    # a Sheet date this soon after a confirmed report is an old estimate
ONE_UNIT_MAX_OVER = 1.5      # one share/contract allowed up to 1.5× the size
CONCENTRATION_CAP = 0.30     # never size a name past 30% of a book (alert band)
MAX_SIZED = 5                # sized ideas per DM
NEAR_TRIGGER = 0.03          # dip-buys within 3% above trigger get sized
WSR_MAX_AGE_DAYS = 8         # a WSR row older than one weekly cycle is stale
TRIM_GAP_DAYS = 14           # a trim re-stated daily is one idea until it lapses 2 weeks
MAX_EXITS = 5                # take-profit exits per DM
TELEGRAM_LIMIT = 4096
SGT = ZoneInfo("Asia/Singapore")
RECHECK_ET = (9, 47)         # the post-open re-check, ET wall clock
STALE_BOOK_DAYS = 10         # cash and share counts this still = prices-only data
EARNINGS_AHEAD_DAYS = 7      # a book's section lists reports due this soon
GEX_MAX_AGE_DAYS = 5         # older dealer levels are not shown
MIN_BRIEF_CALLS = 10         # the brief's record is shown from this many calls

# Index ETFs are excluded from the options-flow record: graded against SPY,
# a SPY call is SPY, so they would pull the record toward zero by construction.
INDEX_ETFS = frozenset({"SPY", "QQQ", "IWM", "DIA", "VOO", "IVV"})

SOURCE_LABEL = {
    "wsr": "WSR dip-buys",
    "uoa": "Unusual options, bullish",
    "gov": "Gov-contract signals",
    "momentum": "Momentum screen",
    "wsr_trim": "WSR profit-takes",
}
SELL_SOURCES = frozenset({"wsr_trim"})   # graded from the seller's side
ACCOUNT_LABEL = {"caspar": "Caspar", "sarah": "Sarah"}
_POSSESSIVE = {"caspar": "his", "sarah": "her"}


# ─────────────────────────────────────────────────────────────────────────
# Small helpers
# ─────────────────────────────────────────────────────────────────────────

def fnum(x) -> float | None:
    try:
        v = float(str(x).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError, AttributeError):
        return None
    return v if math.isfinite(v) else None


def esc(s) -> str:
    """Escape for Telegram HTML parse mode."""
    return html.escape(str(s), quote=False)


def _minus(s: str) -> str:
    return s.replace("-", "−")


def pct(x: float, digits: int = 1, sign: bool = True) -> str:
    """0.0423 → '+4.2%' with a real minus sign."""
    fmt = f"{{:{'+' if sign else ''}.{digits}f}}%"
    return _minus(fmt.format(x * 100))


def usd(x: float) -> str:
    """Money amount: $957, $1,050."""
    return f"${x:,.0f}"


def px(x: float) -> str:
    """Price: $240, $239.36, $7.80."""
    return f"${x:,.0f}" if x == round(x) else f"${x:,.2f}"


def prem(x: float) -> str:
    """Option premium, always with cents: $3.00, $7.65."""
    return f"${x:,.2f}"


def big_money(x: float) -> str:
    """$1.97B, $39M, $850k."""
    if abs(x) >= 1e9:
        return f"${x / 1e9:.2f}B"
    if abs(x) >= 1e6:
        return f"${x / 1e6:.0f}M"
    return f"${x / 1e3:.0f}k"


def short_money(x: float, prefix: str = "$") -> str:
    """$90, $512, $3.1k, S$1.2k."""
    if abs(x) >= 1000:
        return f"{prefix}{x / 1000:.1f}k".replace(".0k", "k")
    return f"{prefix}{x:,.0f}"


def day(d: str) -> date:
    return date.fromisoformat(str(d)[:10])


# ─────────────────────────────────────────────────────────────────────────
# Prices
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class Bars:
    """One ticker's daily OHLC, oldest first. Dates are YYYY-MM-DD.

    Prices are raw (triggers are quoted in raw prices). `adj` is the
    dividend-adjusted close, used only to turn a hold into a total return —
    without it, bond and dividend ETFs would be graded as if they paid nothing.
    """
    dates: list[str]
    o: list[float]
    h: list[float]
    l: list[float]
    c: list[float]
    adj: list[float] | None = None

    def __post_init__(self):
        self._ix = {d: i for i, d in enumerate(self.dates)}
        if self.adj is None:
            self.adj = list(self.c)

    def total_return(self, entry_i: int, entry_px: float, exit_i: int) -> float:
        """Bought at entry_px on bar entry_i, held to the close of bar exit_i."""
        return self.c[entry_i] / entry_px * (self.adj[exit_i] / self.adj[entry_i]) - 1

    def idx(self, d: str) -> int | None:
        return self._ix.get(d)

    def upto(self, d: str) -> int:
        """Count of bars dated strictly before d."""
        n = 0
        for x in self.dates:
            if x < d:
                n += 1
            else:
                break
        return n


# ─────────────────────────────────────────────────────────────────────────
# Grading: every source by one rule
# ─────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PastIdea:
    source: str
    ticker: str
    date: str                 # YYYY-MM-DD the idea was published
    trigger: float | None     # buy-dip / trim level; None = a signal, filled next open
    side: str = "buy"         # "sell" = a trim: right when the stock then lags SPY


@dataclass
class Record:
    source: str
    n: int = 0
    beat: int = 0
    mean_alpha: float = 0.0   # per 20-day hold, as a fraction
    t: float | None = None
    clusters: int = 0
    top_cluster_share: float = 0.0
    open: int = 0
    unfilled: int = 0
    nodata: int = 0           # ideas with no price history — never silently "graded"
    tier: str = "yellow"
    note: str = ""            # why the tier is what it is, when not the t-stat

    @property
    def near_cut(self) -> bool:
        return self.tier == "yellow" and self.t is not None and self.t <= -1.5


def wsr_history(dq_rows: list[dict]) -> list[PastIdea]:
    """Every WSR buy-dip, first appearance per (ticker, trigger)."""
    out, seen = [], set()
    for r in sorted(dq_rows, key=lambda r: r.get("date", "")):
        if (r.get("strategy") or "").upper() != "BUY_DIP":
            continue
        if (r.get("source") or "") not in ("wsr_lite", "wsr_full"):
            continue
        e = fnum(r.get("entry"))
        tk = (r.get("ticker") or "").strip().upper()
        if not e or e <= 0 or not tk:
            continue
        k = (tk, round(e, 2))
        if k in seen:
            continue
        seen.add(k)
        out.append(PastIdea("wsr", tk, r["date"][:10], e))
    return out


def _is_bullish_q80(r: dict) -> bool:
    q = fnum(r.get("quality"))
    tk = (r.get("ticker") or "").strip().upper()
    return (r.get("bias") or "").upper() == "BULLISH" and q is not None and q >= 80 \
        and tk not in INDEX_ETFS


def uoa_history(rows: list[dict]) -> list[PastIdea]:
    """High-quality bullish flow reads, one per ticker per day."""
    out, seen = [], set()
    for r in rows:
        if not _is_bullish_q80(r):
            continue
        k = ((r.get("ticker") or "").strip().upper(), (r.get("date") or "")[:10])
        if k in seen or not k[0] or not k[1]:
            continue
        seen.add(k)
        out.append(PastIdea("uoa", k[0], k[1], None))
    return out


def _first_appearances(rows: list[dict], gap_days: int = 30):
    """Rows where a ticker shows up after at least `gap_days` without it."""
    last: dict[str, date] = {}
    for r in sorted(rows, key=lambda r: r.get("date", "")):
        tk = (r.get("ticker") or "").strip().upper()
        if not tk or not r.get("date"):
            continue
        d = day(r["date"])
        if tk not in last or (d - last[tk]).days >= gap_days:
            yield tk, d, r
        last[tk] = d


def gov_history(rows: list[dict]) -> list[PastIdea]:
    """Gov-contract signals scoring >= 45, first appearance per ticker per 30d."""
    return [PastIdea("gov", tk, d.isoformat(), None)
            for tk, d, r in _first_appearances(rows)
            if (fnum(r.get("investment_score")) or 0) >= 45]


def momentum_history(rows: list[dict]) -> list[PastIdea]:
    return [PastIdea("momentum", tk, d.isoformat(), None)
            for tk, d, r in _first_appearances(
                [r for r in rows if (r.get("source") or "momentum") == "momentum"])]


def _upl_history(position_rows: list[dict]) -> tuple[list[str], dict[str, dict[str, float]]]:
    """Positions tab → (sorted snapshot dates, date → {ticker: unrealised P&L})."""
    snaps: dict[str, dict[str, float]] = defaultdict(dict)
    for p in position_rows:
        d, tk = (p.get("date") or "")[:10], (p.get("ticker") or "").strip().upper()
        if d and tk:
            snaps[d][tk] = fnum(p.get("upl")) or 0.0
    return sorted(snaps), snaps


def wsr_trim_history(dq_rows: list[dict], positions: dict[str, list[dict]]) -> list[PastIdea]:
    """Every WSR trim of a position that was in profit when the trim was written.

    The account's positions snapshot on or before the row's date (within a
    week) says whether the position was up. Trims of losers are a different
    decision and never shown, so they aren't graded here either. A trim
    re-stated day after day — "sell at market" re-issued with each day's
    price — is one idea until it lapses for TRIM_GAP_DAYS.
    """
    hist = {a: _upl_history(rows) for a, rows in positions.items()}
    keep = []
    for r in dq_rows:
        if (r.get("strategy") or "").upper() != "TRIM":
            continue
        if (r.get("source") or "") not in ("wsr_lite", "wsr_full"):
            continue
        e = fnum(r.get("entry"))
        acct = (r.get("account") or "").strip().lower()
        tk = (r.get("ticker") or "").strip().upper()
        d = (r.get("date") or "")[:10]
        if not e or e <= 0 or not tk or not d or acct not in hist:
            continue
        dates, snaps = hist[acct]
        i = bisect.bisect_right(dates, d) - 1
        if i < 0 or (day(d) - day(dates[i])).days > 7:
            continue
        if snaps[dates[i]].get(tk, 0.0) <= 0:
            continue
        keep.append(r)
    return [PastIdea("wsr_trim", tk, d.isoformat(), fnum(r["entry"]), side="sell")
            for tk, d, r in _first_appearances(keep, gap_days=TRIM_GAP_DAYS)]


def grade(source: str, ideas: list[PastIdea], bars: dict[str, Bars], today: str) -> Record:
    """Fill each idea, hold HOLD_DAYS sessions, compare with SPY over the same days.

    Fill: a signal fills at the next session's open. A buy-dip fills on the
    first of the next FILL_WINDOW sessions whose low touches the trigger, at
    min(trigger, open); a trigger already above the last close fills next open.
    A trim mirrors it: the first session whose high reaches the level, at
    max(trigger, open), or next open if the level is already below the close.
    Only completed holds count. Today's partial bar is never used.

    A buy's edge is its return minus SPY's, less COST_PER_SIDE in and out. A
    trim's edge is SPY's minus the stock's, less COST_PER_SIDE on the sale:
    selling was right when the stock went on to lag SPY by more than it cost.
    """
    rec = Record(source)
    spy = bars.get("SPY")
    if spy is None:
        return rec
    days = [d for d in spy.dates if d < today]
    pos = {d: i for i, d in enumerate(days)}
    alphas: list[tuple[str, float]] = []   # (entry week, alpha)
    for idea in ideas:
        b = bars.get(idea.ticker)
        if b is None:
            rec.nodata += 1
            continue
        after = [d for d in days if d > idea.date]
        if not after:
            rec.open += 1
            continue
        fill_day = fill_px = None
        sell = idea.side == "sell"
        if idea.trigger is None:
            fill_day = after[0]
        else:
            n_before = b.upto(after[0])
            prev_close = b.c[n_before - 1] if n_before else None
            if prev_close is not None and (idea.trigger <= prev_close if sell
                                           else idea.trigger >= prev_close):
                fill_day = after[0]
            else:
                for d in after[:FILL_WINDOW]:
                    i = b.idx(d)
                    if i is None:
                        continue
                    if sell and b.h[i] >= idea.trigger:
                        fill_day, fill_px = d, max(idea.trigger, b.o[i])
                        break
                    if not sell and b.l[i] <= idea.trigger:
                        fill_day, fill_px = d, min(idea.trigger, b.o[i])
                        break
                if fill_day is None:
                    if len(after) >= FILL_WINDOW:
                        rec.unfilled += 1
                    else:
                        rec.open += 1
                    continue
        fi = b.idx(fill_day)
        if fi is None:
            continue
        if fill_px is None:
            fill_px = b.o[fi]
        k = pos[fill_day] + HOLD_DAYS
        if k >= len(days):
            rec.open += 1
            continue
        exit_day = days[k]
        xi = b.idx(exit_day)
        si, sx = spy.idx(fill_day), spy.idx(exit_day)
        if xi is None or si is None or sx is None or not fill_px or not spy.o[si]:
            continue
        r_idea = b.total_return(fi, fill_px, xi)
        r_spy = spy.total_return(si, spy.o[si], sx)
        y, w, _ = day(fill_day).isocalendar()
        alphas.append((f"{y}-W{w:02d}", r_spy - r_idea - COST_PER_SIDE if sell
                       else r_idea - r_spy - 2 * COST_PER_SIDE))

    rec.n = len(alphas)
    if not alphas:
        return rec
    a = [x for _, x in alphas]
    rec.beat = sum(x > 0 for x in a)
    rec.mean_alpha = st.mean(a)
    groups: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for wk, x in alphas:
        groups[wk] += x - rec.mean_alpha
        counts[wk] += 1
    rec.clusters = len(groups)
    rec.top_cluster_share = max(counts.values()) / rec.n
    if rec.clusters > 1:
        g = rec.clusters
        se = math.sqrt(g / (g - 1) * sum(v * v for v in groups.values())) / rec.n
        rec.t = rec.mean_alpha / se if se > 0 else None
    return rec


def assign_tier(rec: Record, min_graded: int = 10, min_clusters: int = 4) -> Record:
    """🟢 needs t >= 2 from at least 8 entry weeks, no one week > 40% of the
    record (a single basket must not look like a track record). 🔴 at t <= -2.
    Anything thinner or in between is 🟡 probation."""
    if rec.n < min_graded or rec.clusters < min_clusters or rec.t is None:
        rec.tier, rec.note = "yellow", "too few graded yet"
    elif rec.t >= 2 and rec.clusters >= 8 and rec.top_cluster_share <= 0.40:
        rec.tier = "green"
    elif rec.t <= -2:
        rec.tier = "red"
    else:
        rec.tier = "yellow"
    return rec


def record_line(rec: Record, extra: str = "") -> str:
    head = f"{TIER_EMOJI[rec.tier]} {SOURCE_LABEL.get(rec.source, rec.source)}"
    if rec.n == 0:
        body = "no graded ideas yet"
    elif rec.source in SELL_SOURCES:
        body = (f"{rec.beat}/{rec.n} lagged SPY after the trim and costs · "
                f"trimming {pct(rec.mean_alpha)} vs keeping, per 20d")
    else:
        body = f"{rec.beat}/{rec.n} beat SPY after costs · {pct(rec.mean_alpha)} vs SPY per 20d"
    tail = []
    if rec.near_cut:
        tail.append("near cut")
    if rec.note and rec.n:
        tail.append(rec.note)
    if extra:
        tail.append(extra)
    return f"{head}: {body}" + "".join(f" · {x}" for x in tail)


# ─────────────────────────────────────────────────────────────────────────
# Today's candidates
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class Idea:
    source: str
    ticker: str
    action: str                       # "BUY" | "BUY CALL"
    why: str = ""
    kind: str = "stock"               # "stock" | "ETF" | "option"
    trigger: float | None = None      # buy-dip level (underlying)
    stop: float | None = None         # underlying close below this invalidates
    target: float | None = None
    accounts: tuple[str, ...] = ()    # accounts the source wrote it for
    # Options only
    expiry: str = ""                  # YYYY-MM-DD
    strike: float = 0.0
    limit: float = 0.0                # max premium per share
    mid: float = 0.0
    # Filled by check_live()
    last: float = 0.0
    chg_1d: float = 0.0
    chg_20d: float = 0.0
    status: str = ""
    stop_basis: str = ""              # "20-day low" | "1.5 days' range below entry" | "source stop"
    unit_cost: float = 0.0            # one share, or one contract (×100)
    notes: list[str] = field(default_factory=list)
    sizes: dict = field(default_factory=dict)   # account → (units, one_unit_exception, reason)

    @property
    def is_option(self) -> bool:
        return self.kind == "option"


def _wsr_reason(text: str) -> str:
    """The WSR one-liner leads with price chatter; the reason follows the dash."""
    t = " ".join((text or "").split())
    return t.split(" — ", 1)[1] if " — " in t else t


def live_wsr_dips(dq_rows: list[dict], today: str) -> list[Idea]:
    """Buy-dips the WSR still stands behind: the latest row per (account,
    ticker) must be pending/watching and no older than one weekly cycle.
    A later killed/filled row retires the idea. Rows for the same ticker in
    both books merge into one idea, sized for both."""
    latest: dict[tuple[str, str], dict] = {}
    latest_full: dict[tuple[str, str], dict] = {}
    for r in sorted(dq_rows, key=lambda r: r.get("date", "")):
        if (r.get("strategy") or "").upper() != "BUY_DIP":
            continue
        k = ((r.get("account") or "").strip().lower(), (r.get("ticker") or "").strip().upper())
        if k[1]:
            latest[k] = r
            if r.get("source") == "wsr_full":
                latest_full[k] = r
    cutoff = (day(today) - timedelta(days=WSR_MAX_AGE_DAYS)).isoformat()
    by_ticker: dict[str, list[tuple[dict, dict | None]]] = defaultdict(list)
    for k, r in latest.items():
        if (r.get("status") or "").lower() not in ("pending", "watching"):
            continue
        if r.get("date", "")[:10] < cutoff or (r.get("source") or "") not in ("wsr_lite", "wsr_full"):
            continue
        if not fnum(r.get("entry")):
            continue
        full = latest_full.get(k)
        by_ticker[k[1]].append((r, full if full and full.get("date", "")[:10] >= cutoff else None))
    out = []
    for tk, pairs in by_ticker.items():
        pairs.sort(key=lambda p: p[0].get("date", ""))
        newest = pairs[-1][0]
        # The weekly full WSR states the reason; mid-week lite rows are mostly
        # price updates ("still watching the $100 level"), so prefer the full.
        fulls = [f for _, f in pairs if f]
        why_row = max(fulls, key=lambda r: r.get("date", "")) if fulls else newest
        out.append(Idea(
            source="wsr", ticker=tk, action="BUY",
            trigger=fnum(newest.get("entry")),
            target=fnum(newest.get("target")) or None,
            why=_wsr_reason(why_row.get("thesis_1liner", "")),
            accounts=tuple(sorted({(r.get("account") or "").lower() for r, _ in pairs})),
        ))
    return out


def blocked_sells(dq_rows: list[dict], today: str, upl: dict[tuple[str, str], float],
                  holds: set[tuple[str, str]]) -> list[tuple[str, str]]:
    """Live TRIM/CC rows the never-sell-a-loser rule blocks: the name is on the
    hold_list, or the position is underwater. Returned so the DM can say how
    many it dropped; none of them is ever shown as an idea."""
    from src.hold_list import is_held, is_sell_rec
    latest: dict[tuple[str, str, str], dict] = {}
    for r in sorted(dq_rows, key=lambda r: r.get("date", "")):
        k = ((r.get("account") or "").strip().lower(), (r.get("ticker") or "").strip().upper(),
             (r.get("strategy") or "").upper())
        latest[k] = r
    cutoff = (day(today) - timedelta(days=WSR_MAX_AGE_DAYS)).isoformat()
    out = []
    for (acct, tk, strat), r in latest.items():
        if not is_sell_rec(strat) or (r.get("status") or "").lower() not in ("pending", "watching"):
            continue
        if r.get("date", "")[:10] < cutoff:
            continue
        if is_held(acct, tk, holds) or upl.get((acct, tk), 0.0) < 0:
            out.append((acct, tk))
    return sorted(out)


@dataclass
class Exit:
    """A take-profit trim of one account's position."""
    account: str
    ticker: str
    trigger: float                    # the WSR's trim level (its price, for a sell-now)
    market: bool                      # True: the WSR says sell now; False: sell at the level
    qty: int | None                   # the WSR's share count
    why: str = ""
    # Filled by check_exit()
    held: float = 0.0
    avg_cost: float = 0.0
    last: float = 0.0
    hit_today: bool = False
    status: str = ""
    units: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def sell_px(self) -> float:
        """Market for a sell-now or a level already reached; else the limit."""
        return self.last if self.market or self.last >= self.trigger else self.trigger

    @property
    def proceeds(self) -> float:
        return self.units * self.sell_px

    @property
    def gain(self) -> float:
        return self.units * (self.sell_px - self.avg_cost) if self.avg_cost else 0.0

    @property
    def actionable(self) -> bool:
        """Sell now, at or past the level, or the level traded today."""
        return self.market or self.last >= self.trigger or self.hit_today


def live_wsr_trims(dq_rows: list[dict], today: str, upl: dict[tuple[str, str], float],
                   holds: set[tuple[str, str]]) -> list[Exit]:
    """Trims the WSR still stands behind, on positions in profit: the latest
    TRIM row per (account, ticker) must be pending (sell now) or watching
    (sell at the level) and no older than one weekly cycle. Losers and
    hold-list names belong to blocked_sells — the two never overlap."""
    from src.hold_list import is_held
    latest: dict[tuple[str, str], dict] = {}
    latest_full: dict[tuple[str, str], dict] = {}
    for r in sorted(dq_rows, key=lambda r: r.get("date", "")):
        if (r.get("strategy") or "").upper() != "TRIM":
            continue
        k = ((r.get("account") or "").strip().lower(), (r.get("ticker") or "").strip().upper())
        if k[1]:
            latest[k] = r
            if r.get("source") == "wsr_full":
                latest_full[k] = r
    cutoff = (day(today) - timedelta(days=WSR_MAX_AGE_DAYS)).isoformat()
    out = []
    for (acct, tk), r in latest.items():
        status = (r.get("status") or "").lower()
        if status not in ("pending", "watching"):
            continue
        if r.get("date", "")[:10] < cutoff or (r.get("source") or "") not in ("wsr_lite", "wsr_full"):
            continue
        e = fnum(r.get("entry"))
        if not e or e <= 0:
            continue
        if is_held(acct, tk, holds) or upl.get((acct, tk), 0.0) <= 0:
            continue
        # The weekly full WSR states the reason, but only if it is still the
        # same instruction — a lite row that promoted a trim to "sell now"
        # carries the current reason.
        full = latest_full.get((acct, tk))
        same = full and full.get("date", "")[:10] >= cutoff \
            and (full.get("status") or "").lower() == status \
            and (status == "pending" or fnum(full.get("entry")) == e)
        q = fnum(r.get("qty"))
        out.append(Exit(account=acct, ticker=tk, trigger=e, market=status == "pending",
                        qty=int(q) if q and q > 0 else None,
                        why=_wsr_reason((full if same else r).get("thesis_1liner", ""))))
    return out


def uoa_candidates(rows: list[dict], today: str, max_ideas: int = 1) -> list[Idea]:
    """Long-call ideas from the most recent scan's buyer-initiated, bullish,
    quality >= 80 call flow. One idea per ticker: the expiry with the most
    notional, and within it the strike with the most notional."""
    days = sorted({(r.get("date") or "")[:10] for r in rows if (r.get("date") or "")[:10] <= today})
    if not days:
        return []
    scan = days[-1]
    flow = [r for r in rows if (r.get("date") or "")[:10] == scan]
    bull = [r for r in flow if _is_bullish_q80(r)
            and (r.get("side") or "").upper() == "CALL"
            and (r.get("aggressor") or "").upper() == "BUY_INITIATED"
            and (fnum(r.get("dte")) or 0) >= 7]
    by_tk: dict[str, list[dict]] = defaultdict(list)
    for r in bull:
        by_tk[r["ticker"].strip().upper()].append(r)
    ranked = sorted(by_tk, key=lambda t: -sum(fnum(r.get("notional")) or 0 for r in by_tk[t]))
    when = "today" if scan == today else ("yesterday" if (day(today) - day(scan)).days <= 3
                                           else day(scan).strftime("%-d %b"))
    out = []
    for tk in ranked[:max_ideas]:
        rs = by_tk[tk]
        per_exp: dict[str, float] = defaultdict(float)
        for r in rs:
            per_exp[r["expiry"][:10]] += fnum(r.get("notional")) or 0
        exp = max(per_exp, key=per_exp.get)
        in_exp = [r for r in rs if r["expiry"][:10] == exp]
        pick = max(in_exp, key=lambda r: fnum(r.get("notional")) or 0)
        strikes = sorted({fnum(r.get("strike")) for r in in_exp if fnum(r.get("strike"))})
        quals = sorted({int(fnum(r.get("quality")) or 0) for r in in_exp})
        total = sum(fnum(r.get("notional")) or 0 for r in in_exp)
        k_txt = (f"${strikes[0]:g}–{strikes[-1]:g}" if len(strikes) > 1 else f"${strikes[0]:g}")
        q_txt = f"{quals[0]}–{quals[-1]}" if len(quals) > 1 else f"{quals[0]}"
        why = (f"${total / 1e6:.1f}M of buyer-initiated {day(exp).strftime('%-d %b')} {k_txt} "
               f"calls {when} (quality {q_txt})").replace(".0M", "M")
        against = sum(fnum(r.get("notional")) or 0 for r in flow
                      if (r.get("ticker") or "").strip().upper() == tk
                      and (r.get("bias") or "").upper() == "BEARISH")
        if against >= 0.25 * total:
            why += f"; ${against / 1e6:.1f}M of bearish flow against it".replace(".0M", "M")
        ask = fnum(pick.get("ask")) or 0
        bid = fnum(pick.get("bid")) or 0
        out.append(Idea(source="uoa", ticker=tk, action="BUY CALL", kind="option", why=why,
                        expiry=exp, strike=fnum(pick.get("strike")) or 0,
                        limit=ask, mid=(ask + bid) / 2 if ask and bid else ask))
    return out


def gov_watch(rows: list[dict], today: str) -> dict | None:
    """The most material new gov-contract signal: highest contract value as a
    share of market cap (>= 1%) on the latest signal day, score >= 45."""
    days = sorted({(r.get("date") or "")[:10] for r in rows if (r.get("date") or "")[:10] <= today})
    if not days:
        return None
    cands = [r for r in rows if (r.get("date") or "")[:10] == days[-1]
             and (fnum(r.get("investment_score")) or 0) >= 45
             and (fnum(r.get("contract_pct_mktcap")) or 0) >= 0.01]
    if not cands:
        return None
    r = max(cands, key=lambda r: fnum(r.get("contract_pct_mktcap")) or 0)
    return {"ticker": r["ticker"].strip().upper(), "usd": fnum(r.get("contract_usd")) or 0,
            "pct_mktcap": fnum(r.get("contract_pct_mktcap")) or 0}


def momentum_watch(rows: list[dict], today: str, top: int = 3) -> list[dict]:
    """The latest screen's top names by score, with their own stop."""
    rows = [r for r in rows if (r.get("source") or "momentum") == "momentum"
            and (r.get("date") or "")[:10] <= today]
    days = sorted({r["date"][:10] for r in rows})
    if not days:
        return []
    latest = [r for r in rows if r["date"][:10] == days[-1]]
    latest.sort(key=lambda r: -(fnum(r.get("score")) or 0))
    return [{"ticker": r["ticker"].strip().upper(), "stop": fnum(r.get("stop_price"))}
            for r in latest[:top]]


# ─────────────────────────────────────────────────────────────────────────
# Live re-check
# ─────────────────────────────────────────────────────────────────────────

def _today_bar(b: Bars, today: str) -> tuple[int | None, int]:
    """(index of today's bar or None, count of completed bars before today)."""
    return b.idx(today), b.upto(today)


def twenty_day_low(b: Bars, today: str) -> float | None:
    """Lowest low of the last 20 sessions, today's included. Including today
    matters: a dip-buy that triggers on a fresh 20-day low would otherwise get
    a stop above its own entry and be dropped the moment it fires."""
    ti, n = _today_bar(b, today)
    end = n + (1 if ti is not None else 0)
    lows = b.l[max(0, end - 20):end]
    return min(lows) if lows else None


def atr(b: Bars, today: str, n: int = 14) -> float | None:
    """Average true range of the last n sessions, today's included."""
    ti, k = _today_bar(b, today)
    end = k + (1 if ti is not None else 0)
    trs = [max(b.h[i], b.c[i - 1]) - min(b.l[i], b.c[i - 1]) for i in range(max(1, end - n), end)]
    return st.mean(trs) if trs else None


def dip_stop(b: Bars, today: str, entry: float) -> tuple[float | None, str]:
    """The 20-day low, or 1.5 average daily ranges below the entry if that is
    lower. The second leg keeps the stop under the entry when the buy level
    is itself below the 20-day low (a limit waiting under the market)."""
    low = twenty_day_low(b, today)
    a = atr(b, today)
    floor = entry - 1.5 * a if a else None
    if low is not None and (floor is None or low <= floor):
        return low, "20-day low"
    return floor, "1.5 days' range below entry"


def move_stats(b: Bars, today: str) -> tuple[float, float, float]:
    """(last, 1-day change, 20-day change) using today's bar when present."""
    ti, n = _today_bar(b, today)
    last = b.c[ti] if ti is not None else b.c[n - 1]
    end = n if ti is not None else n - 1
    prev = b.c[end - 1] if end >= 1 else last
    base = b.c[end - 20] if end >= 20 else b.c[0]
    return last, last / prev - 1, last / base - 1


def check_live(idea: Idea, b: Bars | None, today: str) -> str | None:
    """Re-check one idea on live prices. Returns a drop reason, or None and
    fills in last/status/stop/unit_cost."""
    if b is None or not b.dates:
        return "no live price"
    ti, n = _today_bar(b, today)
    if n == 0:
        return "no price history"
    idea.last, idea.chg_1d, idea.chg_20d = move_stats(b, today)
    if idea.stop is not None:                       # the source's own stop
        idea.stop_basis = "source stop"
        if idea.last < idea.stop:
            return stop_note(b, today, idea.chg_1d)
    if idea.is_option:
        if idea.stop is None:
            idea.stop, idea.stop_basis = twenty_day_low(b, today), "20-day low"
        idea.unit_cost = idea.limit * 100
        return None if idea.limit > 0 else "no option quote"
    trig = idea.trigger
    if not trig:
        return "no trigger"
    if trig > 1.5 * idea.last or trig < 0.5 * idea.last:
        return f"trigger {px(trig)} is nowhere near the price {px(idea.last)}"
    if idea.stop is None:
        idea.stop, idea.stop_basis = dip_stop(b, today, min(trig, idea.last))
    prev_close = b.c[n - 1]
    day_low = b.l[ti] if ti is not None else idea.last
    if ti is not None and day_low <= trig < prev_close:
        idea.status = "trigger hit today"
    elif idea.last <= trig:
        idea.status = "below trigger"
    else:
        idea.status = f"{pct(idea.last / trig - 1, 1, sign=False)} above trigger"
    idea.unit_cost = min(trig, idea.last)
    return None


def check_exit(ex: Exit, b: Bars | None, today: str, held: float, avg_cost: float) -> str | None:
    """Re-check one take-profit trim on live prices. Returns a drop reason, or
    None and fills in last/status/units. The share count is the WSR's, capped
    at what the account holds; no count from the WSR means no count here."""
    if held <= 0:
        return "no longer held"
    if b is None or not b.dates:
        return "no live price"
    ti, n = _today_bar(b, today)
    if n == 0:
        return "no price history"
    ex.held, ex.avg_cost = held, avg_cost
    ex.last, _, _ = move_stats(b, today)
    if avg_cost and ex.last <= avg_cost:
        return "now below cost (rule)"
    if not ex.market and (ex.trigger > 1.5 * ex.last or ex.trigger < 0.5 * ex.last):
        return f"trim level {px(ex.trigger)} is nowhere near the price {px(ex.last)}"
    ex.units = int(min(ex.qty, held)) if ex.qty else 0
    ex.hit_today = ti is not None and b.h[ti] >= ex.trigger > ex.last
    if ex.market:
        ex.status = "WSR says sell now"
    elif ex.last >= ex.trigger:
        ex.status = "at the trim level"
    elif ex.hit_today:
        ex.status = "trim level traded today"
    else:
        ex.status = f"{pct(1 - ex.last / ex.trigger, 1, sign=False)} below the trim level"
    return None


@dataclass
class Earnings:
    """One ticker's earnings dates after the cross-check."""
    upcoming: list[str] = field(default_factory=list)    # sorted, today or later
    reported: str = ""       # latest report that has happened
    checked: bool = False    # False: Yahoo had nothing, so these are the Sheet's dates alone

    @property
    def caveat(self) -> str:
        return "" if self.checked else " (date not cross-checked)"


def reconcile_earnings(sheet: list[str], yahoo: list[tuple[str, bool]] | None, today: str) -> Earnings:
    """Cross-check the Sheet's earnings dates against Yahoo's (date, results are
    out) rows. The Sheet keeps old estimates, including a future date for a
    quarter that has already been reported, so with Yahoo rows in hand:

      - a report only counts if Yahoo shows results for it;
      - a Sheet date within STALE_AFTER_REPORT_DAYS of that report is dropped.
        Yahoo's own next date always stays: late filers do report close together;
      - where the two disagree on the next date both stay, so the earlier one
        is what the notes show.

    With no Yahoo rows the Sheet stands, marked unchecked."""
    if not yahoo:
        return Earnings(upcoming=sorted(d for d in sheet if d >= today),
                        reported=max((d for d in sheet if d < today), default=""))
    reported = max((d for d, done in yahoo if done and d <= today), default="")
    ahead = {d for d, done in yahoo if not done and d >= today}
    for d in sheet:
        if d >= today and (not reported or (day(d) - day(reported)).days > STALE_AFTER_REPORT_DAYS):
            ahead.add(d)
    return Earnings(upcoming=sorted(ahead), reported=reported, checked=True)


def exit_earnings_note(ticker: str, earnings: dict[str, Earnings], today: str) -> str:
    e = earnings.get(ticker) or Earnings()
    for d in e.upcoming:
        if (day(d) - day(today)).days <= 14:
            return f"⚠ earnings {day(d).strftime('%a %-d %b')}{e.caveat}"
    return ""


def earnings_note(ticker: str, earnings: dict[str, Earnings], today: str) -> str:
    """Flag a report inside the 20-day hold, or one that just passed."""
    e = earnings.get(ticker) or Earnings()
    t = day(today)
    for d in e.upcoming:
        if (day(d) - t).days <= 28:
            return f"⚠ earnings {day(d).strftime('%a %-d %b')}, inside the 20-day hold{e.caveat}"
    if e.reported and (t - day(e.reported)).days <= 4:
        when = "today" if e.reported == today else day(e.reported).strftime("%-d %b")
        return f"reported {when} — earnings are behind it{e.caveat}"
    return ""


# ─────────────────────────────────────────────────────────────────────────
# Accounts, sizing, budget
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class Account:
    name: str                  # "caspar" | "sarah"
    ccy: str                   # account currency: "USD" | "SGD"
    nlv: float                 # in account currency
    cash: float                # in account currency
    deposit: float = 0.0       # monthly deposit, in deposit_ccy
    deposit_ccy: str = "SGD"
    deposit_landed: bool = False
    weights: dict = field(default_factory=dict)   # ticker → share of NLV
    stale_since: str = ""      # when set, only prices have moved since this date

    @property
    def label(self) -> str:
        return ACCOUNT_LABEL.get(self.name, self.name.title())


def to_usd(amount: float, ccy: str, sgd_per_usd: float) -> float:
    return amount / sgd_per_usd if ccy.upper() == "SGD" else amount


def size_units(size_usd: float, unit_cost: float) -> tuple[int, bool]:
    """Whole units for a dollar size. (units, used the one-unit exception)."""
    if size_usd <= 0 or unit_cost <= 0:
        return 0, False
    n = int(size_usd // unit_cost)
    if n >= 1:
        return n, False
    if unit_cost <= ONE_UNIT_MAX_OVER * size_usd:
        return 1, True
    return 0, False


def size_idea(idea: Idea, tier: str, accounts: list[Account], sgd_per_usd: float) -> None:
    for a in accounts:
        nlv = to_usd(a.nlv, a.ccy, sgd_per_usd)
        units, one = size_units(SIZE_PCT[tier] * nlv, idea.unit_cost)
        reason = ""
        if units == 0 and nlv > 0:
            unit = "contract" if idea.is_option else "share"
            reason = f"one {unit} is {pct(idea.unit_cost / nlv, 1, sign=False)} of {_POSSESSIVE.get(a.name, 'the')} book"
        elif not idea.is_option and nlv > 0:
            after = a.weights.get(idea.ticker, 0.0) + units * idea.unit_cost / nlv
            if after > CONCENTRATION_CAP:
                units, one = 0, False
                reason = f"already {pct(a.weights.get(idea.ticker, 0.0), 0, sign=False)} of the book"
        idea.sizes[a.name] = (units, one, reason)


def deposit_landed(cash_series: list[float], deposit: float) -> bool:
    """A day-over-day cash jump of >= 80% of the deposit this month = it landed.
    `cash_series` is this month's snapshot cash, oldest first, with the last
    snapshot of the previous month prepended."""
    if deposit <= 0:
        return False
    return any(b - a >= 0.8 * deposit for a, b in zip(cash_series, cash_series[1:]))


@dataclass
class Budget:
    account: Account
    cash_usd: float
    deposit_usd: float
    now: list[int] = field(default_factory=list)      # idea numbers that fit cash now
    later: list[int] = field(default_factory=list)    # fit once the deposit lands
    over: list[int] = field(default_factory=list)     # don't fit this month
    cost_now: float = 0.0
    cost_total: float = 0.0


def allocate(numbered: list[tuple[int, Idea]], a: Account, sgd_per_usd: float) -> Budget:
    """Fill ideas in DM order against cash, then cash + the month's deposit."""
    cash = to_usd(a.cash, a.ccy, sgd_per_usd)
    dep = 0.0 if a.deposit_landed else to_usd(a.deposit, a.deposit_ccy, sgd_per_usd)
    bud = Budget(a, cash, dep)
    cum = 0.0
    for num, idea in numbered:
        units = idea.sizes.get(a.name, (0, False, ""))[0]
        if units <= 0:
            continue
        cost = units * idea.unit_cost
        if cum + cost <= cash:
            bud.now.append(num)
            cum += cost
            bud.cost_now = cum
        elif cum + cost <= cash + dep:
            bud.later.append(num)
            cum += cost
        else:
            bud.over.append(num)
    bud.cost_total = cum
    return bud


# ─────────────────────────────────────────────────────────────────────────
# Direction block and stale-book check (shared by both phases)
# ─────────────────────────────────────────────────────────────────────────

def with_premarket(bars: dict[str, Bars], quotes: dict[str, tuple[float, float, float, float]],
                   today: str) -> dict[str, Bars]:
    """Add today's pre-market trading to each ticker as a partial bar, from
    ticker → (open, high, low, last). grade() never reads today's bar, so the
    records can't move, and a thinly traded name with no quote keeps its last
    close and says which session that close is from."""
    out = dict(bars)
    for tk, (o, h, l, c) in quotes.items():
        b = bars.get(tk)
        if b is None or not b.dates or b.dates[-1] >= today or not b.c[-1]:
            continue
        out[tk] = Bars(b.dates + [today], b.o + [o], b.h + [h], b.l + [l], b.c + [c],
                       b.adj + [b.adj[-1] * c / b.c[-1]])
    return out


def session_word(b: Bars, today: str) -> str:
    """'today' when the numbers include today's trading, else the last session's weekday."""
    ti, n = _today_bar(b, today)
    if ti is not None or not n:
        return "today"
    return day(b.dates[n - 1]).strftime("%a")


def stop_note(b: Bars, today: str, chg: float) -> str:
    """Why a name under its stop was dropped. A stock can bounce and still sit
    under a stop that broke in an earlier session."""
    when = session_word(b, today)
    if chg > 0:
        return f"still below its stop, {pct(chg, 0)} {when}"
    return f"stop hit {when}, {pct(chg, 0)}"


def session_change(b: Bars, today: str) -> tuple[str, float]:
    """(weekday, change) of the last completed session."""
    _, n = _today_bar(b, today)
    if n < 2:
        return "", 0.0
    return day(b.dates[n - 1]).strftime("%a"), b.c[n - 1] / b.c[n - 2] - 1


def sma(b: Bars, today: str, n: int) -> float | None:
    """Average of the last n completed closes."""
    _, k = _today_bar(b, today)
    return st.mean(b.c[k - n:k]) if k >= n else None


def direction_record(brief_rows: list[dict], spy: Bars, today: str) -> tuple[int, int]:
    """How often the morning brief's bullish/bearish call got SPY's session
    right: (hits, calls). The brief is written before that day's US session and
    stamped on the same calendar date. Neutral calls and non-trading days don't count."""
    calls = {}
    for r in sorted(brief_rows, key=lambda r: str(r.get("date", ""))):
        d = str(r.get("date", ""))[:10]
        if d and d < today:
            calls[d] = (r.get("sentiment") or "").strip().lower()
    hits = n = 0
    for d, s in calls.items():
        i = spy.idx(d)
        if s not in ("bullish", "bearish") or not i:
            continue
        n += 1
        hits += (s == "bullish") == (spy.c[i] > spy.c[i - 1])
    return hits, n


def direction_lines(brief_rows: list[dict], spy: Bars | None, today: str) -> list[str]:
    """The morning brief's read, with its own record beside it. Direction before
    the open has not been shown to be predictable, so it reads as a posture."""
    rows = [r for r in brief_rows if str(r.get("date", ""))[:10]]
    if not rows:
        return []
    r = max(rows, key=lambda r: str(r["date"]))
    if (day(today) - day(r["date"])).days > 1:
        return [f"No fresh brief: the last is from {day(r['date']).strftime('%-d %b')}."]
    read = (r.get("sentiment") or "no read").strip().lower()
    verdict = " ".join(str(r.get("verdict") or "").split())
    lines = [f"Morning brief: {read}." + (f" {verdict}" if verdict else "")]
    if spy is not None:
        hits, n = direction_record(brief_rows, spy, today)
        if n >= MIN_BRIEF_CALLS:
            lines.append(f"Its bullish/bearish call on SPY's day: {hits}/{n} right. A posture, not a forecast.")
    return lines


def level_lines(bars: dict[str, Bars], gex_rows: list[dict], macro_rows: list[dict], today: str) -> list[str]:
    """SPY and QQQ reference levels, then the volatility and yield readings."""
    lines = []
    short_gamma = False
    for sym in ("SPY", "QQQ"):
        b = bars.get(sym)
        if b is None:
            continue
        parts = [f"{n}d {px(round(v))}" for n in (50, 200) if (v := sma(b, today, n))]
        rows = [r for r in gex_rows if (r.get("symbol") or "").upper() == sym
                and str(r.get("date", ""))[:10] <= today]
        if rows:
            g = max(rows, key=lambda r: str(r["date"]))
            if (day(today) - day(g["date"])).days <= GEX_MAX_AGE_DAYS:
                put_wall, call_wall = fnum(g.get("put_wall")), fnum(g.get("call_wall"))
                if put_wall and call_wall:
                    parts.append(f"dealer walls {px(put_wall)} / {px(call_wall)} ({day(g['date']).strftime('%-d %b')})")
                short_gamma = short_gamma or str(g.get("regime") or "").upper().startswith("NEGATIVE")
        if parts:
            lines.append(f"{sym}: " + " · ".join(parts))
    tail = []
    rows = [r for r in macro_rows if str(r.get("date", ""))[:10]]
    if rows:
        m = max(rows, key=lambda r: str(r["date"]))
        vix, ten = fnum(m.get("vix")), fnum(m.get("us_10y"))
        if vix:
            tail.append(f"VIX {vix:.1f}")
        if ten:
            tail.append(f"10Y {ten:.2f}%")
    if short_gamma:
        tail.append("dealers short gamma, so moves can run further")
    if tail:
        lines.append(" · ".join(tail))
    return lines


def stale_since(cash: list[tuple[str, float]], holdings: list[tuple[str, frozenset]],
                today: str, days: int = STALE_BOOK_DAYS) -> str:
    """The date a book's cash and share counts last changed, if that is at least
    `days` ago, else ''. A live feed moves cash by cents most days, so both
    standing still for that long means only the prices are being refreshed.
    Each series is (date, value), oldest first."""
    def last_change(series):
        if not series:
            return ""
        since, latest = series[-1]
        for d, v in reversed(series):
            if v != latest:
                break
            since = d
        return since
    since = max(last_change(cash), last_change(holdings))
    return since if since and (day(today) - day(since)).days >= days else ""


def book_earnings(account: str, holdings: dict | None, earnings: dict[str, Earnings], today: str,
                  days: int = EARNINGS_AHEAD_DAYS) -> list[str]:
    """Reports due inside `days` for what this book holds, soonest first."""
    t = day(today)
    out = []
    for (acct, tk), (qty, _) in (holdings or {}).items():
        e = earnings.get(tk)
        if acct != account or qty <= 0 or e is None:
            continue
        due = [d for d in e.upcoming if 0 <= (day(d) - t).days <= days]
        if due:
            when = "today" if due[0] == today else day(due[0]).strftime("%a %-d %b")
            out.append((due[0], f"{tk} {when}{e.caveat}"))
    return [txt for _, txt in sorted(out)]


# ─────────────────────────────────────────────────────────────────────────
# Build + render
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class DM:
    text: str
    sized: list[Idea]
    watch: list[str]
    dropped: list[str]
    log_rows: list[dict]
    exits: list[Exit] = field(default_factory=list)
    cards: list[dict] = field(default_factory=list)   # the PWA's copy of this DM, see CARD_COLUMNS
    changes: list[str] = field(default_factory=list)  # what moved since the pre-open plan


# The `daily_ideas` Sheet tab: one row per card the PWA shows. Every string is
# the one the DM text carries, with the Telegram markup removed, so the PWA can
# never disagree with the DM. Sections: `meta` (one, first), then per book a
# `book` row (cash, summary, warning, budget, earnings) followed by its `idea`,
# `exit_note`, `exit` and `watch` rows with `account` set, then `watch` rows with
# no account, which are for both books. The app's idea card keeps the full text
# where the DM's second-book copy points at the first.
CARD_COLUMNS = (
    "date", "sent_at", "section", "num", "ticker", "kind", "action", "source", "tier",
    "status", "plan", "stop", "size", "why", "notes", "record",
    "tape", "lead", "budget", "waiting", "dropped", "account",
    "phase", "direction", "levels", "recheck", "warning",
)
_TAG = re.compile(r"</?[a-z][^>]*>")


def _plain(s: str) -> str:
    """A DM line without its Telegram HTML: tags dropped first, then entities
    unescaped. In that order, because the DM escapes a literal '<' to '&lt;', so
    after the tags are gone any '<' left was text."""
    return html.unescape(_TAG.sub("", s))


def _card(**cols) -> dict:
    return {c: str(cols.get(c, "")) for c in CARD_COLUMNS}


def _tape(spy_chg: float, qqq_chg: float) -> str:
    if spy_chg <= -0.01:
        return "tech-led sell-off" if qqq_chg < spy_chg - 0.0075 else "broad sell-off"
    if spy_chg >= 0.01:
        return "tech-led rally" if qqq_chg > spy_chg + 0.0075 else "broad rally"
    return ""


def _rank(idea: Idea) -> tuple:
    if idea.is_option:
        r = 1
    elif idea.status == "trigger hit today":
        r = 0
    elif idea.status == "below trigger":
        r = 2
    else:
        r = 3
    dist = abs(idea.last / idea.trigger - 1) if idea.trigger and idea.last else 0
    return (r, dist)


def _join_nums(nums: list[int]) -> str:
    return " + ".join(f"#{n}" for n in nums)


def _sgt_clock(now_et) -> str:
    """The same instant on a Singapore clock, when now_et knows its timezone."""
    return now_et.astimezone(SGT).strftime("%H:%M") if now_et.tzinfo else ""


def _cash_headline(a: Account) -> str:
    pre = "S$" if a.ccy == "SGD" else "$"
    cash = f"{short_money(a.cash, pre)} cash"
    if not a.deposit:
        return cash
    if a.deposit_landed:
        return f"{cash} · this month's deposit is in"
    dep = "S$" if a.deposit_ccy == "SGD" else "$"
    return f"{cash} · {short_money(a.deposit, dep)} deposit not in yet"


def _book_size_line(idea: Idea, a: Account, bud: Budget, num: int, sgd_per_usd: float) -> str:
    """One book's size for one idea, and whether its budget covers it."""
    units, one, _ = idea.sizes[a.name]
    unit = ("contract" if units == 1 else "contracts") if idea.is_option else "sh"
    line = f"Size: {units} {unit} ≈ {usd(units * idea.unit_cost)}"
    nlv = to_usd(a.nlv, a.ccy, sgd_per_usd)
    if one and nlv:
        what = "contract" if idea.is_option else "share"
        line += f" (one {what} is {pct(idea.unit_cost / nlv, 1, sign=False)})"
    if num in bud.now:
        return f"{line} · fits cash now"
    if num in bud.later:
        return f"{line} · once the deposit lands"
    return f"{line} · doesn't fit this month"


def plan_changes(prior: list[dict], cards: list[dict]) -> list[str]:
    """What moved between the pre-open plan and the re-check: actions that
    appeared or went, and ones that crossed their level either way."""
    def actions(rows):
        out = {}
        for c in rows:
            if c.get("section") in ("idea", "exit"):
                st_ = c.get("status") or ""
                out[(c.get("account") or "", c.get("ticker") or "", c.get("action") or "")] = (
                    "above trigger" in st_ or "below the trim level" in st_)
        return out
    old, new = actions(prior), actions(cards)
    changes = []
    for k, waiting in new.items():
        who = f"{k[0]} {k[1]} {k[2]}".strip()
        if k not in old:
            changes.append(f"new: {who}")
        elif old[k] != waiting:
            changes.append(f"{who} {'now waiting for its level' if waiting else 'reached its level'}")
    changes += [f"gone: {k[0]} {k[1]} {k[2]}".replace("  ", " ") for k in old if k not in new]
    return changes


def build_dm(*, now_et, today: str, records: dict[str, Record], wsr: list[Idea],
             uoa: list[Idea], gov: dict | None, momentum: list[dict],
             bars: dict[str, Bars], accounts: list[Account], sgd_per_usd: float,
             kinds: dict[str, str], earnings: dict[str, Earnings],
             blocked: list[tuple[str, str]], growth_leg_on: bool = False,
             exits: list[Exit] = (), holdings: dict[tuple[str, str], tuple[float, float]] | None = None,
             phase: str = "open", direction: list[str] = (), levels: list[str] = (),
             prior_cards: list[dict] | None = None) -> DM:
    """Re-check every candidate live, size the survivors, and render the DM.
    `holdings` is (account, ticker) → (shares held, average cost), for exits.
    `phase` is "preopen" (bars carry pre-market as today) or "open". `prior_cards`
    is today's pre-open plan, if one went out, so the re-check can say what moved."""
    dropped: list[str] = []
    watch: list[str] = []
    waiting: list[str] = []
    sized: list[Idea] = []
    red: dict[str, list[Idea]] = {}    # ideas from 🔴 sources: shown, never sized
    book_watch: dict[str, list[str]] = {a.name: [] for a in accounts}
    book_wait: dict[str, list[str]] = {a.name: [] for a in accounts}
    book_trim_wait: dict[str, list[str]] = defaultdict(list)

    def books_for(idea: Idea) -> list[str]:
        """The books the source wrote it for; none named means both."""
        return [a.name for a in accounts if a.name in idea.accounts]

    def nlv_usd(a: Account) -> float:
        return to_usd(a.nlv, a.ccy, sgd_per_usd)

    for idea in wsr + uoa:
        rec = records.get(idea.source) or Record(idea.source)
        why = check_live(idea, bars.get(idea.ticker), today)
        if why:
            dropped.append(f"{idea.ticker} ({why})")
            continue
        if not idea.is_option:
            idea.kind = kinds.get(idea.ticker, "stock")
        if idea.trigger and idea.last > idea.trigger * (1 + NEAR_TRIGGER):
            txt = f"{idea.ticker} {idea.status.replace(' above trigger', '')} above {px(idea.trigger)}"
            for name in books_for(idea):
                book_wait[name].append(txt)
            if not books_for(idea):
                waiting.append(txt)
            continue
        if rec.tier == "red":
            red.setdefault(idea.source, []).append(idea)
            continue
        size_idea(idea, rec.tier, accounts, sgd_per_usd)
        lvl = f"buy-dip {px(idea.trigger)}" if idea.trigger else idea.action.lower()
        for a in accounts:     # a book that can't take it says why, in its own section
            units, _, reason = idea.sizes[a.name]
            if units <= 0 and reason:
                book_watch[a.name].append(f"• {esc(idea.ticker)}: {esc(lvl)}, no size ({esc(reason)}) "
                                          f"{TIER_EMOJI[rec.tier]}")
        if not any(u > 0 for u, _, _ in idea.sizes.values()):
            continue
        note = earnings_note(idea.ticker, earnings, today)
        if note:
            idea.notes.append(note)
        sized.append(idea)

    # A 🔴 source still shows its levels — one line per source, record first.
    for src, ideas in red.items():
        by_book: dict[str, list[str]] = defaultdict(list)
        for i in sorted(ideas, key=_rank):
            where = i.status.replace(" trigger", "") if i.status else ""
            lvl = f"{i.ticker} {px(i.trigger)}" if i.trigger else f"{i.ticker} {i.action.lower()}"
            for name in books_for(i) or list(book_watch):
                by_book[name].append(f"{lvl} ({where})" if where else lvl)
        watch.append(f"• {esc(record_line(records[src]))} — levels only, listed under each book")
        for name, txts in by_book.items():
            book_watch[name].append(f"• {esc(SOURCE_LABEL.get(src, src))} levels, no size: {esc(' · '.join(txts))}")

    sized.sort(key=_rank)
    for idea in sized[MAX_SIZED:]:
        waiting.append(f"{idea.ticker} (over the {MAX_SIZED}-idea cap)")
    sized = sized[:MAX_SIZED]

    # Momentum: graded like everything else, but watch-only while the paper
    # growth leg is switched off (GROWTH_LEG_ENABLED) — its paper record lost
    # to SPY, and the brief's established facts aren't re-litigated here.
    mrec = replace(records.get("momentum") or Record("momentum"))
    if not growth_leg_on:
        mrec.tier = "red"
    shown = False
    for m in momentum:
        b = bars.get(m["ticker"])
        if b is None:
            continue
        last, c1, _ = move_stats(b, today)
        when = session_word(b, today)
        if m["stop"] and last < m["stop"]:
            dropped.append(f"{m['ticker']} ({stop_note(b, today, c1)})")
            continue
        if not shown:
            extra = "" if growth_leg_on else "paper leg off"
            watch.append(f"• {esc(m['ticker'])}: momentum leader, {pct(c1)} {when} to {px(last)}, "
                         f"stop {px(m['stop'])} {esc(record_line(mrec, extra))}")
            shown = True

    if gov:
        grec = records.get("gov") or Record("gov")
        b = bars.get(gov["ticker"])
        move = ""
        if b is not None:
            _, _, c20 = move_stats(b, today)
            move = f", {pct(c20, 0)} in 20d"
        watch.append(f"• {esc(gov['ticker'])}: {big_money(gov['usd'])} federal contracts ≈ {pct(gov['pct_mktcap'], 0, sign=False)} of market cap{move} "
                     f"{esc(record_line(grec, 'no entry/stop yet'))}")

    if waiting:
        watch.append("• Waiting: " + esc(" · ".join(waiting)))

    # Take-profit exits: re-check each live, act on the ones at or near the
    # level, list the rest as waiting.
    trec = records.get("wsr_trim") or Record("wsr_trim")
    sells: list[Exit] = []
    for ex in exits:
        held, cost = (holdings or {}).get((ex.account, ex.ticker), (0.0, 0.0))
        why = check_exit(ex, bars.get(ex.ticker), today, held, cost)
        if why:
            if why != "no longer held":    # sold already: nothing to say
                dropped.append(f"{ex.ticker} trim ({why})")
            continue
        if not ex.actionable and ex.last < ex.trigger * (1 - NEAR_TRIGGER):
            book_trim_wait[ex.account].append(f"{ex.ticker} {ex.status.replace(' below the trim level', '')} "
                                              f"below {px(ex.trigger)}")
            continue
        note = exit_earnings_note(ex.ticker, earnings, today)
        if note:
            ex.notes.append(note)
        sells.append(ex)
    sells.sort(key=lambda e: (not e.actionable, -e.gain))
    for ex in sells[MAX_EXITS:]:
        book_trim_wait[ex.account].append(f"{ex.ticker} (over the {MAX_EXITS}-exit cap)")
    sells = sells[:MAX_EXITS]
    act_sells = sells if trec.tier != "red" else []

    # ── Render ──────────────────────────────────────────────────────────
    spy_b, qqq_b = bars.get("SPY"), bars.get("QQQ")
    clock = now_et.strftime("%H:%M")
    sgt = _sgt_clock(now_et)
    stamp = f"{now_et.strftime('%a %-d %b')} · {clock} ET" + (f" · {sgt} SGT" if sgt else "")
    preopen = phase == "preopen"
    head = f"🌅 <b>Pre-open plan · {stamp}</b>" if preopen else f"📈 <b>Ideas · {stamp}</b>"
    lines: list[str] = [head]

    tape = []
    s1 = q1 = 0.0
    if spy_b is not None:
        s_last, s1, _ = move_stats(spy_b, today)
        tape.append(f"SPY {s_last:,.2f} {pct(s1)}")
    if qqq_b is not None:
        q_last, q1, _ = move_stats(qqq_b, today)
        tape.append(f"QQQ {q_last:,.2f} {pct(q1)}")
    # Before the open, "today" is thin pre-market trading, so the last full
    # session gets its own line and the sell-off/rally label goes on that.
    direction_txts: list[str] = []
    if preopen:
        if spy_b is not None and qqq_b is not None:
            label, s_prev = session_change(spy_b, today)
            _, q_prev = session_change(qqq_b, today)
            prev = f"{label}: SPY {pct(s_prev)} · QQQ {pct(q_prev)}"
            t = _tape(s_prev, q_prev)
            direction_txts.append(prev + (f" · {t}" if t else ""))
            if tape:
                tape[-1] += f" pre-market, vs {label} close"
    elif spy_b is not None and qqq_b is not None:
        t = _tape(s1, q1)
        if t:
            tape.append(t)
    tape_txt = " · ".join(tape)
    if tape:
        lines.append(tape_txt)
    direction_txts += list(direction)
    lines.extend(esc(d) for d in direction_txts)
    level_txts = list(levels)
    lines.extend(esc(x) for x in level_txts)

    tiers_used = sorted({records.get(i.source, Record(i.source)).tier for i in sized},
                        key=lambda t: -SIZE_PCT[t])
    lead_txt = ""
    if sized:
        sizes = []
        for t in tiers_used:
            amt = " · ".join(f"{a.label} {usd(SIZE_PCT[t] * nlv_usd(a))}" for a in accounts)
            sizes.append(f"{SIZE_PCT[t]:.0%} = {amt}")
        if tiers_used == ["yellow"] and not any(r.tier == "green" for r in records.values()):
            lead = "All at probation size, 2% of the account: no source has beaten SPY yet. "
        else:
            lead = "🟢 sources at 5% of the account, 🟡 at 2%. "
        lead_txt = f"<i>{esc(lead + '. '.join(sizes))}.</i>"
        lines.append(lead_txt)
    else:
        lines.append("<i>No buy cleared the live check with a size today.</i>")
    lines.append("")

    sent_at = now_et.strftime("%Y-%m-%dT%H:%M")

    def card(**cols) -> dict:
        return _card(date=today, sent_at=sent_at, phase=phase, **cols)

    log_rows: list[dict] = []
    book_cards: list[dict] = []
    numbered = list(enumerate(sized, 1))
    exit_nums = {id(e): k for k, e in enumerate(act_sells, 1)}
    printed: dict[int, str] = {}    # idea number → the book whose section carries it in full
    month = now_et.strftime("%b")

    for num, idea in numbered:
        rec = records.get(idea.source) or Record(idea.source)
        log_rows.append({
            "date": today, "sent_at": sent_at, "num": num,
            "source": idea.source, "tier": rec.tier, "ticker": idea.ticker,
            "kind": "option" if idea.is_option else idea.kind,
            "action": idea.action, "trigger": idea.trigger or "", "limit": idea.limit or "",
            "expiry": idea.expiry, "strike": idea.strike or "", "last": round(idea.last, 4),
            "stop": round(idea.stop, 4) if idea.stop else "", "target": idea.target or "",
            "status": idea.status,
        })

    for a in accounts:
        bud = allocate(numbered, a, sgd_per_usd)
        mine = [(n, i) for n, i in numbered if i.sizes.get(a.name, (0, False, ""))[0] > 0]
        my_sells = [e for e in act_sells if e.account == a.name]
        my_levels = [e for e in sells if e.account == a.name] if trec.tier == "red" else []

        counts = []
        if mine:
            counts.append(f"{len(mine)} buy{'s' if len(mine) != 1 else ''}")
        if my_sells:
            counts.append(f"{len(my_sells)} sell{'s' if len(my_sells) != 1 else ''}")
        status_txt = " · ".join(counts) or "No action"
        cash_txt = _cash_headline(a)
        warn_txt = (f"⚠ Cash and share counts unchanged since {day(a.stale_since).strftime('%-d %b')}: "
                    f"check against IBKR before acting.") if a.stale_since else ""
        lines.append(f"<b>👤 {esc(a.label)}</b> — {esc(status_txt)}")
        lines.append(esc(cash_txt))
        if warn_txt:
            lines.append(f"<b>{esc(warn_txt)}</b>")
        book_row_at = len(book_cards)
        book_cards.append({})      # filled once the rest of the section is known

        for num, idea in mine:
            rec = records.get(idea.source) or Record(idea.source)
            kind = "option" if idea.is_option else idea.kind
            status = f" — {esc(idea.status)}" if idea.status else ""
            lines.append(f"<b>{num} · {esc(idea.ticker)} · {kind} · {esc(idea.action)}</b>{status}")
            who = f"{esc(idea.ticker)} close" if idea.is_option else "close"
            ref = idea.last if idea.is_option else idea.unit_cost   # distance from the entry
            stop_txt = (f"Stop: {who} &lt; {px(idea.stop)} ({esc(idea.stop_basis)}, {pct(idea.stop / ref - 1)})"
                        if idea.stop else "Stop: none (no 20-day history)")
            if idea.is_option:
                exp = day(idea.expiry).strftime("%-d %b")
                mid = f" (mid {prem(idea.mid)})" if idea.mid else ""
                plan_txt = f"Buy 1× {exp} ${idea.strike:g}C ≤ {prem(idea.limit)}{mid}"
                be = idea.strike + idea.limit
                stop_line = (f"{stop_txt} · max loss {usd(idea.unit_cost)} per contract · "
                             f"breakeven {px(be)} ({pct(be / idea.last - 1)})")
                lines.extend([plan_txt, stop_line])
            else:
                plan_txt = f"Entry ≤ {px(idea.trigger)} (now {px(idea.last)})"
                tgt = f" · Target {px(idea.target)} ({pct(idea.target / idea.unit_cost - 1, 0)})" \
                    if idea.target and idea.target > idea.unit_cost else ""
                lines.extend([plan_txt, stop_txt + tgt])
                stop_line = stop_txt
                plan_txt += tgt
            size_txt = esc(_book_size_line(idea, a, bud, num, sgd_per_usd))
            lines.append(size_txt)
            why = idea.why
            if idea.source == "uoa" and idea.chg_20d <= -0.05:
                why += f", with {idea.ticker} {pct(idea.chg_20d, 0)} in 20 days"
            prefix = "Why (WSR): " if idea.source == "wsr" else "Why: "
            why_txt = prefix + esc(why.rstrip(".") + ".") if why else ""
            note_txts = [esc(n) for n in idea.notes]
            rec_txt = esc(record_line(rec))
            # The second book's copy points at the first, to fit one message;
            # the app has the room, so its card always carries the full text.
            if num in printed:
                lines.append(f"Why and record: as #{num} under {esc(printed[num])}.")
            else:
                printed[num] = a.label
                if why_txt:
                    lines.append(why_txt)
                lines.extend(note_txts)
                lines.append(rec_txt)
            lines.append("")
            book_cards.append(card(
                section="idea", num=num, ticker=idea.ticker, kind=kind, action=idea.action,
                source=idea.source, tier=rec.tier, status=idea.status, plan=_plain(plan_txt),
                stop=_plain(stop_line), size=_plain(size_txt), why=_plain(why_txt),
                notes=" | ".join(_plain(n) for n in note_txts), record=_plain(rec_txt),
                account=a.label))

        wait_trims = book_trim_wait.get(a.name, [])
        if my_sells or my_levels or wait_trims:
            lines.append("<b>Take profits</b>")
            lines.append(f"<i>{esc(record_line(trec))}</i>")
        if my_levels:       # trims have cost money: levels only
            levels_txt = "levels only: " + esc(" · ".join(
                f"{e.ticker} " + ("sell now" if e.market else px(e.trigger)) for e in my_levels))
            lines.append("• " + levels_txt)
            book_cards.append(card(section="exit_note", source="wsr_trim", tier=trec.tier,
                                   plan=_plain(levels_txt), record=_plain(esc(record_line(trec))),
                                   account=a.label))
        for ex in my_sells:
            k = exit_nums[id(ex)]
            lines.append(f"<b>S{k} · {esc(ex.ticker)} · SELL</b> — {esc(ex.status)}")
            held = f"{ex.held:g}"
            whose = _POSSESSIVE.get(ex.account, "the")
            sell_txt = locks_txt = ""
            if ex.units:
                how = "at market" if ex.market or ex.last >= ex.trigger else f"with a limit at {px(ex.trigger)}"
                was = f"; WSR's price {px(ex.trigger)}" if ex.market and abs(ex.last / ex.trigger - 1) >= 0.01 else ""
                sell_txt = esc(f"Sell {ex.units} of {whose} {held} sh {how} (now {px(ex.last)}{was}) "
                               f"≈ {usd(ex.proceeds)}")
                lines.append(sell_txt)
                if ex.avg_cost:
                    locks_txt = esc(f"Locks ≈ +{usd(ex.gain)}: {pct(ex.sell_px / ex.avg_cost - 1, 0)} over "
                                    f"the {px(ex.avg_cost)} cost")
                    lines.append(locks_txt)
            else:
                sell_txt = esc(f"WSR gave no share count — {whose} {held} sh, now {px(ex.last)}")
                lines.append(sell_txt)
            why_txt = ""
            if ex.why:
                why_txt = "Why (WSR): " + esc(ex.why.rstrip(".") + ".")
                lines.append(why_txt)
            note_txts = [esc(n) for n in ex.notes]
            lines.extend(note_txts)
            lines.append("")
            book_cards.append(card(
                section="exit", num=f"S{k}", ticker=ex.ticker, kind="stock", action="SELL",
                source="wsr_trim", tier=trec.tier, status=ex.status, plan=_plain(sell_txt),
                size=_plain(locks_txt), why=_plain(why_txt),
                notes=" | ".join(_plain(n) for n in note_txts),
                record=_plain(esc(record_line(trec))), account=a.label))
            log_rows.append({
                "date": today, "sent_at": sent_at, "num": f"S{k}",
                "source": "wsr_trim", "tier": trec.tier, "ticker": ex.ticker, "kind": "stock",
                "action": "SELL", "trigger": ex.trigger, "last": round(ex.last, 4),
                "status": ex.status, "account": ex.account, "units": ex.units,
            })

        budget_txt = ""
        parts = []
        if bud.now:
            parts.append(f"{_join_nums(bud.now)} now")
        if bud.later:
            parts.append(f"{_join_nums(bud.later)} once the deposit lands")
        if bud.over:
            parts.append(f"{_join_nums(bud.over)} {'doesn' if len(bud.over) == 1 else 'don'}'t fit this month")
        if parts:
            total = f" ({short_money(bud.cost_total)} total)" if bud.cost_total else ""
            budget_txt = f"{month} budget: {', '.join(parts)}{total}"
        frees = [(exit_nums[id(e)], e) for e in my_sells if e.units]
        if frees:
            verb = "frees" if len(frees) == 1 else "free"
            freed = (f"{' + '.join(f'S{k}' for k, _ in frees)} {verb} ≈ "
                     f"{short_money(sum(e.proceeds for _, e in frees))}")
            budget_txt = f"{budget_txt} · {freed}" if budget_txt else freed
        if budget_txt:
            lines.append(esc(budget_txt))

        earn_txts = book_earnings(a.name, holdings, earnings, today)
        earn_txt = "Earnings: " + " · ".join(earn_txts) if earn_txts else ""
        if earn_txt:
            lines.append(esc(earn_txt))
        wait_txt = " · ".join(wait_trims)
        if wait_txt:
            lines.append("• Waiting to trim: " + esc(wait_txt))
        if book_wait[a.name]:
            lines.append("• Waiting: " + esc(" · ".join(book_wait[a.name])))
        for w in book_watch[a.name]:
            lines.append(w)
        n_blocked = sum(1 for acct, _ in blocked if acct == a.name)
        held_txt = (f"{n_blocked} trim{'s' if n_blocked != 1 else ''} of underwater holdings "
                    f"skipped (rule)") if n_blocked else ""
        if held_txt:
            lines.append(esc(held_txt))
        lines.append("")

        all_wait = " · ".join(wait_trims + book_wait[a.name])
        book_cards[book_row_at] = card(
            section="book", account=a.label, plan=cash_txt, status=status_txt, warning=warn_txt,
            budget=budget_txt, notes=earn_txt, waiting=all_wait, dropped=held_txt)
        book_cards.extend(card(section="watch", num=f"{a.label[0]}{k}", plan=_plain(w).removeprefix("• "),
                               account=a.label)
                          for k, w in enumerate(book_watch[a.name], 1))

    if watch:
        lines.append("<b>Both books — watch, no size</b>")
        lines.extend(watch)
        lines.append("")

    recheck_txt = ""
    if preopen:
        check = now_et.replace(hour=RECHECK_ET[0], minute=RECHECK_ET[1])
        check_sgt = _sgt_clock(check)
        recheck_txt = (f"Re-check {check.strftime('%H:%M')} ET" + (f" · {check_sgt} SGT" if check_sgt else "")
                       + " on live prices")
        lines.append(f"<i>{esc(recheck_txt)}.</i>")
    if dropped:
        lines.append("Dropped: " + esc(" · ".join(dropped)))

    # The PWA's copy: one meta row, then each book's rows, then the shared watch.
    cards = [card(section="meta", tape=_plain(tape_txt), lead=_plain(lead_txt),
                  direction=" | ".join(direction_txts), levels=" | ".join(level_txts),
                  recheck=recheck_txt, dropped=" · ".join(dropped))]
    cards += book_cards
    cards += [card(section="watch", num=f"W{k}", plan=_plain(w).removeprefix("• "))
              for k, w in enumerate(watch, 1)]

    # The re-check after a pre-open plan only says what moved: on a quiet day
    # the same list twice is noise. The app still gets the full fresh list.
    changes: list[str] = []
    if prior_cards:
        changes = plan_changes(prior_cards, cards)
        was = (prior_cards[0].get("sent_at") or "")[11:16]
        since = f"the {was} ET plan" if was else "the pre-open plan"
        if not changes:
            lines = [f"✅ <b>Re-check · {stamp}</b>", tape_txt, f"Plan unchanged since {since}."]
        else:
            lines.insert(1, f"<b>Changed since {esc(since)}:</b> {esc(' · '.join(changes))}")

    text = "\n".join(lines).strip()
    if len(text) > TELEGRAM_LIMIT:   # cut at a line break so no HTML tag is split
        text = text[:TELEGRAM_LIMIT - 12].rsplit("\n", 1)[0] + "\n…(trimmed)"

    return DM(text=text, sized=sized, watch=watch, dropped=dropped, log_rows=log_rows,
              exits=act_sells, cards=cards, changes=changes)
