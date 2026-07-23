"""Research-only three-dimensional price, volatility, and flow scoring."""

from __future__ import annotations

import numpy as np
import pandas as pd


def percentile(series: pd.Series, window: int = 120) -> float:
    """Return the current value's historical percentile without a forecast."""
    history = series.dropna().iloc[-window:]
    if len(history) < window:
        return 50.0
    return round(float((history <= history.iloc[-1]).mean() * 100), 1)


def score_bars(df: pd.DataFrame) -> float | None:
    """Combine price position, volatility, turnover and short money-flow proxies."""
    if len(df) < 150 or not {"High", "Low", "Close", "Volume"}.issubset(df):
        return None
    close, volume = df["Close"], df["Volume"]
    ma60, ma20 = close.rolling(60).mean(), close.rolling(20).mean()
    bias = (close - ma60) / ma60 * 100
    rsi = 100 - 100 / (1 + close.diff().clip(lower=0).rolling(14).mean() / (-close.diff().clip(upper=0)).rolling(14).mean().replace(0, np.nan))
    pct_b = (close - (ma20 - 2 * close.rolling(20).std())) / (4 * close.rolling(20).std()).replace(0, np.nan)
    true_range = pd.concat([df["High"] - df["Low"], (df["High"] - close.shift()).abs(), (df["Low"] - close.shift()).abs()], axis=1).max(axis=1)
    atr_ratio = true_range.rolling(14).mean() / true_range.rolling(14).mean().rolling(60).mean()
    volume_ratio = volume / volume.rolling(20).mean()
    turnover = volume.rolling(5).mean()
    flow = (volume * close.diff()).rolling(5).sum()
    price = .6 * percentile(bias) + .4 * percentile(rsi)
    volatility = .5 * percentile(pct_b) + .5 * percentile(atr_ratio)
    participation = .5 * percentile(volume_ratio) + .5 * percentile(turnover)
    return round(.20 * price + .20 * volatility + .35 * percentile(flow) + .25 * participation, 1)


def label(score: float | None) -> str:
    if score is None: return "資料暫時無法取得"
    if score < 26: return "極度恐慌"
    if score < 45: return "恐慌"
    if score < 56: return "中立"
    if score < 75: return "貪婪"
    return "極度貪婪"
