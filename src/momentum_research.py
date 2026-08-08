"""Price-and-volatility momentum research ranking for a bounded public watchlist."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

from src.research_contract import latest_quote_context
from src.research_scan import download_daily_bars

WEIGHTS = {
    "hist_vol": 29.08, "bb_width": 19.33, "p_ma60": 10.39,
    "trend": 7.67, "p_ma20": 7.26, "p_bb_upper": 5.09, "roc10": 4.25,
}


def features(df: pd.DataFrame) -> dict[str, float] | None:
    if len(df) < 61:
        return None
    close = df["Close"]
    ma5, ma20, ma60 = close.rolling(5).mean().iloc[-1], close.rolling(20).mean().iloc[-1], close.rolling(60).mean().iloc[-1]
    std20 = close.rolling(20).std().iloc[-1]
    upper = ma20 + 2 * std20
    if any(pd.isna(value) or value == 0 for value in (ma5, ma20, ma60, upper)):
        return None
    quote = latest_quote_context(df)
    if quote is None:
        return None
    current = float(quote["close"])
    volume = df["Volume"].astype(float)
    volume_ma20 = float(volume.rolling(20).mean().iloc[-1])
    prior_20_high = float(close.iloc[-21:-1].max())
    daily_range = ((df["High"] - df["Low"]) / close.replace(0, np.nan)).astype(float)
    recent_range = float(daily_range.iloc[-5:].mean())
    earlier_range = float(daily_range.iloc[-20:-5].mean())
    volume_ratio = None if volume_ma20 <= 0 or pd.isna(volume_ma20) else float(volume.iloc[-1] / volume_ma20)
    contraction = None if pd.isna(earlier_range) or earlier_range <= 0 else float(recent_range / earlier_range)
    breakout_20 = current >= prior_20_high
    vcp_breakout = bool(
        contraction is not None
        and contraction <= 0.85
        and breakout_20
        and volume_ratio is not None
        and volume_ratio >= 1.2
    )
    new_high_days = [days for days in (3, 5, 20) if current >= float(close.iloc[-days:].max())]
    labels = []
    if vcp_breakout:
        labels.append("VCP收斂突破")
    if new_high_days:
        labels.append(f"{max(new_high_days)}日新高")
    if volume_ratio is not None and volume_ratio >= 1.5:
        labels.append("量能放大")
    return {
        **quote,
        "above_ma5": current >= ma5,
        "hist_vol": float(close.pct_change().rolling(20).std().iloc[-1] * np.sqrt(252) * 100),
        "bb_width": float((4 * std20 / ma20) * 100), "p_ma60": float((current / ma60 - 1) * 100),
        "trend": float((ma5 / ma60 - 1) * 100), "p_ma20": float((current / ma20 - 1) * 100),
        "p_bb_upper": float((current / upper - 1) * 100), "roc10": float((current / close.iloc[-11] - 1) * 100),
        "volume_ratio": volume_ratio,
        "range_contraction": contraction,
        "breakout_20": breakout_20,
        "vcp_breakout": vcp_breakout,
        "new_high_days": new_high_days,
        "signal_labels": labels,
    }


def build_momentum_snapshot(
    watchlist: tuple[dict[str, str], ...], downloader: Callable[[str], pd.DataFrame] = download_daily_bars, histories: dict[str, pd.DataFrame] | None = None
) -> dict[str, Any]:
    """Rank available watchlist records; output remains research-only."""
    rows, errors = [], []
    for item in watchlist:
        try:
            daily = histories[item["symbol"]] if histories and item["symbol"] in histories else downloader(item["symbol"])
            result = features(daily)
            if result:
                rows.append({"ticker": item["ticker"], "name": item["name"], **result})
        except Exception:
            errors.append(f"{item['ticker']} 動能資料暫時無法取得")
    if not rows:
        return {"status": "資料暫時無法取得", "notice": "僅供動能研究，不構成買賣建議。", "candidates": [], "errors": errors}
    frame = pd.DataFrame(rows)
    # The original system requires its hard 5MA defence before percentile
    # ranking.  The score therefore compares only investable-liquidity rows.
    frame = frame[frame["above_ma5"]].copy()
    if frame.empty:
        return {"status": "無符合動能防守條件", "notice": "本輪沒有收盤站上 5 日均線的公開研究候選。", "candidates": [], "errors": errors}
    score = sum(frame[name].rank(pct=True) * weight for name, weight in WEIGHTS.items()) / sum(WEIGHTS.values()) * 100
    frame["score"] = score.round(1)
    frame = frame.sort_values(["score", "vcp_breakout", "volume_ratio"], ascending=[False, False, False]).head(5)
    candidates = frame[[
        "ticker", "name", "close", "previous_close", "change_percent", "turnover", "as_of", "score", "roc10",
        "volume_ratio", "range_contraction", "breakout_20", "vcp_breakout", "new_high_days", "signal_labels",
    ]].round({"close": 2, "previous_close": 2, "change_percent": 2, "turnover": 2, "roc10": 2, "volume_ratio": 2, "range_contraction": 3}).to_dict("records")
    return {"status": "動能研究排序", "notice": "價格與波動特徵的相對排名；僅供研究，不構成買賣建議。", "candidates": candidates, "errors": errors}
