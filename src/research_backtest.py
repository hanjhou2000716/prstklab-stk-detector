"""Transparent, research-only return calculations with stated trading costs.

This module evaluates hypothetical completed price paths.  It deliberately has
no broker integration, no order creation, and no live trading capability.
"""
from __future__ import annotations

from typing import Any


NOTICE = "歷史研究結果不代表未來表現；僅供回測與風險教育，不構成買賣建議。"

# Default assumptions taken from the project specification.  They are explicit
# so a later study can change them rather than silently assuming zero cost.
MARKET_COSTS = {
    "taiwan": {"commission_rate": 0.001425, "slippage_rate": 0.005},
    "us": {"commission_rate": 0.00005, "slippage_rate": 0.005},
}


def _positive_number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def calculate_hypothetical_return(
    entry_price: float,
    exit_price: float,
    market: str,
    *,
    commission_rate: float | None = None,
    slippage_rate: float | None = None,
) -> dict[str, float]:
    """Calculate a round-trip return after side-specific fee and slippage.

    Slippage worsens the hypothetical entry and exit price.  Commission is
    charged once on each side.  The function returns percentages, not orders.
    """
    entry = _positive_number(entry_price)
    exit_ = _positive_number(exit_price)
    if entry is None or exit_ is None:
        raise ValueError("進出參考價格必須大於 0")
    if market not in MARKET_COSTS:
        raise ValueError("市場必須是 taiwan 或 us")
    defaults = MARKET_COSTS[market]
    commission = defaults["commission_rate"] if commission_rate is None else commission_rate
    slippage = defaults["slippage_rate"] if slippage_rate is None else slippage_rate
    if commission < 0 or slippage < 0:
        raise ValueError("手續費與滑價不可小於 0")

    raw_return = exit_ / entry - 1
    entry_outlay = entry * (1 + slippage) * (1 + commission)
    exit_proceeds = exit_ * (1 - slippage) * (1 - commission)
    net_return = exit_proceeds / entry_outlay - 1
    return {
        "gross_return_percent": round(raw_return * 100, 4),
        "net_return_percent": round(net_return * 100, 4),
        "cost_drag_percent": round((raw_return - net_return) * 100, 4),
        "entry_outlay_per_unit": round(entry_outlay, 6),
        "exit_proceeds_per_unit": round(exit_proceeds, 6),
    }


def evaluate_hypothetical_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate supplied completed research records, skipping invalid inputs."""
    results: list[dict[str, Any]] = []
    skipped: list[str] = []
    for trade in trades:
        ticker = str(trade.get("ticker") or "未命名標的")
        try:
            result = calculate_hypothetical_return(
                trade.get("entry_price"), trade.get("exit_price"), str(trade.get("market")),
                commission_rate=trade.get("commission_rate"), slippage_rate=trade.get("slippage_rate"),
            )
        except (TypeError, ValueError):
            skipped.append(ticker)
            continue
        results.append({"ticker": ticker, "market": trade["market"], **result})

    count = len(results)
    average = sum(item["net_return_percent"] for item in results) / count if count else None
    wins = sum(item["net_return_percent"] > 0 for item in results)
    return {
        "status": "研究回測成本摘要" if results else "沒有可評估的研究紀錄",
        "notice": NOTICE,
        "cost_assumptions": MARKET_COSTS,
        "trades": results,
        "summary": {
            "count": count,
            "average_net_return_percent": round(average, 4) if average is not None else None,
            "net_positive_count": wins,
        },
        "skipped": skipped,
    }
