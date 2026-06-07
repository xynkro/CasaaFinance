"""
unusual_options_scan.py — Unusual Options Activity (UOA) Scanner

Detects abnormal options flow that may indicate informed money, institutional
positioning, or large directional bets. Scans across expirations to find:

1. Volume/OI ratio spikes   — fresh positioning (not rolling)
2. Volume vs 20d avg        — 3x+ normal = someone's loading
3. Single-strike concentration — 60%+ of daily volume on one strike
4. OTM volume spikes        — heavy flow on far-OTM = cheap bets or informed
5. Put/Call volume skew      — one-sided flow = directional conviction

Triggered daily by .github/workflows/unusual-options-scan.yml at 22:30 SGT
(after US market close, when final volume is available).

Usage:
  python scripts/unusual_options_scan.py            # full scan
  python scripts/unusual_options_scan.py --dry      # print only
  python scripts/unusual_options_scan.py --tickers NVDA TSLA  # specific
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.logging_util import setup_logging  # noqa: E402


# ─── Scanner parameters ────────────────────────────────────────────────────
VOL_OI_THRESHOLD   = 3.0    # volume/OI ratio considered unusual
VOL_AVG_MULT       = 3.0    # volume vs avg to flag (3x normal)
STRIKE_CONC_PCT    = 0.50   # 50%+ of total volume on one strike
OTM_DEPTH_PCT      = 0.10   # 10%+ OTM to qualify as "far OTM"
MIN_VOLUME         = 500    # minimum contract volume to flag
MIN_NOTIONAL       = 50_000 # minimum dollar notional (volume × mid × 100)
PC_SKEW_THRESHOLD  = 3.0    # put/call or call/put ratio to flag
MAX_ALERTS         = 30     # max alerts per day
TG_ALERTS          = 10     # max alerts sent to Telegram
MAX_EXPIRATIONS    = 6      # scan nearest N expirations per ticker


# ─── Default universe: watchlist + high-activity names ──────────────────────
DEFAULT_UNIVERSE = [
    # Large-cap tech (high options volume)
    "AAPL", "NVDA", "TSLA", "AMD", "META", "AMZN", "MSFT", "GOOGL",
    "NFLX", "AVGO", "ARM", "SMCI",
    # High-IV / meme / momentum
    "MSTR", "COIN", "PLTR", "SOFI", "RIVN", "LCID", "HOOD",
    "DKNG", "RKLB", "RDDT", "IONQ", "AFRM",
    # Commodities / macro proxies
    "SLV", "GDX", "GLD", "TLT", "USO", "XLE",
    # Biotech (event-driven)
    "MRNA", "CRSP",
    # Financials
    "JPM", "GS", "BAC",
    # ETFs (broad flow signal)
    "SPY", "QQQ", "IWM", "XLF", "XBI",
]


@dataclass
class UoaAlert:
    """Single unusual options activity alert."""
    ticker: str
    alert_type: str        # VOL_OI_SPIKE | VOL_SURGE | STRIKE_CONC | OTM_FLOW | PC_SKEW
    side: str              # CALL | PUT
    strike: float
    expiry: str            # YYYY-MM-DD
    dte: int
    volume: int
    open_interest: int
    vol_oi_ratio: float
    implied_vol: float
    notional: float        # dollar value of flow
    moneyness: str         # ITM | ATM | OTM | FAR_OTM
    underlying_last: float
    option_price: float    # mid price per share (bid+ask)/2
    detail: str            # human-readable explanation
    severity: int          # 1-3 (1=notable, 2=significant, 3=extreme)

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker, "alert_type": self.alert_type,
            "side": self.side, "strike": self.strike,
            "expiry": self.expiry, "dte": self.dte,
            "volume": self.volume, "open_interest": self.open_interest,
            "vol_oi_ratio": round(self.vol_oi_ratio, 1),
            "implied_vol": round(self.implied_vol * 100, 1),
            "notional": round(self.notional),
            "moneyness": self.moneyness,
            "underlying_last": round(self.underlying_last, 2),
            "option_price": round(self.option_price, 2),
            "detail": self.detail, "severity": self.severity,
        }


def _classify_moneyness(strike: float, price: float, side: str) -> str:
    """Classify option moneyness."""
    if price <= 0:
        return "ATM"
    if side == "CALL":
        pct = (strike - price) / price
    else:  # PUT
        pct = (price - strike) / price

    if pct < -0.02:
        return "ITM"
    if pct < 0.02:
        return "ATM"
    if pct < OTM_DEPTH_PCT:
        return "OTM"
    return "FAR_OTM"


def _severity(vol_oi: float, volume: int, notional: float) -> int:
    """Rate alert severity 1-3."""
    score = 0
    if vol_oi >= 10:
        score += 2
    elif vol_oi >= 5:
        score += 1
    if volume >= 5000:
        score += 1
    if notional >= 500_000:
        score += 1
    if notional >= 2_000_000:
        score += 1
    return min(3, max(1, score))


def scan_ticker(ticker: str, logger) -> list[UoaAlert]:
    """Scan a single ticker's option chain for unusual activity."""
    import yfinance as yf

    try:
        yt = yf.Ticker(ticker)
        info = yt.info or {}
        price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
        expirations = yt.options
    except Exception as e:
        logger.debug(f"  {ticker}: chain fetch failed — {e}")
        return []

    if not expirations or price <= 0:
        return []

    today = date.today()
    alerts: list[UoaAlert] = []

    # Track total call/put volume across all expirations for P/C skew
    total_call_vol = 0
    total_put_vol = 0

    for exp_str in expirations[:MAX_EXPIRATIONS]:
        try:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            dte = (exp_date - today).days
            if dte < 3 or dte > 180:  # skip ≤2 DTE (day-trade noise)
                continue

            chain = yt.option_chain(exp_str)
        except Exception:
            continue

        for side_name, df in [("CALL", chain.calls), ("PUT", chain.puts)]:
            if df is None or df.empty:
                continue

            df = df.copy()
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(int)
            df["openInterest"] = pd.to_numeric(df["openInterest"], errors="coerce").fillna(0).astype(int)
            df["impliedVolatility"] = pd.to_numeric(df["impliedVolatility"], errors="coerce").fillna(0)
            df["bid"] = pd.to_numeric(df.get("bid", 0), errors="coerce").fillna(0)
            df["ask"] = pd.to_numeric(df.get("ask", 0), errors="coerce").fillna(0)
            df["mid"] = (df["bid"] + df["ask"]) / 2
            df.loc[df["mid"] <= 0, "mid"] = pd.to_numeric(
                df.get("lastPrice", 0), errors="coerce"
            ).fillna(0)

            # Accumulate for P/C skew
            side_vol = int(df["volume"].sum())
            if side_name == "CALL":
                total_call_vol += side_vol
            else:
                total_put_vol += side_vol

            total_exp_vol = int(df["volume"].sum())

            for _, row in df.iterrows():
                vol = int(row["volume"])
                oi = int(row["openInterest"])
                strike = float(row["strike"])
                iv = float(row["impliedVolatility"])
                mid = float(row["mid"])
                notional = vol * mid * 100

                if vol < MIN_VOLUME:
                    continue
                if notional < MIN_NOTIONAL:
                    continue

                vol_oi = vol / oi if oi > 0 else vol  # if OI=0, all volume is new
                moneyness = _classify_moneyness(strike, price, side_name)
                sev = _severity(vol_oi, vol, notional)

                # ── Check 1: Volume/OI spike ──
                if vol_oi >= VOL_OI_THRESHOLD:
                    alerts.append(UoaAlert(
                        ticker=ticker, alert_type="VOL_OI_SPIKE",
                        side=side_name, strike=strike, expiry=exp_str,
                        dte=dte, volume=vol, open_interest=oi,
                        vol_oi_ratio=vol_oi, implied_vol=iv,
                        notional=notional, moneyness=moneyness,
                        underlying_last=price, option_price=mid,
                        detail=f"Vol/OI {vol_oi:.1f}x — {vol:,} contracts vs {oi:,} OI "
                               f"(${notional:,.0f} notional)",
                        severity=sev,
                    ))

                # ── Check 2: Strike concentration ──
                if total_exp_vol > 0 and vol / total_exp_vol >= STRIKE_CONC_PCT:
                    conc_pct = vol / total_exp_vol * 100
                    alerts.append(UoaAlert(
                        ticker=ticker, alert_type="STRIKE_CONC",
                        side=side_name, strike=strike, expiry=exp_str,
                        dte=dte, volume=vol, open_interest=oi,
                        vol_oi_ratio=vol_oi, implied_vol=iv,
                        notional=notional, moneyness=moneyness,
                        underlying_last=price, option_price=mid,
                        detail=f"{conc_pct:.0f}% of {exp_str} {side_name.lower()} volume "
                               f"on ${strike:.0f} strike ({vol:,} of {total_exp_vol:,})",
                        severity=sev,
                    ))

                # ── Check 3: Far-OTM volume ──
                if moneyness == "FAR_OTM" and vol >= MIN_VOLUME * 2:
                    otm_pct = abs(strike - price) / price * 100
                    alerts.append(UoaAlert(
                        ticker=ticker, alert_type="OTM_FLOW",
                        side=side_name, strike=strike, expiry=exp_str,
                        dte=dte, volume=vol, open_interest=oi,
                        vol_oi_ratio=vol_oi, implied_vol=iv,
                        notional=notional, moneyness=moneyness,
                        underlying_last=price, option_price=mid,
                        detail=f"Far-OTM ({otm_pct:.1f}% away) {side_name.lower()} — "
                               f"{vol:,} contracts, ${notional:,.0f} notional",
                        severity=sev,
                    ))

    # ── Check 4: Put/Call skew across all expirations ──
    if total_call_vol > 0 and total_put_vol > 0:
        pc_ratio = total_put_vol / total_call_vol
        cp_ratio = total_call_vol / total_put_vol
        if pc_ratio >= PC_SKEW_THRESHOLD:
            alerts.append(UoaAlert(
                ticker=ticker, alert_type="PC_SKEW",
                side="PUT", strike=0, expiry="",
                dte=0, volume=total_put_vol, open_interest=0,
                vol_oi_ratio=0, implied_vol=0,
                notional=0, moneyness="",
                underlying_last=price, option_price=0,
                detail=f"Put/Call ratio {pc_ratio:.1f}x — {total_put_vol:,} puts vs "
                       f"{total_call_vol:,} calls. Heavy downside positioning.",
                severity=2 if pc_ratio >= 5 else 1,
            ))
        elif cp_ratio >= PC_SKEW_THRESHOLD:
            alerts.append(UoaAlert(
                ticker=ticker, alert_type="PC_SKEW",
                side="CALL", strike=0, expiry="",
                dte=0, volume=total_call_vol, open_interest=0,
                vol_oi_ratio=0, implied_vol=0,
                notional=0, moneyness="",
                underlying_last=price, option_price=0,
                detail=f"Call/Put ratio {cp_ratio:.1f}x — {total_call_vol:,} calls vs "
                       f"{total_put_vol:,} puts. Heavy upside positioning.",
                severity=2 if cp_ratio >= 5 else 1,
            ))

    # Deduplicate: if same strike+expiry+side has both VOL_OI_SPIKE and STRIKE_CONC,
    # keep only the highest-severity one
    seen = {}
    deduped = []
    for a in alerts:
        key = (a.ticker, a.side, a.strike, a.expiry)
        if a.alert_type == "PC_SKEW":
            deduped.append(a)  # always keep skew alerts
            continue
        existing = seen.get(key)
        if existing is None or a.severity > existing.severity:
            seen[key] = a
    deduped.extend(seen.values())

    return sorted(deduped, key=lambda a: (a.severity, a.notional), reverse=True)


def main() -> int:
    import yfinance as yf

    ap = argparse.ArgumentParser(description="Unusual Options Activity Scanner")
    ap.add_argument("--dry", action="store_true", help="Print only, no sheet/Telegram")
    ap.add_argument("--tickers", nargs="+", default=None, help="Override universe")
    args = ap.parse_args()

    logger = setup_logging("uoa-scan")
    logger.info("═══ Unusual Options Activity Scanner ═══")

    universe = args.tickers or DEFAULT_UNIVERSE
    logger.info(f"Scanning {len(universe)} tickers")

    all_alerts: list[UoaAlert] = []
    for i, ticker in enumerate(universe):
        try:
            alerts = scan_ticker(ticker, logger)
            if alerts:
                logger.info(f"  {ticker}: {len(alerts)} alerts "
                           f"(max severity {max(a.severity for a in alerts)})")
                all_alerts.extend(alerts)
            if (i + 1) % 10 == 0:
                logger.info(f"  ... scanned {i + 1}/{len(universe)}")
        except Exception as e:
            logger.debug(f"  {ticker}: scan error — {e}")

    all_alerts.sort(key=lambda a: (a.severity, a.notional), reverse=True)
    logger.info(f"Total: {len(all_alerts)} unusual activity alerts")

    # Top alerts summary
    for a in all_alerts[:10]:
        sev_icon = ["", "⚡", "🔥", "🚨"][a.severity]
        logger.info(f"  {sev_icon} {a.ticker:6} {a.alert_type:12} {a.side:4} "
                    f"${a.strike:.0f} {a.expiry} — {a.detail}")

    if args.dry:
        logger.info("DRY RUN — no sheet write or Telegram push")
        return 0

    # ── Write to sheet ──
    today_iso = date.today().isoformat()
    try:
        from src.sync import load_env
        from src import sheets as sh
        from src import schema as S
        load_env()
        client = sh.authenticate()
        sh.ensure_headers(client, S.UoaAlertRow.TAB_NAME, S.UoaAlertRow.HEADERS)

        rows = []
        for a in all_alerts[:MAX_ALERTS]:
            row = S.UoaAlertRow(
                date=today_iso,
                ticker=a.ticker,
                alert_type=a.alert_type,
                side=a.side,
                strike=a.strike,
                expiry=a.expiry,
                dte=a.dte,
                volume=a.volume,
                open_interest=a.open_interest,
                vol_oi_ratio=a.vol_oi_ratio,
                implied_vol=a.implied_vol,
                notional=a.notional,
                moneyness=a.moneyness,
                underlying_last=a.underlying_last,
                option_price=a.option_price,
                severity=a.severity,
                detail=a.detail,
            )
            rows.append(row.to_row())
        sh.append_rows(client, S.UoaAlertRow.TAB_NAME, rows)
        logger.info(f"  ✓ Wrote {len(rows)} rows to {S.UoaAlertRow.TAB_NAME}")
    except Exception as e:
        logger.error(f"  Sheet write failed: {e}")

    # ── Telegram push ──
    try:
        from src import telegram as tg
        tg_result = tg.ping_unusual_options(
            date=today_iso,
            alerts=[a.to_dict() for a in all_alerts[:TG_ALERTS]],
            total_scanned=len(universe),
            total_alerts=len(all_alerts),
            pwa_url="https://xynkro.github.io/CasaaFinance/",
        )
        if tg_result.get("skipped"):
            logger.info(f"  Telegram: skipped ({tg_result['skipped']})")
        else:
            logger.info("  ✓ UOA alerts sent to Telegram")
    except Exception as e:
        logger.warning(f"  Telegram UOA push failed: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
