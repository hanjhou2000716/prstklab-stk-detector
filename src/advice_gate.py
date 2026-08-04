"""Safety gate for contextual, evidence-backed research language."""

from __future__ import annotations

from typing import Any


BLOCKING_REASONS = {
    "data_quality", "stale_quote", "missing_crosscheck", "no_backtest_release", "candidate_data_gap", "unknown_risk_profile",
}


def evaluate_advice_gate(context: dict[str, Any]) -> dict[str, Any]:
    """Return a decision-support permission, never a buy/sell instruction."""
    checks = {
        "data_quality": bool(context.get("data_quality_ok")),
        "fresh_quote": not bool(context.get("quote_stale")),
        "crosscheck": bool(context.get("crosscheck_ok")),
        "backtest": bool(context.get("backtest_release")),
        "candidate_complete": not bool(context.get("candidate_data_gap")),
        "policy": bool(context.get("policy_valid")),
        "risk_context": bool(context.get("risk_profile_known") or context.get("general_research")),
    }
    reasons = [name for name, passed in checks.items() if not passed]
    allowed = not reasons
    return {
        "allowed": allowed,
        "checks": checks,
        "blocking_reasons": reasons,
        "stance": "觀察" if not allowed else "條件式觀察",
        "message": "目前資料不足，僅能列為觀察候選，暫不提供操作判斷。" if not allowed else "資料條件達標，仍須檢視反方情境與失效條件。",
    }


def build_explainability_card(candidate: dict[str, Any], gate: dict[str, Any]) -> dict[str, Any]:
    """Build a transparent candidate card without an unexplained total score."""
    return {
        "ticker": candidate.get("ticker"),
        "name": candidate.get("name"),
        "strategy": candidate.get("strategy"),
        "passed_conditions": list(candidate.get("passed_conditions") or []),
        "failed_conditions": list(candidate.get("failed_conditions") or []),
        "data_completeness": candidate.get("data_completeness"),
        "risk_factors": list(candidate.get("risk_factors") or []),
        "signal_date": candidate.get("signal_date"),
        "invalidation": candidate.get("invalidation"),
        "advice_gate": gate,
        "disclaimer": "僅供公開資訊整理與教育性觀察，不構成投資建議。",
    }

