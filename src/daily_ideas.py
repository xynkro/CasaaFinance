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
  - Both books in one DM, every size labelled by account. It names account
    cash, so it only ever goes to the personal DM lane, which fails closed.
  - Sent ~15 min after the US open, after re-checking every idea on live
    prices, so an idea whose stop broke this morning never reaches the DM.
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
import statistics as st
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

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
            return f"stop hit today, {pct(idea.chg_1d, 0)}"
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


def _size_line(idea: Idea, accounts: list[Account], sgd_per_usd: float) -> str:
    """Accounts the source wrote the idea for come first."""
    order = sorted(accounts, key=lambda a: (a.name not in idea.accounts, a.name))
    parts = []
    for a in order:
        units, one, reason = idea.sizes.get(a.name, (0, False, ""))
        if units <= 0:
            parts.append(f"{a.label} none" + (f" ({reason})" if reason else ""))
            continue
        unit = ("contract" if units == 1 else "contracts") if idea.is_option else "sh"
        part = f"{a.label} {units} {unit} ≈ {usd(units * idea.unit_cost)}"
        nlv = to_usd(a.nlv, a.ccy, sgd_per_usd)
        if one and nlv:
            what = "contract" if idea.is_option else "share"
            part += f" (one {what} is {pct(idea.unit_cost / nlv, 1, sign=False)})"
        parts.append(part)
    return "Size: " + " · ".join(parts)


def build_dm(*, now_et, today: str, records: dict[str, Record], wsr: list[Idea],
             uoa: list[Idea], gov: dict | None, momentum: list[dict],
             bars: dict[str, Bars], accounts: list[Account], sgd_per_usd: float,
             kinds: dict[str, str], earnings: dict[str, Earnings],
             blocked: list[tuple[str, str]], growth_leg_on: bool = False,
             exits: list[Exit] = (), holdings: dict[tuple[str, str], tuple[float, float]] | None = None) -> DM:
    """Re-check every candidate live, size the survivors, and render the DM.
    `holdings` is (account, ticker) → (shares held, average cost), for exits."""
    dropped: list[str] = []
    watch: list[str] = []
    waiting: list[str] = []
    sized: list[Idea] = []
    red: dict[str, list[Idea]] = {}    # ideas from 🔴 sources: shown, never sized

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
            waiting.append(f"{idea.ticker} {idea.status.replace(' above trigger', '')} above {px(idea.trigger)}")
            continue
        if rec.tier == "red":
            red.setdefault(idea.source, []).append(idea)
            continue
        size_idea(idea, rec.tier, accounts, sgd_per_usd)
        if not any(u > 0 for u, _, _ in idea.sizes.values()):
            reasons = [f"{a.label}: {idea.sizes[a.name][2]}" for a in accounts if idea.sizes[a.name][2]]
            lvl = f"buy-dip {px(idea.trigger)}" if idea.trigger else idea.action.lower()
            watch.append(f"• {esc(idea.ticker)}: {esc(lvl)}, no size ({esc('; '.join(reasons))}) "
                         f"{TIER_EMOJI[rec.tier]}")
            continue
        note = earnings_note(idea.ticker, earnings, today)
        if note:
            idea.notes.append(note)
        sized.append(idea)

    # A 🔴 source still shows its levels — one line per source, record first.
    for src, ideas in red.items():
        levels = []
        for i in sorted(ideas, key=_rank):
            where = i.status.replace(" trigger", "") if i.status else ""
            lvl = f"{i.ticker} {px(i.trigger)}" if i.trigger else f"{i.ticker} {i.action.lower()}"
            levels.append(f"{lvl} ({where})" if where else lvl)
        watch.append(f"• {esc(record_line(records[src]))} — levels only: {esc(' · '.join(levels))}")

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
        if m["stop"] and last < m["stop"]:
            dropped.append(f"{m['ticker']} (stop hit today, {pct(c1, 0)})")
            continue
        if not shown:
            extra = "" if growth_leg_on else "paper leg off"
            watch.append(f"• {esc(m['ticker'])}: momentum leader, {pct(c1)} today to {px(last)}, "
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
    trim_wait: list[str] = []
    for ex in exits:
        held, cost = (holdings or {}).get((ex.account, ex.ticker), (0.0, 0.0))
        why = check_exit(ex, bars.get(ex.ticker), today, held, cost)
        if why:
            if why != "no longer held":    # sold already: nothing to say
                dropped.append(f"{ex.ticker} trim ({why})")
            continue
        if not ex.actionable and ex.last < ex.trigger * (1 - NEAR_TRIGGER):
            trim_wait.append(f"{ex.ticker} {ex.status.replace(' below the trim level', '')} "
                             f"below {px(ex.trigger)}")
            continue
        note = exit_earnings_note(ex.ticker, earnings, today)
        if note:
            ex.notes.append(note)
        sells.append(ex)
    sells.sort(key=lambda e: (not e.actionable, -e.gain))
    for ex in sells[MAX_EXITS:]:
        trim_wait.append(f"{ex.ticker} (over the {MAX_EXITS}-exit cap)")
    sells = sells[:MAX_EXITS]
    act_sells = sells if trec.tier != "red" else []

    if blocked:
        dropped.insert(0, f"{len(blocked)} trim{'s' if len(blocked) != 1 else ''} of underwater "
                          f"holdings (rule)")

    # ── Render ──────────────────────────────────────────────────────────
    lines: list[str] = []
    spy_b, qqq_b = bars.get("SPY"), bars.get("QQQ")
    head = f"📈 <b>Ideas · {now_et.strftime('%a %-d %b · %H:%M')} ET</b>"
    lines.append(head)
    tape = []
    if spy_b is not None:
        s_last, s1, _ = move_stats(spy_b, today)
        tape.append(f"SPY {s_last:,.2f} {pct(s1)}")
    if qqq_b is not None:
        q_last, q1, _ = move_stats(qqq_b, today)
        tape.append(f"QQQ {q_last:,.2f} {pct(q1)}")
        if spy_b is not None:
            t = _tape(s1, q1)
            if t:
                tape.append(t)
    if tape:
        lines.append(" · ".join(tape))

    tiers_used = sorted({records.get(i.source, Record(i.source)).tier for i in sized},
                        key=lambda t: -SIZE_PCT[t])
    if sized:
        sizes = []
        for t in tiers_used:
            amt = " · ".join(f"{a.label} {usd(SIZE_PCT[t] * nlv_usd(a))}" for a in accounts)
            sizes.append(f"{SIZE_PCT[t]:.0%} = {amt}")
        if tiers_used == ["yellow"] and not any(r.tier == "green" for r in records.values()):
            lead = "All at probation size, 2% of the account: no source has beaten SPY yet. "
        else:
            lead = "🟢 sources at 5% of the account, 🟡 at 2%. "
        lines.append(f"<i>{esc(lead + '. '.join(sizes))}.</i>")
    lines.append("")

    log_rows = []
    for num, idea in enumerate(sized, 1):
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
            lines.append(f"Buy 1× {exp} ${idea.strike:g}C ≤ {prem(idea.limit)}{mid}")
            be = idea.strike + idea.limit
            lines.append(f"{stop_txt} · max loss {usd(idea.unit_cost)} per contract · "
                         f"breakeven {px(be)} ({pct(be / idea.last - 1)})")
        else:
            lines.append(f"Entry ≤ {px(idea.trigger)} (now {px(idea.last)})")
            tgt = f" · Target {px(idea.target)} ({pct(idea.target / idea.unit_cost - 1, 0)})" \
                if idea.target and idea.target > idea.unit_cost else ""
            lines.append(stop_txt + tgt)
        lines.append(esc(_size_line(idea, accounts, sgd_per_usd)))
        why = idea.why
        if idea.source == "uoa" and idea.chg_20d <= -0.05:
            why += f", with {idea.ticker} {pct(idea.chg_20d, 0)} in 20 days"
        prefix = "Why (WSR): " if idea.source == "wsr" else "Why: "
        if why:
            lines.append(prefix + esc(why.rstrip(".") + "."))
        for n in idea.notes:
            lines.append(esc(n))
        lines.append(esc(record_line(rec)))
        lines.append("")
        log_rows.append({
            "date": today, "sent_at": now_et.strftime("%Y-%m-%dT%H:%M"), "num": num,
            "source": idea.source, "tier": rec.tier, "ticker": idea.ticker, "kind": kind,
            "action": idea.action, "trigger": idea.trigger or "", "limit": idea.limit or "",
            "expiry": idea.expiry, "strike": idea.strike or "", "last": round(idea.last, 4),
            "stop": round(idea.stop, 4) if idea.stop else "", "target": idea.target or "",
            "status": idea.status,
        })

    if not sized:
        lines.append("<i>No idea cleared the live check with a size today.</i>")
        lines.append("")

    if sells or trim_wait:
        lines.append("<b>Take profits</b>")
        lines.append(f"<i>{esc(record_line(trec))}</i>")
        if trec.tier == "red" and sells:   # trims have cost money: levels only
            levels = [f"{e.ticker} " + ("sell now" if e.market else px(e.trigger))
                      + f" ({ACCOUNT_LABEL.get(e.account, e.account)})" for e in sells]
            lines.append("• levels only: " + esc(" · ".join(levels)))
        for k, ex in enumerate(act_sells, 1):
            who = ACCOUNT_LABEL.get(ex.account, ex.account.title())
            lines.append(f"<b>S{k} · {esc(ex.ticker)} · {who} · SELL</b> — {esc(ex.status)}")
            held = f"{ex.held:g}"
            whose = _POSSESSIVE.get(ex.account, "the")
            if ex.units:
                how = "at market" if ex.market or ex.last >= ex.trigger else f"with a limit at {px(ex.trigger)}"
                was = f"; WSR's price {px(ex.trigger)}" if ex.market and abs(ex.last / ex.trigger - 1) >= 0.01 else ""
                lines.append(esc(f"Sell {ex.units} of {whose} {held} sh {how} (now {px(ex.last)}{was}) "
                                 f"≈ {usd(ex.proceeds)}"))
                if ex.avg_cost:
                    lines.append(esc(f"Locks ≈ +{usd(ex.gain)}: {pct(ex.sell_px / ex.avg_cost - 1, 0)} over "
                                     f"the {px(ex.avg_cost)} cost"))
            else:
                lines.append(esc(f"WSR gave no share count — {whose} {held} sh, now {px(ex.last)}"))
            if ex.why:
                lines.append("Why (WSR): " + esc(ex.why.rstrip(".") + "."))
            for n in ex.notes:
                lines.append(esc(n))
            lines.append("")
        if trim_wait:
            lines.append("• Waiting to trim: " + esc(" · ".join(trim_wait)))
            lines.append("")
        for k, ex in enumerate(act_sells, 1):
            log_rows.append({
                "date": today, "sent_at": now_et.strftime("%Y-%m-%dT%H:%M"), "num": f"S{k}",
                "source": "wsr_trim", "tier": trec.tier, "ticker": ex.ticker, "kind": "stock",
                "action": "SELL", "trigger": ex.trigger, "last": round(ex.last, 4),
                "status": ex.status, "account": ex.account, "units": ex.units,
            })

    if watch:
        lines.append("<b>Watch — no size</b>")
        lines.extend(watch)
        lines.append("")

    if sized:
        numbered = list(enumerate(sized, 1))
        month = now_et.strftime("%b")
        lines.append(f"{month} budget (cash + deposit):")
        for a in accounts:
            bud = allocate(numbered, a, sgd_per_usd)
            pre = "S$" if a.ccy == "SGD" else "$"
            cash_txt = short_money(a.cash, pre)
            if a.deposit and not a.deposit_landed:
                dep_pre = "S$" if a.deposit_ccy == "SGD" else "$"
                head = (f"{cash_txt} + {short_money(a.deposit, dep_pre)} ≈ "
                        f"{short_money(bud.cash_usd + bud.deposit_usd)}")
            elif a.deposit:
                head = f"{short_money(bud.cash_usd)} cash (this month's deposit is in)"
            else:
                head = f"{short_money(bud.cash_usd)} cash (no deposit on file)"
            parts = []
            if bud.now:
                parts.append(f"{_join_nums(bud.now)} now")
            if bud.later:
                parts.append(f"{_join_nums(bud.later)} once the deposit lands")
            if bud.over:
                verb = "doesn't" if len(bud.over) == 1 else "don't"
                parts.append(f"{_join_nums(bud.over)} {verb} fit this month")
            if not parts:
                parts.append("nothing sized for this book")
            tot = f" ({short_money(bud.cost_total)} total)" if bud.cost_total else ""
            mine = [(k, e) for k, e in enumerate(act_sells, 1) if e.account == a.name and e.units]
            if mine:
                verb = "frees" if len(mine) == 1 else "free"
                tot += (f" · {' + '.join(f'S{k}' for k, _ in mine)} {verb} ≈ "
                        f"{short_money(sum(e.proceeds for _, e in mine))}")
            lines.append(f"• {a.label} {esc(head)} → {', '.join(parts)}{tot}")

    if dropped:
        lines.append("Dropped: " + esc(" · ".join(dropped)))

    text = "\n".join(lines).strip()
    if len(text) > TELEGRAM_LIMIT:   # cut at a line break so no HTML tag is split
        text = text[:TELEGRAM_LIMIT - 12].rsplit("\n", 1)[0] + "\n…(trimmed)"
    return DM(text=text, sized=sized, watch=watch, dropped=dropped, log_rows=log_rows,
              exits=act_sells)
