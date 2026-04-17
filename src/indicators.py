"""
indicators.py — Compute 15+ technical indicators from daily OHLCV data.

Pure-Python (pandas-backed) computations so they're testable and
version-controlled, unlike the XLSM where formulas shift with row moves.

Public API:
  compute_indicators(df) -> dict       # df: pandas DataFrame with OHLCV cols
  classify_trend(close, sma20, sma50, sma200) -> str
  fetch_ohlcv(tickers, period="1y") -> dict[ticker, DataFrame]
"""
from __future__ import annotations

import math
from typing import Any

import pandas as pd


def _last(series: pd.Series, default: float = 0.0) -> float:
    """Safe last-value extraction."""
    try:
        v = series.iloc[-1]
        if pd.isna(v):
            return default
        return float(v)
    except (IndexError, ValueError, TypeError):
        return default


def classify_trend(close: float, sma20: float, sma50: float, sma200: float) -> str:
    """Trend classification from price vs SMAs."""
    if sma20 == 0 or sma50 == 0:
        return "Unknown"
    if close > sma20 > sma50 > sma200 > 0:
        return "Strong Uptrend"
    if close > sma20 > sma50:
        return "Uptrend"
    if close < sma20 < sma50 < sma200:
        return "Strong Downtrend"
    if close < sma20 < sma50:
        return "Downtrend"
    return "Sideways"


def _detect_crossover(line: pd.Series, signal: pd.Series, lookback: int = 3) -> str:
    """Detect MACD-style crossover in last `lookback` bars."""
    if len(line) < lookback + 1 or len(signal) < lookback + 1:
        return "none"
    # Recent cross: line crossed signal within lookback
    for i in range(-1, -lookback - 1, -1):
        if pd.isna(line.iloc[i]) or pd.isna(signal.iloc[i]) or pd.isna(line.iloc[i - 1]) or pd.isna(signal.iloc[i - 1]):
            continue
        prev_below = line.iloc[i - 1] < signal.iloc[i - 1]
        now_above = line.iloc[i] > signal.iloc[i]
        if prev_below and now_above:
            return "bullish"
        if (not prev_below) and (not now_above):
            return "bearish"
    return "none"


def _detect_candle(df: pd.DataFrame) -> str:
    """Classify most recent candle."""
    if len(df) < 2:
        return "none"
    o, h, l, c = df["Open"].iloc[-1], df["High"].iloc[-1], df["Low"].iloc[-1], df["Close"].iloc[-1]
    prev_c = df["Close"].iloc[-2]
    body = abs(c - o)
    total_range = h - l
    if total_range == 0:
        return "doji"
    body_ratio = body / total_range
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l

    # Doji: very small body
    if body_ratio < 0.1:
        return "doji"
    # Hammer / inverted hammer — long lower wick, small body at top
    if lower_wick > 2 * body and upper_wick < body:
        return "hammer_bullish" if c > prev_c else "hammer_neutral"
    # Shooting star — long upper wick, small body at bottom
    if upper_wick > 2 * body and lower_wick < body:
        return "shooting_star_bearish"
    # Engulfing (check vs prev candle)
    prev_o = df["Open"].iloc[-2]
    prev_body_dir = "up" if prev_c > prev_o else "down"
    this_body_dir = "up" if c > o else "down"
    if this_body_dir != prev_body_dir and body > abs(prev_c - prev_o) * 1.2:
        return "engulfing_bullish" if this_body_dir == "up" else "engulfing_bearish"
    # Large body — directional
    if body_ratio > 0.7:
        return "strong_bullish" if c > o else "strong_bearish"
    return "neutral"


def _detect_divergence(close: pd.Series, rsi: pd.Series, lookback: int = 20) -> str:
    """Simple price/RSI divergence detection."""
    if len(close) < lookback or len(rsi) < lookback:
        return "none"
    recent = close.iloc[-lookback:]
    recent_rsi = rsi.iloc[-lookback:]
    # Bearish divergence: price makes higher high, RSI makes lower high
    try:
        price_hh = recent.iloc[-1] >= recent.max() * 0.98
        rsi_lh = recent_rsi.iloc[-1] < recent_rsi.max() * 0.9
        if price_hh and rsi_lh:
            return "bearish"
        # Bullish: price makes lower low, RSI makes higher low
        price_ll = recent.iloc[-1] <= recent.min() * 1.02
        rsi_hl = recent_rsi.iloc[-1] > recent_rsi.min() * 1.1
        if price_ll and rsi_hl:
            return "bullish"
    except (ValueError, ZeroDivisionError):
        pass
    return "none"


def compute_indicators(df: pd.DataFrame) -> dict[str, Any]:
    """
    Compute all indicators for a single ticker. df must have columns:
    Open, High, Low, Close, Volume — daily bars, chronological.
    """
    out: dict[str, Any] = {}
    if len(df) < 20:
        return out

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    vol = df["Volume"]

    out["close"] = _last(close)
    out["prev_close"] = _last(close.iloc[:-1]) if len(close) > 1 else 0.0

    # ----- Moving averages -----
    out["sma_20"] = _last(close.rolling(20).mean())
    out["sma_50"] = _last(close.rolling(50).mean())
    out["sma_200"] = _last(close.rolling(200).mean()) if len(close) >= 200 else 0.0
    out["ema_9"] = _last(close.ewm(span=9, adjust=False).mean())
    out["ema_12"] = _last(close.ewm(span=12, adjust=False).mean())
    out["ema_26"] = _last(close.ewm(span=26, adjust=False).mean())

    # Trend classification
    out["trend"] = classify_trend(out["close"], out["sma_20"], out["sma_50"], out["sma_200"])

    # ----- RSI 14 (Wilder's) -----
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    rsi = 100 - (100 / (1 + rs))
    out["rsi_14"] = _last(rsi, default=50.0)

    # ----- MACD 12/26/9 -----
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    macd_signal = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = macd_line - macd_signal
    out["macd_line"] = _last(macd_line)
    out["macd_signal"] = _last(macd_signal)
    out["macd_hist"] = _last(macd_hist)
    out["macd_cross"] = _detect_crossover(macd_line, macd_signal, lookback=3)

    # ----- Bollinger Bands 20, 2σ -----
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_upper = sma20 + 2 * std20
    bb_lower = sma20 - 2 * std20
    bb_width = (bb_upper - bb_lower) / sma20
    out["bb_upper"] = _last(bb_upper)
    out["bb_lower"] = _last(bb_lower)
    denom = (_last(bb_upper) - _last(bb_lower)) or 1e-10
    out["bb_pct_b"] = round((_last(close) - _last(bb_lower)) / denom, 3)
    out["bb_width"] = _last(bb_width)
    # Squeeze: bandwidth near recent minimum
    if len(bb_width) >= 60:
        recent_min = bb_width.rolling(60).min().iloc[-1]
        out["bb_squeeze"] = bool(_last(bb_width) < recent_min * 1.1)
    else:
        out["bb_squeeze"] = False

    # ----- Stochastic %K, %D (14, 3) -----
    period = 14
    lowest_low = low.rolling(period).min()
    highest_high = high.rolling(period).max()
    k_range = (highest_high - lowest_low).replace(0, 1e-10)
    k = 100 * (close - lowest_low) / k_range
    d = k.rolling(3).mean()
    out["stoch_k"] = _last(k, default=50.0)
    out["stoch_d"] = _last(d, default=50.0)

    # ----- Williams VIX Fix (22) -----
    # WVF = ((max_close_22 - low) / max_close_22) * 100
    max_close_22 = close.rolling(22).max()
    wvf = ((max_close_22 - low) / max_close_22.replace(0, 1e-10)) * 100
    out["wvf"] = _last(wvf)
    # Market bottom signal: WVF exceeds its own upper band
    if len(wvf.dropna()) >= 22:
        wvf_mean = wvf.rolling(22).mean()
        wvf_std = wvf.rolling(22).std()
        wvf_upper = wvf_mean + 2 * wvf_std
        out["wvf_bottom"] = bool(_last(wvf) > _last(wvf_upper))
    else:
        out["wvf_bottom"] = False

    # ----- VWAP 10-day (daily approximation using HLC/3) -----
    typical = (high + low + close) / 3
    vwap = (typical * vol).rolling(10).sum() / vol.rolling(10).sum().replace(0, 1e-10)
    out["vwap_10"] = _last(vwap)

    # ----- ATR 14 -----
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    out["atr_14"] = _last(atr)

    # ----- Volume -----
    avg_vol_20 = vol.rolling(20).mean()
    out["vol_avg_20"] = _last(avg_vol_20)
    out["vol_today"] = _last(vol)
    out["vol_ratio"] = round(_last(vol) / max(_last(avg_vol_20), 1), 2)
    out["vol_spike"] = bool(_last(vol) > 1.5 * _last(avg_vol_20))
    # Bullish/bearish spike: direction of today's candle
    if out["vol_spike"]:
        out["vol_spike_type"] = "bullish" if out["close"] > out["prev_close"] else "bearish"
    else:
        out["vol_spike_type"] = "none"

    # ----- Fibonacci retracements from 60-day swing -----
    if len(high) >= 60:
        window = 60
    else:
        window = len(high)
    swing_high = float(high.iloc[-window:].max())
    swing_low = float(low.iloc[-window:].min())
    rng = swing_high - swing_low if swing_high > swing_low else 1e-10
    out["swing_high"] = swing_high
    out["swing_low"] = swing_low
    out["fib_0236"] = round(swing_high - rng * 0.236, 4)
    out["fib_0382"] = round(swing_high - rng * 0.382, 4)
    out["fib_050"] = round(swing_high - rng * 0.5, 4)
    out["fib_0618"] = round(swing_high - rng * 0.618, 4)
    out["fib_0764"] = round(swing_high - rng * 0.764, 4)

    # Resistance/support: nearest Fib level above/below current price
    fib_levels = [
        out["fib_0236"], out["fib_0382"], out["fib_050"],
        out["fib_0618"], out["fib_0764"], out["swing_high"], out["swing_low"],
    ]
    above = [f for f in fib_levels if f > out["close"]]
    below = [f for f in fib_levels if f < out["close"]]
    out["resistance"] = min(above) if above else out["swing_high"]
    out["support"] = max(below) if below else out["swing_low"]

    # ----- Candle pattern -----
    out["candle_pattern"] = _detect_candle(df)

    # ----- Divergence -----
    out["divergence"] = _detect_divergence(close, rsi)

    # ----- Catalyst proxy: recent vol spike vs baseline -----
    returns = close.pct_change()
    if len(returns) >= 60:
        recent_std = float(returns.iloc[-5:].std())
        baseline_std = float(returns.iloc[-60:].std())
        out["catalyst_flag"] = bool(recent_std > 2 * baseline_std)
        out["vol_regime"] = "elevated" if recent_std > 1.5 * baseline_std else "normal"
    else:
        out["catalyst_flag"] = False
        out["vol_regime"] = "normal"

    # ----- Annualized realized volatility -----
    if len(returns.dropna()) >= 20:
        daily_vol = float(returns.iloc[-60:].std()) if len(returns) >= 60 else float(returns.std())
        out["volatility_annual"] = round(daily_vol * math.sqrt(252), 4)
    else:
        out["volatility_annual"] = 0.0

    # ----- Momentum -----
    if len(close) >= 6:
        out["momentum_5d"] = round((float(close.iloc[-1]) - float(close.iloc[-6])) / float(close.iloc[-6]) * 100, 2)
    else:
        out["momentum_5d"] = 0.0
    if len(close) >= 21:
        out["momentum_20d"] = round((float(close.iloc[-1]) - float(close.iloc[-21])) / float(close.iloc[-21]) * 100, 2)
    else:
        out["momentum_20d"] = 0.0

    return out


def fetch_ohlcv(tickers: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
    """Batch-download OHLCV for tickers (already Yahoo-formatted)."""
    import yfinance as yf

    result: dict[str, pd.DataFrame] = {}
    if not tickers:
        return result

    data = yf.download(tickers, period=period, progress=False, threads=True, group_by="ticker")
    if data.empty:
        return {t: pd.DataFrame() for t in tickers}

    for t in tickers:
        try:
            if len(tickers) == 1:
                df = data.copy()
            else:
                df = data[t].copy()
            df = df.dropna(subset=["Close"]).copy()
            result[t] = df
        except (KeyError, AttributeError):
            result[t] = pd.DataFrame()

    return result
