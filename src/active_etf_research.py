"""Research-only allocation math for the active-ETF module.

The module deliberately produces a review plan, never orders or broker calls.
It is intended to make the assumptions behind a paper portfolio reproducible.
"""
from __future__ import annotations

from typing import Any


NOTICE = "僅供研究與風險教育；不構成買賣建議，也不會執行交易。"


def _number(candidate: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = candidate.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _weight_cap(count: int, configured_cap: float) -> float:
    """Keep the 100% allocation rule coherent when one or two records exist."""
    return 1 / count if count <= 2 else configured_cap


def _capped_inverse_risk_weights(risks: list[float], cap: float) -> list[float]:
    """Allocate inverse-risk scores with a repeated cap-and-redistribute pass."""
    if not risks:
        return []
    raw = [1 / risk for risk in risks]
    weights = [0.0] * len(raw)
    active = set(range(len(raw)))
    remaining = 1.0

    while active:
        denominator = sum(raw[index] for index in active)
        provisional = {index: remaining * raw[index] / denominator for index in active}
        capped = [index for index, value in provisional.items() if value > cap + 1e-12]
        if not capped:
            for index, value in provisional.items():
                weights[index] = value
            break
        for index in capped:
            weights[index] = cap
            remaining -= cap
            active.remove(index)

    return weights


def build_research_allocation(
    candidates: list[dict[str, Any]],
    capital: float = 100_000,
    max_weight_per_stock: float = 0.45,
) -> dict[str, Any]:
    """Create a paper-allocation review from Price Action reference prices.

    Valid candidates need a positive reference price and a lower structural stop.
    The resulting ``capital_amount`` is a research allocation amount only; it is
    intentionally not converted into orders or share quantities.
    """
    if capital <= 0:
        raise ValueError("研究本金必須大於 0")
    if not 0 < max_weight_per_stock <= 1:
        raise ValueError("單一標的權重上限必須介於 0 與 1")

    valid: list[dict[str, Any]] = []
    skipped: list[str] = []
    for candidate in candidates:
        ticker = str(candidate.get("ticker") or candidate.get("Ticker") or "未命名標的")
        price = _number(candidate, "reference_price", "entry_price", "Entry_Price", "close", "Close")
        stop = _number(candidate, "stop_loss", "dynamic_stop_loss", "Dynamic_Stop_Loss")
        if price is None or stop is None or price <= 0 or stop < 0 or stop >= price:
            skipped.append(ticker)
            continue
        valid.append({"ticker": ticker, "name": candidate.get("name") or candidate.get("Name") or ticker, "price": price, "stop": stop})

    if not valid:
        return {
            "status": "沒有可計算的研究候選",
            "notice": NOTICE,
            "allocations": [],
            "skipped": skipped,
        }

    risks = [(item["price"] - item["stop"]) / item["price"] for item in valid]
    cap = _weight_cap(len(valid), max_weight_per_stock)
    weights = _capped_inverse_risk_weights(risks, cap)
    allocations = []
    for item, risk, weight in zip(valid, risks, weights):
        allocations.append({
            "ticker": item["ticker"],
            "name": item["name"],
            "reference_price": round(item["price"], 2),
            "structural_stop": round(item["stop"], 2),
            "risk_percent": round(risk * 100, 2),
            "weight_percent": round(weight * 100, 2),
            "capital_amount": round(capital * weight, 2),
        })

    return {
        "status": "研究配置草案",
        "notice": NOTICE,
        "capital": capital,
        "max_weight_percent": round(cap * 100, 2),
        "allocations": allocations,
        "skipped": skipped,
        "rebalance_timing": "每日收盤後檢視，次一交易日再由使用者自行決定是否採用。",
    }
