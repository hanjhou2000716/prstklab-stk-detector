"""Run the Price Action research scanner on the public representative watchlist."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from src.price_action import PriceActionResearchScanner


def download_daily_bars(symbol: str) -> pd.DataFrame:
    """Download recent completed daily OHLCV bars from a public provider."""
    import yfinance as yf

    data = yf.download(
        symbol, period="6mo", interval="1d", auto_adjust=False,
        progress=False, threads=False,
    )
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    return data[["Open", "High", "Low", "Close", "Volume"]].dropna()


def build_price_action_snapshot(
    watchlist: tuple[dict[str, str], ...],
    scanner: PriceActionResearchScanner | None = None,
    downloader: Callable[[str], pd.DataFrame] = download_daily_bars,
    histories: dict[str, pd.DataFrame] | None = None,
) -> dict[str, Any]:
    """Return public-watchlist research results without creating a trade instruction."""
    scanner = scanner or PriceActionResearchScanner()
    candidates: list[dict[str, Any]] = []
    errors: list[str] = []
    for item in watchlist:
        try:
            daily = histories[item["symbol"]] if histories and item["symbol"] in histories else downloader(item["symbol"])
            result = scanner.scan_daily(daily)
            if result:
                candidates.append({
                    "ticker": item["ticker"],
                    "name": item["name"],
                    "market": item["market"],
                    **result,
                })
        except Exception:
            errors.append(f"{item['ticker']} 結構資料暫時無法取得")
    candidates.sort(key=lambda candidate: candidate["turnover"], reverse=True)
    candidates = candidates[:5]
    status = "已有結構研究候選" if candidates else "本次無符合裸 K 結構的代表標的"
    return {
        "status": status,
        "notice": "僅供公開市場結構研究與風險觀察，不構成買賣建議。",
        "candidates": candidates,
        "errors": errors,
    }
