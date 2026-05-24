"""
backtest_scoring.py — Walk-forward backtest for technical_score.py weights.

Simulates CSP, CC, and BUY strategies using compute_scores() at each
historical date, tracks forward returns, and reports hit rates + edge
vs random.

Usage:
  python scripts/backtest_scoring.py                     # default 10 tickers, 1y
  python scripts/backtest_scoring.py --tickers AAPL NVDA # specific tickers
  python scripts/backtest_scoring.py --period 2y         # 2 years
  python scripts/backtest_scoring.py --threshold 40      # score threshold
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.indicators import compute_indicators
from src.technical_score import compute_scores, score_label


# ── Default universe for backtesting ────────────────────────────────────────
DEFAULT_TICKERS = [
    "AAPL", "NVDA", "TSLA", "AMD", "META",
    "AMZN", "MSFT", "GOOGL", "MSTR", "COIN",
]


@dataclass
class Trade:
    ticker: str
    strategy: str
    entry_date: str
    entry_price: float
    score: float
    exit_date: str = ""
    exit_price: float = 0.0
    pnl_pct: float = 0.0


@dataclass
class StrategyStats:
    name: str
    trades: list[Trade] = field(default_factory=list)
    wins: int = 0
    losses: int = 0

    @property
    def total(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float:
        return self.wins / self.total * 100 if self.total else 0

    @property
    def avg_pnl(self) -> float:
        if not self.trades:
            return 0
        return sum(t.pnl_pct for t in self.trades) / len(self.trades)

    @property
    def max_win(self) -> float:
        return max((t.pnl_pct for t in self.trades), default=0)

    @property
    def max_loss(self) -> float:
        return min((t.pnl_pct for t in self.trades), default=0)


def _fetch_data(tickers: list[str], period: str) -> dict[str, pd.DataFrame]:
    """Fetch OHLCV for all tickers."""
    import yfinance as yf

    out = {}
    for ticker in tickers:
        try:
            df = yf.download(ticker, period=period, progress=False, auto_adjust=True)
            if df is not None and not df.empty and len(df) >= 60:
                # Flatten MultiIndex columns if present
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                out[ticker] = df
        except Exception:
            pass
    return out


def _run_backtest(
    ticker: str,
    df: pd.DataFrame,
    threshold: int,
    hold_days: int,
    min_window: int = 250,
) -> list[Trade]:
    """
    Walk-forward backtest for a single ticker.

    At each date (starting after min_window bars):
    1. Compute indicators on the trailing window
    2. Compute scores
    3. If score >= threshold for a strategy, open a trade
    4. Close after hold_days, measure P&L

    CSP win = price stays above entry (put expires OTM)
    CC win = price stays below entry + 5% (call expires OTM)
    BUY win = price goes up
    """
    trades = []
    dates = df.index.tolist()

    # Don't open trades in the last hold_days
    for i in range(min_window, len(dates) - hold_days):
        window = df.iloc[max(0, i - min_window):i + 1]
        entry_date = dates[i]
        entry_price = float(df.loc[entry_date, "Close"])

        if entry_price <= 0:
            continue

        ind = compute_indicators(window)
        scores = compute_scores(ind)

        # Exit price after hold_days
        exit_idx = i + hold_days
        exit_date = dates[exit_idx]
        exit_price = float(df.loc[exit_date, "Close"])
        pct_move = (exit_price - entry_price) / entry_price * 100

        # CSP: win if price didn't crash (stayed above -5%)
        csp_score = scores.get("CSP", 0)
        if csp_score >= threshold:
            csp_win = pct_move > -5  # 5% OTM cushion
            trades.append(Trade(
                ticker=ticker, strategy="CSP",
                entry_date=str(entry_date.date()),
                entry_price=entry_price,
                score=csp_score,
                exit_date=str(exit_date.date()),
                exit_price=exit_price,
                # CSP P&L: premium collected (proxy ~2%) minus loss if assigned
                pnl_pct=2.0 if csp_win else pct_move + 2.0,
            ))

        # CC: win if price didn't blast through +5%
        cc_score = scores.get("CC", 0)
        if cc_score >= threshold:
            cc_win = pct_move < 5  # call stays OTM
            trades.append(Trade(
                ticker=ticker, strategy="CC",
                entry_date=str(entry_date.date()),
                entry_price=entry_price,
                score=cc_score,
                exit_date=str(exit_date.date()),
                exit_price=exit_price,
                # CC P&L: premium + stock move, capped if called away
                pnl_pct=min(pct_move + 1.5, 6.5) if not cc_win else pct_move + 1.5,
            ))

        # BUY: win if price went up
        buy_score = scores.get("BUY", 0)
        if buy_score >= threshold:
            trades.append(Trade(
                ticker=ticker, strategy="BUY",
                entry_date=str(entry_date.date()),
                entry_price=entry_price,
                score=buy_score,
                exit_date=str(exit_date.date()),
                exit_price=exit_price,
                pnl_pct=pct_move,
            ))

    return trades


def _baseline_stats(
    df: pd.DataFrame,
    hold_days: int,
    min_window: int = 250,
) -> dict[str, float]:
    """Compute baseline: random entry every day, same hold period."""
    dates = df.index.tolist()
    moves = []
    for i in range(min_window, len(dates) - hold_days):
        entry = float(df.iloc[i]["Close"])
        exit_ = float(df.iloc[i + hold_days]["Close"])
        if entry > 0:
            moves.append((exit_ - entry) / entry * 100)

    if not moves:
        return {"up_pct": 50.0, "avg_move": 0.0}

    up = sum(1 for m in moves if m > 0)
    return {
        "up_pct": up / len(moves) * 100,
        "avg_move": sum(moves) / len(moves),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Backtest technical scoring")
    ap.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    ap.add_argument("--period", default="1y", help="yfinance period (1y, 2y)")
    ap.add_argument("--threshold", type=int, default=30, help="Score threshold")
    ap.add_argument("--hold", type=int, default=35, help="Hold period in days")
    args = ap.parse_args()

    print(f"Backtest: {len(args.tickers)} tickers, period={args.period}, "
          f"threshold={args.threshold}, hold={args.hold}d")
    print()

    data = _fetch_data(args.tickers, args.period)
    print(f"Data fetched: {len(data)} tickers with enough history")

    if not data:
        print("No data — aborting")
        return 1

    # Run backtests
    all_trades: list[Trade] = []
    baselines: list[dict] = []
    for ticker, df in data.items():
        trades = _run_backtest(ticker, df, args.threshold, args.hold)
        all_trades.extend(trades)
        bl = _baseline_stats(df, args.hold)
        baselines.append(bl)
        strats = {}
        for t in trades:
            strats.setdefault(t.strategy, []).append(t)
        counts = ", ".join(f"{s}: {len(ts)}" for s, ts in sorted(strats.items()))
        print(f"  {ticker:6}: {len(trades)} signals ({counts or 'none'})")

    if not all_trades:
        print("\nNo signals generated at threshold={args.threshold}. Try lowering it.")
        return 0

    # Aggregate baseline
    avg_up = sum(b["up_pct"] for b in baselines) / len(baselines)
    avg_move = sum(b["avg_move"] for b in baselines) / len(baselines)

    # Group by strategy
    by_strat: dict[str, StrategyStats] = {}
    for t in all_trades:
        if t.strategy not in by_strat:
            by_strat[t.strategy] = StrategyStats(name=t.strategy)
        ss = by_strat[t.strategy]
        ss.trades.append(t)
        if t.pnl_pct > 0:
            ss.wins += 1
        else:
            ss.losses += 1

    # Report
    print("\n" + "=" * 70)
    print(f"{'STRATEGY':10} {'SIGNALS':>8} {'WIN%':>7} {'AVG P&L':>9} "
          f"{'MAX WIN':>9} {'MAX LOSS':>10} {'EDGE':>7}")
    print("=" * 70)

    for name in ["BUY", "CSP", "CC"]:
        ss = by_strat.get(name)
        if not ss:
            print(f"{name:10} {'0':>8} {'—':>7} {'—':>9} {'—':>9} {'—':>10} {'—':>7}")
            continue
        # Edge = avg P&L minus baseline avg move (for BUY)
        # For CSP/CC, edge = win rate minus baseline up/down %
        if name == "BUY":
            edge = ss.avg_pnl - avg_move
        elif name == "CSP":
            edge = ss.win_rate - avg_up  # CSP wins when stock doesn't crash
        else:  # CC
            edge = ss.win_rate - (100 - avg_up)  # CC wins when stock doesn't blast up

        print(f"{name:10} {ss.total:>8} {ss.win_rate:>6.1f}% {ss.avg_pnl:>+8.2f}% "
              f"{ss.max_win:>+8.2f}% {ss.max_loss:>+9.2f}% {edge:>+6.1f}%")

    print("=" * 70)
    print(f"{'BASELINE':10} {'':>8} {avg_up:>6.1f}% {avg_move:>+8.2f}%")
    print()

    # Score-bucketed analysis
    print("Score-bucketed win rates (does higher score = better outcome?):")
    print("-" * 55)
    print(f"{'STRAT':6} {'BUCKET':>12} {'SIGNALS':>8} {'WIN%':>7} {'AVG P&L':>9}")
    print("-" * 55)
    for name in ["BUY", "CSP", "CC"]:
        ss = by_strat.get(name)
        if not ss or len(ss.trades) < 5:
            continue
        buckets = {"10-14": [], "15-19": [], "20-24": [], "25+": []}
        for t in ss.trades:
            if t.score >= 25:
                buckets["25+"].append(t)
            elif t.score >= 20:
                buckets["20-24"].append(t)
            elif t.score >= 15:
                buckets["15-19"].append(t)
            else:
                buckets["10-14"].append(t)
        for bname, bts in buckets.items():
            if not bts:
                continue
            bwins = sum(1 for t in bts if t.pnl_pct > 0)
            bavg = sum(t.pnl_pct for t in bts) / len(bts)
            print(f"{name:6} {bname:>12} {len(bts):>8} "
                  f"{bwins/len(bts)*100:>6.1f}% {bavg:>+8.2f}%")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
