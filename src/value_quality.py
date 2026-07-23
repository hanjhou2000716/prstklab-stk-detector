"""Public fundamental-quality research with explicit missing-data handling."""
from __future__ import annotations
from typing import Any

def normalize(info: dict[str, Any]) -> dict[str, float | None]:
    def number(key: str) -> float | None:
        value = info.get(key)
        return float(value) if isinstance(value, (int, float)) else None
    return {"roe": number("returnOnEquity"), "pe": number("trailingPE"), "dividend_yield": number("dividendYield"), "net_income": number("netIncomeToCommon")}

def quality_score(metrics: dict[str, float | None]) -> int:
    return sum([
        (metrics["net_income"] or 0) > 500_000_000,
        (metrics["roe"] or 0) >= .17,
        (metrics["dividend_yield"] or 0) >= .02,
    ])

def build_value_snapshot(watchlist: tuple[dict[str, str], ...]) -> dict[str, Any]:
    import yfinance as yf
    candidates, errors = [], []
    for item in watchlist:
        try:
            metrics = normalize(yf.Ticker(item["symbol"]).info)
            candidates.append({"ticker": item["ticker"], "name": item["name"], "score": quality_score(metrics), **metrics})
        except Exception:
            errors.append(f"{item['ticker']} 財務資料暫時無法取得")
    candidates.sort(key=lambda row: row["score"], reverse=True)
    return {"status": "價值品質研究", "notice": "公開財務欄位可能因市場與公司而缺漏；僅供研究，不構成買賣建議。", "candidates": candidates[:5], "errors": errors}
