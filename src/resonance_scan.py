"""Bounded-watchlist adapter for three-dimensional resonance research."""
from __future__ import annotations

from typing import Any

from src.research_scan import download_daily_bars
from src.resonance_research import label, score_bars


def build_resonance_snapshot(watchlist: tuple[dict[str, str], ...], histories=None) -> dict[str, Any]:
    candidates, errors = [], []
    for item in watchlist:
        try:
            daily = histories[item["symbol"]] if histories and item["symbol"] in histories else download_daily_bars(item["symbol"])
            score = score_bars(daily)
            if score is not None and score < 56:
                candidates.append({"ticker": item["ticker"], "name": item["name"], "score": score, "status": label(score)})
        except Exception:
            errors.append(f"{item['ticker']} 共振資料暫時無法取得")
    def score_key(item: dict[str, object]) -> float:
        value = item.get("score")
        return float(value) if isinstance(value, (int, float)) else 0.0
    candidates.sort(key=score_key)
    return {"status": "三維共振研究", "notice": "僅呈現 FGI 低於 56 的研究候選，不構成買賣建議。", "candidates": candidates[:10], "errors": errors}
