#!/usr/bin/env python3
"""
Daily ideas DM — the I/O around src/daily_ideas.py.

Reads the Sheet, grades every idea source vs SPY, re-checks today's candidates
on live prices, sizes them for each book, adds the WSR's take-profit trims on
positions in profit (graded from the seller's side), and sends one message to the
personal DM lane (never the group: it names account cash). The same strings the
DM carries go to the `daily_ideas` tab (one row per card) for the PWA's Home page,
so the app and the DM cannot disagree; the workflow then starts the Firestore
mirror, whose own schedule runs hours late.

TWO SENDS A DAY
  preopen  08:00-09:29 ET: the plan, on pre-market prices, with a direction block.
           Writes the app's rows but not the ledger: it is a preview, not a graded list.
  open     09:40-11:30 ET: the re-check on live prices. Logged to `ideas_log`, the
           once-a-day dedup ledger and the record the DM will be graded on later.
           If a plan went out, the message only says what changed.

SCHEDULE
  deploy/vm/casaa_dispatch.py on the GCP VM starts this at 08:45 and 09:47 ET,
  because GitHub's cron runs land hours late. The workflow's cron stays as a
  backstop: a run landing in a window sends if nothing has, and one landing after
  the window warns that the list never went out, so a dead timer can't stay silent.

USAGE
  python scripts/daily_ideas_dm.py --dry                 # live data, print only
  python scripts/daily_ideas_dm.py --dry --phase preopen # the plan, whatever the clock says
  python scripts/daily_ideas_dm.py --fixture fixtures/daily_ideas   # offline, print only
  python scripts/daily_ideas_dm.py                       # send (inside a window)
  python scripts/daily_ideas_dm.py --force               # send outside the window / resend
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import daily_ideas as di  # noqa: E402
from src.hold_list import hold_key  # noqa: E402

log = logging.getLogger("daily_ideas_dm")
ET = ZoneInfo("America/New_York")
PREOPEN_WINDOW = (time(8, 0), time(9, 29))
WINDOW = (time(9, 40), time(11, 30))
MARKET_OPEN = time(9, 30)
SMA_HISTORY_DAYS = 320       # calendar days, enough for a 200-day average

TABS = [
    "decision_queue", "uoa_alerts", "gov_confluence_signals", "screen_candidates",
    "snapshot_caspar", "snapshot_sarah", "positions_caspar", "positions_sarah",
    "hold_list", "monthly_deposits", "earnings_calendar", "ideas_log",
    "daily_brief_latest", "gex_regime", "macro", "daily_ideas",
]
LOG_TAB = "ideas_log"
LOG_HEADERS = ["date", "sent_at", "num", "source", "tier", "ticker", "kind", "action",
               "trigger", "limit", "expiry", "strike", "last", "stop", "target", "status",
               "account", "units"]

# The PWA's copy of the DM: one row per card, replaced per day on a resend.
CARD_TAB = "daily_ideas"
CARD_HEADERS = list(di.CARD_COLUMNS)

# Account currency and the snapshot columns that hold net liq and cash.
ACCOUNT_SPECS = {
    "caspar": ("USD", "net_liq_usd", "cash"),
    "sarah": ("SGD", "net_liq_sgd", "cash_sgd"),
}


# ─────────────────────────────────────────────────────────────────────────
# Inputs
# ─────────────────────────────────────────────────────────────────────────

def _records(values: list[list[str]]) -> list[dict]:
    if not values:
        return []
    hdr = [h.strip() for h in values[0]]
    return [dict(zip(hdr, r + [""] * (len(hdr) - len(r)))) for r in values[1:]]


def load_tabs_sheet() -> dict[str, list[dict]]:
    from src import sheets as sh
    ss = sh._open_sheet(sh.authenticate())
    out: dict[str, list[dict]] = {}
    for t in TABS:
        try:
            out[t] = _records(ss.worksheet(t).get_all_values())
        except Exception as e:  # missing tab = empty; every reader fails soft
            log.info("tab %s unreadable (%s) — treated as empty", t, e)
            out[t] = []
    return out


def load_tabs_dir(d: Path) -> dict[str, list[dict]]:
    out = {}
    for t in TABS:
        p = d / f"{t}.csv"
        out[t] = list(csv.DictReader(open(p, newline=""))) if p.exists() else []
    return out


def bars_from_csv(p: Path) -> dict[str, di.Bars]:
    rows: dict[str, list] = {}
    for r in csv.DictReader(open(p, newline="")):
        rows.setdefault(r["ticker"], []).append(r)
    out = {}
    for tk, rs in rows.items():
        rs.sort(key=lambda r: r["date"])
        adj = [float(r["adj_close"]) for r in rs] if rs[0].get("adj_close") else None
        out[tk] = di.Bars([r["date"] for r in rs], [float(r["open"]) for r in rs],
                          [float(r["high"]) for r in rs], [float(r["low"]) for r in rs],
                          [float(r["close"]) for r in rs], adj)
    return out


def _frame_to_bars(df) -> di.Bars | None:
    try:
        df = df.dropna(subset=["Open", "High", "Low", "Close"])
    except Exception:
        return None
    if df.empty:
        return None
    adj = df["Adj Close"].astype(float).tolist() if "Adj Close" in df else None
    return di.Bars([d.strftime("%Y-%m-%d") for d in df.index],
                   df["Open"].astype(float).tolist(), df["High"].astype(float).tolist(),
                   df["Low"].astype(float).tolist(), df["Close"].astype(float).tolist(), adj)


def fetch_bars(tickers: list[str], start: str) -> dict[str, di.Bars]:
    """Daily OHLC from yfinance, unadjusted (triggers are raw prices) plus the
    dividend-adjusted close for total returns. During the session the last row
    is today's partial bar.

    yfinance's bulk download silently drops tickers when rate-limited (large
    caps came back "possibly delisted" on 2026-10-31). A dropped ticker
    quietly removes its ideas from a source's record — enough to flip
    a tier — so missing names are retried in smaller batches, then one by one.
    """
    import time as _t
    import yfinance as yf
    want = sorted(set(tickers))
    out: dict[str, di.Bars] = {}

    def batch(names: list[str]) -> None:
        data = yf.download(names, start=start, interval="1d", auto_adjust=False,
                           group_by="ticker", progress=False, threads=len(names) > 10)
        for tk in names:
            try:
                b = _frame_to_bars(data[tk] if len(names) > 1 else data)
            except KeyError:
                b = None
            if b is not None:
                out[tk] = b

    batch(want)
    for size in (10, 1):
        missing = [t for t in want if t not in out]
        if not missing:
            break
        _t.sleep(3)
        log.info("retrying %d tickers yfinance dropped: %s", len(missing), " ".join(missing))
        for i in range(0, len(missing), size):
            batch(missing[i:i + size])
            _t.sleep(0.5)
    still = [t for t in want if t not in out]
    if still:
        log.warning("no prices for %d tickers after retries: %s", len(still), " ".join(still))
    return out


def fetch_premarket(tickers: list[str], today: str) -> dict[str, tuple[float, float, float, float]]:
    """Today's pre-market trading per ticker: (open, high, low, last). A ticker
    with no trade today is left out, and on a market holiday all of them are,
    which is how the pre-open send knows the market is shut. Counts only in the
    log: these tickers include holdings and CI logs are public."""
    import yfinance as yf
    names = sorted(set(tickers))
    out: dict[str, tuple[float, float, float, float]] = {}
    try:
        data = yf.download(names, period="1d", interval="5m", prepost=True, auto_adjust=False,
                           group_by="ticker", progress=False, threads=len(names) > 10)
    except Exception as e:
        log.warning("pre-market download failed: %s", type(e).__name__)
        return out
    for tk in names:
        try:
            df = (data[tk] if len(names) > 1 else data).dropna(subset=["Open", "High", "Low", "Close"])
        except KeyError:
            continue
        if df.empty:
            continue
        stamps = df.index.tz_convert(ET) if df.index.tz is not None else df.index
        df = df[stamps.strftime("%Y-%m-%d") == today]
        if not df.empty:
            out[tk] = (float(df["Open"].iloc[0]), float(df["High"].max()),
                       float(df["Low"].min()), float(df["Close"].iloc[-1]))
    log.info("pre-market: quotes for %d of %d tickers", len(out), len(names))
    return out


def fetch_fx() -> float:
    """SGD per USD. Retries, then fails loudly: a guessed rate would mis-size
    Sarah's book, and no DM beats a wrong one."""
    import time as _t
    import yfinance as yf
    for attempt in range(3):
        for sym in ("SGD=X", "USDSGD=X"):
            try:
                s = yf.Ticker(sym).history(period="5d")["Close"].dropna()
                if len(s) and 1.0 < float(s.iloc[-1]) < 2.0:
                    return float(s.iloc[-1])
            except Exception as e:
                log.warning("fx %s attempt %d failed: %s", sym, attempt + 1, e)
        _t.sleep(3 * (attempt + 1))
    raise RuntimeError("no SGD/USD rate from yfinance — not sending a mis-sized DM")


def fetch_option(ticker: str, expiry: str, strike: float) -> tuple[float, float] | None:
    import yfinance as yf
    try:
        calls = yf.Ticker(ticker).option_chain(expiry).calls
        row = calls[abs(calls["strike"] - strike) < 1e-6]
        if row.empty:
            return None
        return float(row["bid"].iloc[0] or 0), float(row["ask"].iloc[0] or 0)
    except Exception as e:
        log.warning("option chain %s %s failed: %s", ticker, expiry, e)
        return None


def fetch_kinds(tickers: list[str]) -> dict[str, str]:
    import yfinance as yf
    out = {}
    for tk in tickers:
        try:
            out[tk] = "ETF" if (yf.Ticker(tk).info or {}).get("quoteType") == "ETF" else "stock"
        except Exception:
            out[tk] = "stock"
    return out


def fetch_earnings(tickers: list[str]) -> dict[str, list[tuple[str, bool]]]:
    """Yahoo's earnings rows per ticker: (date, results are out). A ticker that
    fails or has no rows is left out, so its Sheet dates stand, marked unchecked.
    Logs counts only: these tickers include holdings and CI logs are public."""
    import yfinance as yf
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)    # it names tickers with no dates
    out = {}
    for tk in tickers:
        try:
            df = yf.Ticker(tk).get_earnings_dates(limit=8)
            if df is not None and not df.empty:
                out[tk] = [(d.strftime("%Y-%m-%d"), bool(done))
                           for d, done in df["Reported EPS"].notna().items()]
        except Exception as e:
            log.warning("earnings dates lookup failed: %s", type(e).__name__)
    log.info("earnings cross-check: Yahoo had dates for %d of %d tickers", len(out), len(tickers))
    return out


# ─────────────────────────────────────────────────────────────────────────
# Accounts
# ─────────────────────────────────────────────────────────────────────────

def _latest_date_rows(rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    last = max(r.get("date", "")[:10] for r in rows)
    return [r for r in rows if r.get("date", "")[:10] == last]


def read_positions(tabs: dict) -> tuple[dict, dict, set]:
    """From each book's latest positions snapshot: (account, ticker) →
    unrealised P&L, (account, ticker) → (shares held, average cost), and the
    hold list. Needs no prices or FX, so it runs before the price fetch."""
    upl, holdings = {}, {}
    for name in ACCOUNT_SPECS:
        for p in _latest_date_rows(tabs.get(f"positions_{name}", [])):
            tk = (p.get("ticker") or "").strip().upper()
            if tk:
                upl[(name, tk)] = di.fnum(p.get("upl")) or 0.0
                holdings[(name, tk)] = (di.fnum(p.get("qty")) or 0.0, di.fnum(p.get("avg_cost")) or 0.0)
    holds = set()
    for r in tabs.get("hold_list", []):
        k = hold_key(r.get("account"), r.get("ticker"))
        if k[1]:
            holds.add(k)
    return upl, holdings, holds


def build_accounts(tabs: dict, today: str, sgd_per_usd: float) -> list[di.Account]:
    deposits = {}
    for r in tabs.get("monthly_deposits", []):
        amt = di.fnum(r.get("amount"))
        if amt:
            deposits[(r.get("account") or "").strip().lower()] = (amt, (r.get("ccy") or "SGD").strip().upper())
    month = today[:7]
    accounts = []
    for name, (ccy, nlv_col, cash_col) in ACCOUNT_SPECS.items():
        snaps = sorted(tabs.get(f"snapshot_{name}", []), key=lambda r: r.get("date", ""))
        snaps = [r for r in snaps if di.fnum(r.get(nlv_col))]
        if not snaps:
            log.warning("no snapshot for %s — account left out of sizing", name)
            continue
        cur = snaps[-1]
        dep_amt, dep_ccy = deposits.get(name, (0.0, "SGD"))
        acct = di.Account(name=name, ccy=ccy, nlv=di.fnum(cur.get(nlv_col)) or 0,
                          cash=di.fnum(cur.get(cash_col)) or 0, deposit=dep_amt, deposit_ccy=dep_ccy)
        # Has this month's deposit landed? Cash series = last snapshot of the
        # previous month + this month's, compared in the account's currency.
        prior = [r for r in snaps if r["date"][:7] < month][-1:]
        series = [di.fnum(r.get(cash_col)) or 0
                  for r in prior + [r for r in snaps if r["date"][:7] == month]]
        dep_usd = di.to_usd(dep_amt, dep_ccy, sgd_per_usd)
        dep_in_ccy = dep_usd if ccy == "USD" else dep_usd * sgd_per_usd
        acct.deposit_landed = di.deposit_landed(series, dep_in_ccy)
        for p in _latest_date_rows(tabs.get(f"positions_{name}", [])):
            tk = (p.get("ticker") or "").strip().upper()
            if tk:
                acct.weights[tk] = di.fnum(p.get("weight")) or 0.0
        # Prices alone get refreshed between broker syncs, so a book whose cash
        # and share counts stand still is running on old holdings.
        by_day: dict[str, set] = {}
        for p in tabs.get(f"positions_{name}", []):
            by_day.setdefault((p.get("date") or "")[:10], set()).add(
                ((p.get("ticker") or "").strip().upper(), di.fnum(p.get("qty")) or 0.0))
        acct.stale_since = di.stale_since(
            [(r["date"][:10], di.fnum(r.get(cash_col)) or 0) for r in snaps],
            [(d, frozenset(v)) for d, v in sorted(by_day.items()) if d], today)
        accounts.append(acct)
    return accounts


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────

def print_dry(dm: di.DM, is_fixture: bool) -> None:
    """Print a dry run. Job logs on this public repo are world-readable and the
    DM names account cash, so under GitHub Actions only synthetic runs print."""
    if is_fixture or not os.environ.get("GITHUB_ACTIONS"):
        print(dm.text)
    else:
        log.info("dry run: DM built (%d sized, %d exits, %d watch), not printed: CI logs are public",
                 len(dm.sized), len(dm.exits), len(dm.watch))


def write_cards(client, cards: list[dict], today: str) -> int:
    """Replace today's rows in the PWA's `daily_ideas` tab (a --force resend
    swaps that day's rows instead of stacking a second set). Runs after the
    ledger write, so a failure here costs the PWA its list for the day but never
    the dedup ledger or causes a re-send. Returns 0, or 1 if the write failed."""
    from src import sheets as sh
    try:
        sh.ensure_headers(client, CARD_TAB, CARD_HEADERS)
        rows = [[str(c.get(h, "")) for h in CARD_HEADERS] for c in cards]
        n = sh.replace_today_rows(client, CARD_TAB, rows, today_prefix=today)
        log.info("wrote %d cards to %s", n, CARD_TAB)
        _flag_sent()
        return 0
    except Exception:
        log.exception("could not write the %s tab (the DM was sent and the ledger written)", CARD_TAB)
        return 1


def _flag_sent() -> None:
    """Tell the workflow fresh rows exist, so it starts the Firestore mirror."""
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write("sent=true\n")


def warn_if_missed(tabs: dict, now_et: datetime, today: str) -> int:
    """A run landing after the window: if SPY traded and no list went out, say
    so once, because a dead timer would otherwise look exactly like a quiet day."""
    if any(r.get("date") == today for r in tabs.get(LOG_TAB, [])):
        return 0
    spy = fetch_bars(["SPY"], (now_et.date() - timedelta(days=7)).isoformat()).get("SPY")
    if spy is None or spy.dates[-1] != today:
        return 0
    from src import telegram as tg, sheets as sh
    sgt = now_et.astimezone(di.SGT).strftime("%H:%M")
    tg.ping_daily_ideas(f"⚠️ <b>No ideas list today.</b> The {di.RECHECK_ET[0]:02d}:{di.RECHECK_ET[1]:02d} ET "
                        f"re-check never ran and it is now {now_et.strftime('%H:%M')} ET · {sgt} SGT. "
                        f"Check the casaa-dispatch timer on the VM.")
    client = sh.authenticate()
    sh.ensure_headers(client, LOG_TAB, LOG_HEADERS)
    row = {"date": today, "sent_at": now_et.strftime("%Y-%m-%dT%H:%M"), "num": 0, "source": "missed"}
    sh.append_rows(client, LOG_TAB, [[str(row.get(h, "")) for h in LOG_HEADERS]])
    log.info("warned that today's list never went out")
    return 0


def run(args) -> int:
    fixture = Path(args.fixture) if args.fixture else None
    meta = json.loads((fixture / "meta.json").read_text()) if fixture else {}
    now_et = (datetime.fromisoformat(meta["now"]).replace(tzinfo=ET) if fixture
              else datetime.now(ET))
    today = now_et.date().isoformat()
    live_send = not (args.dry or fixture)
    clock = now_et.time()
    phase = args.phase or ("preopen" if clock < MARKET_OPEN else "open")

    tabs = None
    if live_send and not args.force:
        if now_et.weekday() >= 5:
            log.info("weekend — nothing to do")
            return 0
        if clock > WINDOW[1]:
            return warn_if_missed(load_tabs_sheet(), now_et, today)
        if not (PREOPEN_WINDOW[0] <= clock <= PREOPEN_WINDOW[1] or WINDOW[0] <= clock <= WINDOW[1]):
            log.info("outside the send windows (%s ET) — nothing to do", now_et.strftime("%H:%M"))
            return 0

    tabs = load_tabs_dir(fixture) if fixture else load_tabs_sheet()
    todays_cards = [r for r in tabs.get(CARD_TAB, []) if r.get("date") == today]

    if live_send and not args.force:
        if any(r.get("date") == today for r in tabs.get(LOG_TAB, [])):
            log.info("ideas DM already sent today — skipping")
            return 0
        if phase == "preopen" and any(r.get("phase") == "preopen" for r in todays_cards):
            log.info("pre-open plan already sent today — skipping")
            return 0

    dq = tabs["decision_queue"]
    hist = {
        "wsr": di.wsr_history(dq),
        "uoa": di.uoa_history(tabs["uoa_alerts"]),
        "gov": di.gov_history(tabs["gov_confluence_signals"]),
        "momentum": di.momentum_history(tabs["screen_candidates"]),
        "wsr_trim": di.wsr_trim_history(dq, {a: tabs.get(f"positions_{a}", []) for a in ACCOUNT_SPECS}),
    }
    wsr = di.live_wsr_dips(dq, today)
    uoa = di.uoa_candidates(tabs["uoa_alerts"], today)
    gov = di.gov_watch(tabs["gov_confluence_signals"], today)
    mom = di.momentum_watch(tabs["screen_candidates"], today)
    upl, holdings, holds = read_positions(tabs)
    exits = di.live_wsr_trims(dq, today, upl, holds)

    tickers = {"SPY", "QQQ"} | {i.ticker for v in hist.values() for i in v} \
        | {i.ticker for i in wsr + uoa} | {m["ticker"] for m in mom} | ({gov["ticker"]} if gov else set()) \
        | {e.ticker for e in exits}
    if fixture:
        bars = bars_from_csv(fixture / "prices.csv")
        sgd_per_usd = float(meta["sgd_per_usd"])
        kinds = meta.get("kinds", {})
        opts = meta.get("options", {})
        yahoo = meta.get("yahoo_earnings", {})
    else:
        first = min([i.date for v in hist.values() for i in v] + [today])
        start = min(date.fromisoformat(first) - timedelta(days=45),
                    date.fromisoformat(today) - timedelta(days=SMA_HISTORY_DAYS)).isoformat()
        log.info("fetching %d tickers since %s", len(tickers), start)
        bars = fetch_bars(sorted(tickers), start)
        sgd_per_usd = fetch_fx()
        kinds = fetch_kinds([i.ticker for i in wsr])
        opts = {}
        yahoo = fetch_earnings(sorted(t for t in {i.ticker for i in wsr + uoa} | {e.ticker for e in exits}
                                      | {tk for _, tk in holdings} if kinds.get(t) != "ETF"))
        if phase == "preopen":
            quotes = fetch_premarket(sorted({"SPY", "QQQ"} | {i.ticker for i in wsr + uoa}
                                            | {m["ticker"] for m in mom} | {e.ticker for e in exits}), today)
            if live_send and not args.force and "SPY" not in quotes:
                log.info("SPY has no pre-market trades for %s — market closed, nothing sent", today)
                return 0
            bars = di.with_premarket(bars, quotes, today)

    spy = bars.get("SPY")
    if live_send and not args.force and (spy is None or spy.dates[-1] != today):
        log.info("SPY has no bar for %s — market closed, nothing sent", today)
        return 0

    records = {s: di.assign_tier(di.grade(s, h, bars, today)) for s, h in hist.items()}

    for idea in uoa:
        key = f"{idea.ticker}|{idea.expiry}|{idea.strike:g}"
        q = opts.get(key) if fixture else fetch_option(idea.ticker, idea.expiry, idea.strike)
        if q:
            bid, ask = (q["bid"], q["ask"]) if isinstance(q, dict) else q
            if ask > 0:
                idea.limit, idea.mid = ask, (bid + ask) / 2 if bid > 0 else ask
        # else: keep the scan's own ask; the scan date is in the "why" line

    accounts = build_accounts(tabs, today, sgd_per_usd)
    sheet_dates: dict[str, list[str]] = {}
    for r in tabs.get("earnings_calendar", []):
        if r.get("ticker") and r.get("date"):
            sheet_dates.setdefault(r["ticker"].strip().upper(), []).append(r["date"][:10])
    earnings = {t: di.reconcile_earnings(sheet_dates.get(t, []), yahoo.get(t), today)
                for t in set(sheet_dates) | set(yahoo)}
    blocked = di.blocked_sells(dq, today, upl, holds)
    growth_on = os.environ.get("GROWTH_LEG_ENABLED", "").lower() in ("true", "1", "yes")

    dm = di.build_dm(now_et=now_et, today=today, records=records, wsr=wsr, uoa=uoa, gov=gov,
                     momentum=mom, bars=bars, accounts=accounts, sgd_per_usd=sgd_per_usd,
                     kinds=kinds, earnings=earnings, blocked=blocked, growth_leg_on=growth_on,
                     exits=exits, holdings=holdings, phase=phase,
                     direction=di.direction_lines(tabs.get("daily_brief_latest", []), spy, today),
                     levels=di.level_lines(bars, tabs.get("gex_regime", []), tabs.get("macro", []), today),
                     prior_cards=[r for r in todays_cards if r.get("phase") == "preopen"] if phase == "open" else None)

    for s, r in records.items():
        log.info("record %-8s n=%-4d beat=%-4d alpha=%+.2f%% t=%s weeks=%d tier=%s "
                 "(open %d, unfilled %d, no prices %d)",
                 s, r.n, r.beat, r.mean_alpha * 100, f"{r.t:+.2f}" if r.t is not None else "—",
                 r.clusters, r.tier, r.open, r.unfilled, r.nodata)

    if not live_send:
        log.info("dry run: %d cards would go to %s", len(dm.cards), CARD_TAB)   # stderr: stdout stays the DM
        print_dry(dm, fixture is not None)
        return 0

    from src import telegram as tg
    tg.ping_daily_ideas(dm.text)
    from src import sheets as sh
    client = sh.authenticate()
    if phase == "preopen":      # a preview: not graded, and it must not block the re-check
        log.info("sent the pre-open plan: %d sized, %d exits", len(dm.sized), len(dm.exits))
        return write_cards(client, dm.cards, today)
    sh.ensure_headers(client, LOG_TAB, LOG_HEADERS)
    rows = dm.log_rows or []
    rows.append({"date": today, "sent_at": now_et.strftime("%Y-%m-%dT%H:%M"), "num": 0,
                 "source": "dm", "status": f"{len(dm.sized)} sized · {len(dm.exits)} exits · "
                                           f"{len(dm.watch)} watch"})
    sh.append_rows(client, LOG_TAB, [[str(r.get(h, "")) for h in LOG_HEADERS] for r in rows])
    log.info("sent ideas DM: %d sized, %d exits, %d watch, %d dropped",
             len(dm.sized), len(dm.exits), len(dm.watch), len(dm.dropped))
    return write_cards(client, dm.cards, today)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry", action="store_true", help="print the DM instead of sending it")
    ap.add_argument("--fixture", help="offline run from a fixture folder (implies --dry)")
    ap.add_argument("--force", action="store_true", help="ignore the time window and the once-a-day ledger")
    ap.add_argument("--phase", choices=("preopen", "open"), help="default: by the clock, before or after 09:30 ET")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    if not args.fixture:
        from src.sync import load_env
        load_env()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
