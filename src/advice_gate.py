"""Safety gate for contextual, evidence-backed research language."""

from __future__ import annotations

from typing import Any

BLOCKING_REASONS = {
    "data_quality", "stale_quote", "missing_crosscheck", "no_backtest_release",
    "invalid_backtest_release", "candidate_data_gap", "unknown_risk_profile",
    "invalid_policy", "missing_evidence", "missing_invalidation",
}


def _backtest_is_valid(context: dict[str, Any]) -> tuple[bool, str | None]:
    """Require a ready, eligible P4 contract when structured data is supplied."""
    contract = context.get("backtest_release_contract")
    if contract is not None:
        if not isinstance(contract, dict):
            return False, "invalid_backtest_release"
        if contract.get("publication_state") != "ready" or contract.get("publish_eligible") is not True:
            return False, "invalid_backtest_release"
        return True, None
    if context.get("backtest_release"):
        # A bare release ID cannot prove publication state or eligibility. It
        # may come from a stale candidate row, so keep the advice gate closed
        # until the structured contract is attached.
        return False, "invalid_backtest_release"
    return False, "no_backtest_release"


def evaluate_advice_gate(context: dict[str, Any]) -> dict[str, Any]:
    """Return a decision-support permission, never a buy/sell instruction."""
    backtest_ok, backtest_reason = _backtest_is_valid(context)
    checks = {
        "data_quality": bool(context.get("data_quality_ok")),
        "fresh_quote": not bool(context.get("quote_stale")),
        "crosscheck": bool(context.get("crosscheck_ok")),
        "backtest": backtest_ok,
        "candidate_complete": not bool(context.get("candidate_data_gap")),
        "policy": bool(context.get("policy_valid")),
        "risk_context": bool(context.get("risk_profile_known") or context.get("general_research")),
    }
    reasons = [name for name, passed in checks.items() if not passed]
    if backtest_reason and backtest_reason not in reasons:
        reasons.append(backtest_reason)
    if not context.get("evidence"):
        reasons.append("missing_evidence")
    if not context.get("invalidation_condition"):
        reasons.append("missing_invalidation")
    reasons = list(dict.fromkeys(reasons))
    allowed = not reasons
    decision_support = {
        "horizon": context.get("horizon") or "research",
        "evidence": list(context.get("evidence") or []),
        "alternative_scenario": context.get("alternative_scenario") or "證據改變時，結論需重新評估。",
        "invalidation_condition": context.get("invalidation_condition"),
        "confidence": context.get("confidence") if allowed else "low",
        "actionable": False,
    }
    return {
        "allowed": allowed,
        "checks": checks,
        "blocking_reasons": reasons,
        "stance": "觀察" if not allowed else "條件式觀察",
        "message": "目前資料不足，僅能列為觀察候選，暫不提供操作判斷。" if not allowed else "資料條件達標，仍須檢視反方情境與失效條件。",
        "decision_support": decision_support,
    }



def build_explainability_card(candidate: dict[str, Any], gate: dict[str, Any]) -> dict[str, Any]:
    """Build a transparent candidate card without an unexplained total score."""
    def first(*keys: str) -> Any:
        for key in keys:
            value = candidate.get(key)
            if value not in (None, ""):
                return value
        return None

    strategy_binding = None
    if candidate.get("strategy_registry") is not None or any(
        candidate.get(key) not in (None, "")
        for key in ("strategy_version", "data_version", "backtest_release")
    ):
        from src.production_integration import bind_strategy_provenance

        strategy_binding = bind_strategy_provenance(candidate)
    card = {
        "ticker": candidate.get("ticker"),
        "name": candidate.get("name"),
        "strategy": candidate.get("strategy"),
        "passed_conditions": list(candidate.get("passed_conditions") or []),
        "failed_conditions": list(candidate.get("failed_conditions") or []),
        "data_completeness": candidate.get("data_completeness"),
        "risk_factors": list(candidate.get("risk_factors") or []),
        "liquidity": first("liquidity", "liquidity_metrics", "turnover"),
        "recent_events": list(first("recent_events", "events") or []),
        "valuation_position": first("valuation_position", "value_position", "pe"),
        "momentum_position": first("momentum_position", "momentum", "change_percent"),
        "quality_position": first("quality_position", "quality", "roe"),
        "evidence": list(candidate.get("evidence") or []),
        "alternative_scenario": candidate.get("alternative_scenario"),
        "horizon": candidate.get("horizon") or "research",
        "confidence": candidate.get("confidence"),
        "signal_date": candidate.get("signal_date"),
        "invalidation": candidate.get("invalidation"),
        "advice_gate": gate,
        "strategy_binding": strategy_binding,
        "disclaimer": "僅供公開資訊整理與教育性觀察，不構成投資建議。",
    }
    explainability: dict[str, Any] = {
        "passed_conditions": card["passed_conditions"],
        "failed_conditions": card["failed_conditions"],
        "data_completeness": card["data_completeness"],
        "risk_factors": card["risk_factors"],
        "liquidity": card["liquidity"],
        "recent_events": card["recent_events"],
        "valuation_position": card["valuation_position"],
        "momentum_position": card["momentum_position"],
        "quality_position": card["quality_position"],
        "evidence": card["evidence"],
        "signal_date": card["signal_date"],
        "invalidation": card["invalidation"],
    }
    if strategy_binding is not None:
        explainability["strategy_binding"] = strategy_binding
    card["explainability"] = explainability
    return card

