#!/usr/bin/env python3
"""Regenerate the synthetic daily-ideas fixture (offline dryrun + tests).

Every number here is made up — tickers, prices, balances and deposits are
synthetic placeholders, because this repo is public. The data is shaped so each
rule in src/daily_ideas.py fires once: a dip-buy hit today (AAA), one below its
trigger (EEE ETF), one far above (MMM), one too dear for the small book (SSS),
a call idea from options flow (GGG), a momentum name whose stop broke (QQC),
one that holds (ZZZ), a gov-contract signal (BBB), trims blocked by the
never-sell-a-loser rule (UUU underwater, TTT on the hold list), a killed idea
(KIL) and a stale one (OLD). Take-profit exits: a sell-now on a winner (WWW),
a trim 1% below its level (VVV) and one still far off (PPP), graded on a
history of trims of positions that were up at the time.
Earnings dates: Yahoo agrees (AAA), a stale Sheet date after a confirmed report
(VVV), Yahoo earlier than the Sheet (WWW) and no Yahoo rows at all (GGG).

  python fixtures/daily_ideas/make_fixture.py
"""
from __future__ import annotations

import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parent
TODAY = date(2026, 11, 2)
rng = random.Random(7)


def business_days(start: date, end: date) -> list[str]:
    d, out = start, []
    while d <= end:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


DAYS = business_days(date(2026, 3, 2), TODAY)


def walk(p0: float, drift: float, vol: float) -> list[float]:
    out, p = [], p0
    for _ in DAYS:
        p *= 1 + drift + rng.gauss(0, vol)
        out.append(round(p, 2))
    return out


def ohlc(closes: list[float]) -> list[tuple]:
    rows, prev = [], closes[0]
    for c in closes:
        o = round(prev * (1 + rng.gauss(0, 0.003)), 2)
        h = round(max(o, c) * (1 + abs(rng.gauss(0, 0.004))), 2)
        lo = round(min(o, c) * (1 - abs(rng.gauss(0, 0.004))), 2)
        rows.append((o, h, lo, c))
        prev = c
    return rows


def shaped(base: float, tail: list[float]) -> list[float]:
    """A quiet walk around `base`, ending in an exact hand-written tail."""
    head = [round(base * (1 + rng.gauss(0, 0.01)), 2) for _ in DAYS[: -len(tail)]]
    return head + tail


prices: dict[str, list[tuple]] = {}
prices["SPY"] = ohlc(walk(600, 0.0004, 0.008))
prices["QQQ"] = ohlc(walk(520, 0.0005, 0.011))
for i, tk in enumerate(["H1", "H2", "H3", "H4", "H5", "H6", "H7", "H8"]):
    prices[tk] = ohlc(walk(50 + 10 * i, rng.uniform(-0.001, 0.0015), 0.015))

# Hand-shaped names: (closes, then today's bar overridden as o/h/l/c).
special = {
    "AAA": (shaped(106, [106, 105, 104, 101, 98, 96.5, 99, 102, 104, 105, 104, 103.5, 104,
                         105, 104.5, 104, 103.5, 103, 103.2, 103, 100.4]), (102.5, 103.0, 99.5, 100.4)),
    "EEE": (shaped(50.6, [50.8, 50.5, 50.2, 49.6, 49.1, 49.4, 50.0, 50.3, 50.6, 50.7, 50.4,
                          50.5, 50.3, 50.2, 50.4, 50.3, 50.1, 50.2, 50.3, 50.2, 49.6]), (50.1, 50.2, 49.5, 49.6)),
    "MMM": (shaped(88, [88, 89, 90, 90]), (90.2, 90.6, 89.4, 90.0)),
    "SSS": (shaped(405, [405, 398, 395, 401, 404, 406, 405, 404]), (405, 406, 403, 404.0)),
    "GGG": (shaped(152, [152, 151, 150, 149, 148, 147, 146, 145, 144, 143, 142, 141, 140, 139,
                         138, 137.5, 138, 139, 140, 141, 140]), (140.5, 141.2, 139.6, 140.0)),
    "ZZZ": (shaped(80, [80, 82, 84, 86, 86, 85]), (85.6, 86.0, 84.8, 85.0)),
    "QQC": (shaped(53, [53, 52.5, 52, 52, 48]), (51.5, 51.6, 47.8, 48.0)),
    "BBB": (shaped(60, [60, 62, 64, 66, 68, 70, 72, 72]), (71.5, 72.4, 71.2, 72.0)),
    "VVV": (shaped(400, [404, 408, 410, 412, 415, 416]), (415.5, 418.0, 413.0, 416.0)),
    "WWW": (shaped(30, [30.5, 31, 31.5, 32]), (31.8, 32.3, 31.6, 32.0)),
    "PPP": (shaped(100, [100, 101, 100]), (100.2, 100.8, 99.6, 100.0)),
}
for tk, (closes, today_bar) in special.items():
    rows = ohlc(closes)
    rows[-1] = today_bar
    prices[tk] = rows

with open(OUT / "prices.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["ticker", "date", "open", "high", "low", "close"])
    for tk, rows in prices.items():
        for d, (o, h, lo, c) in zip(DAYS, rows):
            w.writerow([tk, d, o, h, lo, c])


def close_on(tk: str, d: str) -> float:
    return prices[tk][DAYS.index(d)][3]


def write(name: str, header: list[str], rows: list[dict]) -> None:
    with open(OUT / f"{name}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in header})


hist_dates = [d for d in DAYS if "2026-04-06" <= d <= "2026-09-18"][::7]

DQ_HDR = ["date", "account", "ticker", "bucket", "thesis_1liner", "conv", "entry", "target",
          "status", "strategy", "right", "strike", "expiry", "premium_per_share", "delta",
          "annual_yield_pct", "breakeven", "cash_required", "iv_rank", "thesis_confidence",
          "thesis", "source", "qty", "accumulation_plan", "gates"]
dq = []
for i, d in enumerate(hist_dates[:16]):
    tk = f"H{i % 8 + 1}"
    dq.append({"date": f"{d}T013000", "account": "sarah", "ticker": tk, "strategy": "BUY_DIP",
               "entry": round(close_on(tk, d) * 0.99, 2), "status": "filled",
               "source": "wsr_full", "thesis_1liner": f"{tk} dip — synthetic history"})
live = "2026-10-28T013300"
dq += [
    {"date": "2026-10-26T232050", "account": "sarah", "ticker": "AAA", "strategy": "BUY_DIP",
     "entry": 100, "target": 115, "status": "watching", "source": "wsr_full", "qty": 3,
     "thesis_1liner": "AAA BUY_DIP $100 — post-earnings add on a pullback to support."},
    {"date": live, "account": "sarah", "ticker": "AAA", "strategy": "BUY_DIP", "entry": 100,
     "target": 115, "status": "watching", "source": "wsr_lite",
     "thesis_1liner": "AAA $103 (-1% WoW) — still watching the $100 dip level."},
    {"date": live, "account": "sarah", "ticker": "EEE", "strategy": "BUY_DIP", "entry": 50,
     "target": 54, "status": "pending", "source": "wsr_lite",
     "thesis_1liner": "EEE $50.20 — international equity underweight; starter position."},
    {"date": live, "account": "caspar", "ticker": "MMM", "strategy": "BUY_DIP", "entry": 80,
     "target": 95, "status": "watching", "source": "wsr_lite",
     "thesis_1liner": "MMM $88 — add on a deeper pullback."},
    {"date": live, "account": "caspar", "ticker": "SSS", "strategy": "BUY_DIP", "entry": 400,
     "target": 440, "status": "watching", "source": "wsr_lite",
     "thesis_1liner": "SSS $405 — core index exposure on a dip."},
    {"date": "2026-10-26T232050", "account": "sarah", "ticker": "KIL", "strategy": "BUY_DIP",
     "entry": 30, "status": "watching", "source": "wsr_full", "thesis_1liner": "KIL — x"},
    {"date": live, "account": "sarah", "ticker": "KIL", "strategy": "BUY_DIP", "entry": 30,
     "status": "killed", "source": "wsr_lite", "thesis_1liner": "KIL BUY_DIP KILLED — anchor broken."},
    {"date": "2026-10-12T232050", "account": "sarah", "ticker": "OLD", "strategy": "BUY_DIP",
     "entry": 20, "status": "watching", "source": "wsr_full", "thesis_1liner": "OLD — stale"},
    {"date": live, "account": "sarah", "ticker": "UUU", "strategy": "TRIM", "entry": 7,
     "status": "pending", "source": "wsr_lite", "thesis_1liner": "UUU — sell the loser"},
    {"date": live, "account": "caspar", "ticker": "TTT", "strategy": "TRIM", "entry": 3,
     "status": "pending", "source": "wsr_lite", "thesis_1liner": "TTT — sell"},
    {"date": live, "account": "sarah", "ticker": "VVV", "strategy": "TRIM", "entry": 420,
     "status": "watching", "source": "wsr_lite", "qty": 3,
     "thesis_1liner": "VVV $416 — trim the winner at $420, RSI overbought."},
    {"date": live, "account": "caspar", "ticker": "WWW", "strategy": "TRIM", "entry": 31.5,
     "status": "pending", "source": "wsr_lite", "qty": 5,
     "thesis_1liner": "WWW $31.50 (+58% from cost) — sell 5sh at market, lock the gain."},
    {"date": live, "account": "sarah", "ticker": "PPP", "strategy": "TRIM", "entry": 120,
     "status": "watching", "source": "wsr_lite", "qty": 2,
     "thesis_1liner": "PPP $101 — next ladder step at $120."},
]
# Trim history: positions that were in profit when the WSR wrote the trim.
trim_dates = hist_dates[1:15]
for i, d in enumerate(trim_dates):
    tk = f"H{(i + 2) % 8 + 1}"
    dq.append({"date": f"{d}T013000", "account": "sarah", "ticker": tk, "strategy": "TRIM",
               "entry": round(close_on(tk, d) * 1.01, 2), "status": "watching", "qty": 2,
               "source": "wsr_full", "thesis_1liner": f"{tk} trim — synthetic history"})
write("decision_queue", DQ_HDR, dq)

UOA_HDR = ["date", "ticker", "alert_type", "side", "strike", "expiry", "dte", "volume",
           "open_interest", "vol_oi_ratio", "implied_vol", "notional", "moneyness",
           "underlying_last", "option_price", "severity", "detail", "bid", "ask", "last_price",
           "aggressor", "structure", "bias", "extrinsic_pct", "quality"]
uoa = [{"date": d, "ticker": f"H{(i + 3) % 8 + 1}", "side": "CALL", "strike": 100,
        "expiry": "2026-12-18", "dte": 40, "notional": 1_500_000, "aggressor": "BUY_INITIATED",
        "structure": "LONG_CALL", "bias": "BULLISH", "quality": 86}
       for i, d in enumerate(hist_dates[:14])]
uoa += [
    {"date": "2026-10-30", "ticker": "GGG", "side": "CALL", "strike": 150, "expiry": "2026-11-20",
     "dte": 21, "notional": 2_500_000, "aggressor": "BUY_INITIATED", "structure": "LONG_CALL",
     "bias": "BULLISH", "quality": 88, "bid": 3.3, "ask": 3.5},
    {"date": "2026-10-30", "ticker": "GGG", "side": "CALL", "strike": 155, "expiry": "2026-11-20",
     "dte": 21, "notional": 1_200_000, "aggressor": "BUY_INITIATED", "structure": "LONG_CALL",
     "bias": "BULLISH", "quality": 86, "bid": 1.6, "ask": 1.7},
    {"date": "2026-10-30", "ticker": "SPY", "side": "CALL", "strike": 610, "expiry": "2026-11-04",
     "dte": 5, "notional": 9_000_000, "aggressor": "BUY_INITIATED", "structure": "LONG_CALL",
     "bias": "BULLISH", "quality": 90, "bid": 2, "ask": 2.1},
]
write("uoa_alerts", UOA_HDR, uoa)

GOV_HDR = ["date", "ticker", "confluence_score", "investment_score", "contract_usd",
           "contract_pct_mktcap", "thesis_oneliner", "recommended_action"]
gov = [{"date": d, "ticker": f"H{i % 8 + 1}", "investment_score": 50, "contract_usd": 5e7,
        "contract_pct_mktcap": 0.02} for i, d in enumerate(hist_dates[::1][:12])]
gov += [
    {"date": "2026-10-30", "ticker": "BBB", "investment_score": 55, "contract_usd": 1.2e9,
     "contract_pct_mktcap": 0.05},
    {"date": "2026-10-30", "ticker": "H2", "investment_score": 60, "contract_usd": 2e6,
     "contract_pct_mktcap": 0.0001},
]
write("gov_confluence_signals", GOV_HDR, gov)

SC_HDR = ["date", "source", "ticker", "sector", "score", "trigger_price", "stop_price", "rationale"]
sc = [{"date": f"{d}T023600", "source": "momentum", "ticker": f"H{(i + 5) % 8 + 1}", "score": 70}
      for i, d in enumerate(hist_dates[:12])]
sc += [
    {"date": "2026-10-29T023623", "source": "momentum", "ticker": "ZZZ", "score": 90, "stop_price": 70},
    {"date": "2026-10-29T023623", "source": "momentum", "ticker": "QQC", "score": 80, "stop_price": 50},
]
write("screen_candidates", SC_HDR, sc)

write("snapshot_caspar", ["date", "net_liq_usd", "cash", "upl", "upl_pct", "excess_liq"], [
    {"date": "2026-10-30T071300", "net_liq_usd": 10000, "cash": 150},
    {"date": "2026-11-02T071300", "net_liq_usd": 10000, "cash": 150},
])
write("snapshot_sarah", ["date", "net_liq_sgd", "cash_sgd", "upl_sgd", "upl_pct", "excess_liq_sgd"], [
    {"date": "2026-10-30T071300", "net_liq_sgd": 50000, "cash_sgd": 1600},
    {"date": "2026-11-02T071300", "net_liq_sgd": 50000, "cash_sgd": 1600},
])
POS_HDR = ["date", "ticker", "qty", "avg_cost", "last", "mkt_val", "upl", "weight"]
write("positions_caspar", POS_HDR, [
    {"date": "2026-11-02T071300", "ticker": "TTT", "qty": 100, "upl": -120, "weight": 0.03},
    {"date": "2026-11-02T071300", "ticker": "SSS", "qty": 1, "upl": 40, "weight": 0.04},
    {"date": "2026-11-02T071300", "ticker": "WWW", "qty": 20, "avg_cost": 20, "upl": 230, "weight": 0.06},
])
write("positions_sarah", POS_HDR, [
    {"date": f"{d}T071300", "ticker": f"H{(i + 2) % 8 + 1}", "qty": 10, "avg_cost": 1, "upl": 100}
    for i, d in enumerate(trim_dates)
] + [
    {"date": "2026-11-02T071300", "ticker": "UUU", "qty": 100, "upl": -300, "weight": 0.01},
    {"date": "2026-11-02T071300", "ticker": "VVV", "qty": 10, "avg_cost": 330, "upl": 900, "weight": 0.08},
    {"date": "2026-11-02T071300", "ticker": "PPP", "qty": 4, "avg_cost": 80, "upl": 80, "weight": 0.01},
])
write("hold_list", ["date", "account", "ticker", "note"],
      [{"date": "2026-10-09", "account": "caspar", "ticker": "TTT", "note": "synthetic"}])
write("monthly_deposits", ["account", "amount", "ccy", "note"], [
    {"account": "caspar", "amount": 400, "ccy": "SGD", "note": "synthetic"},
    {"account": "sarah", "amount": 2500, "ccy": "SGD", "note": "synthetic"},
])
write("earnings_calendar", ["date", "ticker", "hour"], [
    {"date": "2026-11-06", "ticker": "AAA", "hour": "amc"},    # Yahoo agrees
    {"date": "2026-11-04", "ticker": "VVV", "hour": "amc"},    # stale: Yahoo shows it reported 28 Oct
    {"date": "2026-11-12", "ticker": "WWW", "hour": "amc"},    # Yahoo says earlier, 5 Nov
    {"date": "2026-11-10", "ticker": "GGG", "hour": "amc"},    # Yahoo has no rows
])
(OUT / "meta.json").write_text(json.dumps({
    "now": "2026-11-02T09:47:00",
    "sgd_per_usd": 1.28,
    "kinds": {"EEE": "ETF"},
    "options": {"GGG|2026-11-20|150": {"bid": 2.9, "ask": 3.1}},
    "yahoo_earnings": {
        "AAA": [["2026-11-06", False], ["2026-08-06", True]],
        "VVV": [["2027-01-27", False], ["2026-10-28", True], ["2026-07-29", True]],
        "WWW": [["2026-11-05", False], ["2026-08-05", True]],
    },
}, indent=1) + "\n")
print("fixture written to", OUT)
