"""Walk-forward Price Action research validation without future data leakage."""
from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd

from src.price_action import PriceActionResearchScanner, REQUIRED_COLUMNS
from src.research_backtest import NOTICE, calculate_hypothetical_return


def _validate_bars(bars: pd.DataFrame) -> pd.DataFrame:
    missing = REQUIRED_COLUMNS - set(bars.columns)
    if missing:
        raise ValueError(f"OHLCV 資料缺少欄位：{', '.join(sorted(missing))}")
    return bars.sort_index().dropna(subset=list(REQUIRED_COLUMNS))


def _resolve_path(bars: pd.DataFrame, entry_price: float, stop_price: float, max_holding_days: int) -> dict[str, Any]:
    """Resolve a 10R research path, flagging intraday ordering ambiguity."""
    risk = entry_price - stop_price
    target = entry_price + 10 * risk
    path = bars.iloc[:max_holding_days]
    for offset, (_, bar) in enumerate(path.iterrows()):
        hits_stop = float(bar["Low"]) <= stop_price
        hits_target = float(bar["High"]) >= target
        if hits_stop and hits_target:
            # OHLCV cannot tell which level happened first; use a conservative
            # loss assumption and surface it instead of inventing a sequence.
            return {"outcome": "同日停損／10R順序不明", "exit_price": stop_price, "holding_days": offset + 1, "ambiguous": True}
        if hits_stop:
            return {"outcome": "結構風險邊界觸發", "exit_price": stop_price, "holding_days": offset + 1, "ambiguous": False}
        if hits_target:
            return {"outcome": "達到10R研究目標", "exit_price": target, "holding_days": offset + 1, "ambiguous": False}
    return {
        "outcome": "樣本結束前未觸及邊界",
        "exit_price": float(path.iloc[-1]["Close"]),
        "holding_days": len(path),
        "ambiguous": False,
    }


def walk_forward_price_action(
    bars: pd.DataFrame,
    ticker: str,
    market: str,
    *,
    scanner: Any | None = None,
    min_history: int = 40,
    max_holding_days: int = 60,
    cooldown_days: int = 1,
) -> dict[str, Any]:
    """Replay a Price Action scanner using only data available at each signal.

    A detected signal is evaluated from the *next* bar's open. This avoids
    assuming an entry at a price only known after the signal bar closes.
    """
    if min_history < 2 or max_holding_days < 1 or cooldown_days < 0:
        raise ValueError("回測窗口、持有天數與冷卻天數必須合理")
    data = _validate_bars(bars)
    scanner = scanner or PriceActionResearchScanner()
    records: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    position = min_history - 1

    while position < len(data) - 1:
        signal_bars = data.iloc[: position + 1]
        signal = scanner.scan_daily(signal_bars)
        if not signal:
            position += 1
            continue
        entry_position = position + 1
        entry_price = float(data.iloc[entry_position]["Open"])
        stop_price = float(signal.get("reference_stop", 0))
        signal_date = str(data.index[position].date()) if hasattr(data.index[position], "date") else str(data.index[position])
        if entry_price <= stop_price or stop_price <= 0:
            skipped.append({"signal_date": signal_date, "reason": "下一根開盤已低於結構風險邊界"})
            position = entry_position + cooldown_days
            continue
        path = _resolve_path(data.iloc[entry_position:], entry_price, stop_price, max_holding_days)
        return_info = calculate_hypothetical_return(entry_price, path["exit_price"], market)
        records.append({
            "ticker": ticker,
            "signal_date": signal_date,
            "entry_date": str(data.index[entry_position].date()) if hasattr(data.index[entry_position], "date") else str(data.index[entry_position]),
            "entry_price": round(entry_price, 4),
            "structural_stop": round(stop_price, 4),
            "target_10r": round(entry_price + 10 * (entry_price - stop_price), 4),
            **path,
            **return_info,
        })
        position = entry_position + path["holding_days"] - 1 + cooldown_days

    outcomes = Counter(record["outcome"] for record in records)
    net_returns = [record["net_return_percent"] for record in records]
    return {
        "status": "Price Action 逐步回測研究" if records else "沒有可評估的 Price Action 研究訊號",
        "notice": NOTICE + " 訊號日只使用當時已完成 K 線，假設下一根 K 線開盤進行研究。",
        "ticker": ticker,
        "market": market,
        "trades": records,
        "summary": {
            "count": len(records),
            "average_net_return_percent": round(sum(net_returns) / len(net_returns), 4) if net_returns else None,
            "ambiguous_same_day_count": sum(record["ambiguous"] for record in records),
            "outcomes": dict(outcomes),
        },
        "skipped_signals": skipped,
    }
