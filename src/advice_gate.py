"""Fail-closed gate and neutral scenario advice formatter."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


FAIL_MESSAGE = "目前資料不足，僅能列為觀察候選，暫不提供操作判斷。"


def evaluate_advice_gate(context: Mapping[str, Any]) -> dict[str, Any]:
    required = ("data_quality_ok", "freshness_ok", "sources_cross_checked", "backtest_valid", "candidate_complete", "policy_valid")
    missing = [key for key in required if context.get(key) is not True]
    return {"allowed": not missing, "missing": missing, "message": "allowed" if not missing else FAIL_MESSAGE}


def build_scenario_advice(context: Mapping[str, Any], *, horizon: str, thesis: str, evidence: Sequence[str], trigger: Sequence[str], invalidation: Sequence[str], risks: Sequence[str], confidence: str, alternative: str) -> dict[str, Any]:
    gate = evaluate_advice_gate(context)
    if not gate["allowed"]:
        return {"stance": "資料不足", "message": FAIL_MESSAGE, "gate": gate, "not_investment_advice": True}
    return {"stance": "觀察", "horizon": horizon, "thesis": thesis, "evidence": list(evidence),
            "trigger": list(trigger), "invalidation": list(invalidation), "key_risks": list(risks),
            "confidence": confidence, "alternative_scenario": alternative, "gate": gate,
            "not_investment_advice": True}


def add_counterargument(advice: Mapping[str, Any], *, strongest_counterargument: str, review_when: str) -> dict[str, Any]:
    result = dict(advice)
    result["counterargument"] = strongest_counterargument
    result["review_when"] = review_when
    if not strongest_counterargument or not review_when:
        result["confidence"] = "low"
    return result
