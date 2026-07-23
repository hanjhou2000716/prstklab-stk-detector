"""Price-and-volatility momentum research ranking for a bounded public watchlist."""

from __future__ import annotations

from typing import Any, Callable

import numpy as np
import pandas as pd

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
    current = float(close.iloc[-1])
    return {
        "close": current, "above_ma5": current >= ma5,
        "hist_vol": float(close.pct_change().rolling(20).std().iloc[-1] * np.sqrt(252) * 100),
        "bb_width": float((4 * std20 / ma20) * 100), "p_ma60": float((current / ma60 - 1) * 100),
        "trend": float((ma5 / ma60 - 1) * 100), "p_ma20": float((current / ma20 - 1) * 100),
        "p_bb_upper": float((current / upper - 1) * 100), "roc10": float((current / close.iloc[-11] - 1) * 100),
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
    score = sum(frame[name].rank(pct=True) * weight for name, weight in WEIGHTS.items()) / sum(WEIGHTS.values()) * 100
    frame["score"] = score.round(1)
    frame = frame[frame["above_ma5"]].sort_values("score", ascending=False).head(10)
    candidates = frame[["ticker", "name", "close", "score", "roc10"]].round({"close": 2, "roc10": 2}).to_dict("records")
    return {"status": "動能研究排序", "notice": "價格與波動特徵的相對排名；僅供研究，不構成買賣建議。", "candidates": candidates, "errors": errors}
