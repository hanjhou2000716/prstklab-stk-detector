"""Confirmed public-data Smart Money observations for three-dimensional resonance."""

from __future__ import annotations

import pandas as pd

SMART_MONEY_RULES = (
    ("absorption", "爆量吸收／長下影", 35),
    ("liquidity_sweep", "跌破前低後收回", 30),
    ("positive_alpha", "相對大盤 Alpha > 0", 20),
    ("volatility_expansion", "True Range > 1.1×ATR", 15),
)


def smart_money_conditions(df: pd.DataFrame, benchmark: pd.DataFrame | None) -> dict[str, bool] | None:
    """Check the four agreed Smart Money observations from completed daily bars."""
    required = {"Open", "High", "Low", "Close", "Volume"}
    if len(df) < 21 or not required.issubset(df.columns):
        return None

    current = df.iloc[-1]
    previous = df.iloc[-2]
    close = df["Close"].astype(float)
    volume = df["Volume"].astype(float)
    high, low = df["High"].astype(float), df["Low"].astype(float)
    true_range = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr14 = true_range.rolling(14).mean().iloc[-1]
    volume_ma20 = volume.rolling(20).mean().iloc[-1]
    body = abs(float(current["Close"]) - float(current["Open"]))
    lower_shadow = min(float(current["Open"]), float(current["Close"])) - float(current["Low"])

    alpha_verified = False
    if isinstance(benchmark, pd.DataFrame) and len(benchmark) >= 2 and "Close" in benchmark.columns:
        benchmark_close = benchmark["Close"].dropna().astype(float)
        if len(benchmark_close) >= 2 and float(benchmark_close.iloc[-2]) > 0 and float(close.iloc[-2]) > 0:
            alpha_verified = float(close.iloc[-1] / close.iloc[-2] - 1) > float(benchmark_close.iloc[-1] / benchmark_close.iloc[-2] - 1)

    return {
        "absorption": bool(
            (not pd.isna(volume_ma20) and volume_ma20 > 0 and float(current["Volume"]) >= float(volume_ma20) * 1.2)
            or lower_shadow > max(body * 1.5, 1e-9)
        ),
        "liquidity_sweep": bool(float(current["Low"]) < float(previous["Low"]) and float(current["Close"]) > float(previous["Low"])),
        "positive_alpha": alpha_verified,
        "volatility_expansion": bool(not pd.isna(atr14) and atr14 > 0 and float(true_range.iloc[-1]) > float(atr14) * 1.1),
    }


def smart_money_summary(conditions: dict[str, bool] | None) -> dict[str, object]:
    """Return ordered labels, transparent score and four-/three-rule tier."""
    if not conditions:
        return {"matched_labels": [], "count": 0, "score": 0, "tier": None}
    matched = [(label, weight) for key, label, weight in SMART_MONEY_RULES if conditions.get(key)]
    count = len(matched)
    return {
        "matched_labels": [label for label, _ in matched],
        "count": count,
        "score": sum(weight for _, weight in matched),
        "tier": "四項共振" if count == 4 else "三項備選" if count == 3 else None,
    }
