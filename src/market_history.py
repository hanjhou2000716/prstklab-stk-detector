"""One public OHLCV download shared by research modules during a refresh."""
from __future__ import annotations
import pandas as pd
from src.research_scan import download_daily_bars

def load_watchlist_history(watchlist: tuple[dict[str, str], ...]) -> tuple[dict[str, pd.DataFrame], list[str]]:
    history, errors = {}, []
    for item in watchlist:
        try: history[item["symbol"]] = download_daily_bars(item["symbol"])
        except Exception: errors.append(f"{item['ticker']} 歷史資料暫時無法取得")
    return history, errors
