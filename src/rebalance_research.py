"""Manual-input, research-only daily rebalance review rules."""
from __future__ import annotations

from typing import Any


NOTICE = "僅供收盤後研究檢視；不讀取帳戶、不產生下單或調整指令。"


def _weight_map(items: dict[str, Any]) -> dict[str, float]:
    weights: dict[str, float] = {}
    for ticker, value in items.items():
        try:
            weight = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{ticker} 權重不是數值") from exc
        if weight < 0:
            raise ValueError(f"{ticker} 權重不可小於 0")
        weights[str(ticker)] = weight
    if weights and abs(sum(weights.values()) - 100) > 0.1:
        raise ValueError("現有權重合計必須為 100%")
    return weights


def _target_map(allocations: list[dict[str, Any]]) -> dict[str, float]:
    return _weight_map({str(item.get("ticker")): item.get("weight_percent") for item in allocations if item.get("ticker")})


def review_rebalance(
    current_weights: dict[str, Any],
    target_allocations: list[dict[str, Any]],
    *,
    drift_threshold_percent: float = 10,
    regime: dict[str, Any] | None = None,
    atr_ratio_threshold: float = 1.5,
    correlation_change_threshold: float = 0.2,
) -> dict[str, Any]:
    """Flag a manual review only for configured drift or regime changes.

    ``current_weights`` must be manually supplied percentages.  The function
    intentionally has no brokerage, holdings, or account-data dependency.
    """
    if drift_threshold_percent < 0 or atr_ratio_threshold <= 0 or correlation_change_threshold < 0:
        raise ValueError("再平衡門檻必須為合理的非負數")
    current = _weight_map(current_weights)
    target = _target_map(target_allocations)
    if not target:
        return {"status": "沒有目標研究配置", "notice": NOTICE, "should_review": False, "reasons": [], "drifts": []}
    if not current:
        return {"status": "尚未提供現有權重", "notice": NOTICE, "should_review": False, "reasons": ["需手動提供現有權重後才能比較漂移"], "drifts": []}

    drifts = []
    for ticker in sorted(set(current) | set(target)):
        present, desired = current.get(ticker, 0.0), target.get(ticker, 0.0)
        drifts.append({"ticker": ticker, "current_weight_percent": round(present, 2), "target_weight_percent": round(desired, 2), "drift_percent": round(abs(present - desired), 2)})
    maximum = max(item["drift_percent"] for item in drifts)
    reasons = [f"權重漂移最高 {maximum}%（門檻 {drift_threshold_percent}%）"] if maximum >= drift_threshold_percent else []

    regime = regime or {}
    incomplete = []
    try:
        atr_ratio = float(regime["current_atr"]) / float(regime["baseline_atr"])
        if atr_ratio >= atr_ratio_threshold:
            reasons.append(f"ATR 比率 {round(atr_ratio, 2)} 倍（門檻 {atr_ratio_threshold} 倍）")
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        incomplete.append("ATR")
    try:
        correlation_change = abs(float(regime["current_correlation"]) - float(regime["baseline_correlation"]))
        if correlation_change >= correlation_change_threshold:
            reasons.append(f"相關性變化 {round(correlation_change, 3)}（門檻 {correlation_change_threshold}）")
    except (KeyError, TypeError, ValueError):
        incomplete.append("相關性")

    return {
        "status": "需人工再平衡檢視" if reasons else "目前未達再平衡研究門檻",
        "notice": NOTICE,
        "should_review": bool(reasons),
        "reasons": reasons,
        "drifts": drifts,
        "max_weight_drift_percent": maximum,
        "incomplete_regime_inputs": incomplete,
        "review_timing": "每日收盤後檢視；如需採用，由使用者於下一交易日自行決定。",
    }
