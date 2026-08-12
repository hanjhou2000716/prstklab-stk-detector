"""Compose existing intelligence modules into a fail-closed event result."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.advice_gate import build_explainability_card, evaluate_advice_gate
from src.cross_asset_risk import detect_contagion
from src.market_impact_graph import build_market_impact_graph
from src.market_regime import classify_regime
from src.stress_scenarios import run_stress_scenario
from src.surprise_engine import calculate_surprise


def _market_reaction(observations: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Expose the observed first reaction without inferring causality.

    A macro surprise and a price move are separate observations.  Keeping the
    quotes in the intelligence payload makes the evidence visible to the
    Mini App while leaving confirmation to the explicit cross-check policy.
    """
    quotes: list[dict[str, Any]] = []
    for item in observations:
        ticker = item.get("ticker") or item.get("symbol")
        change = item.get("change_percent")
        if not ticker or not isinstance(change, (int, float)):
            continue
        quotes.append({
            "ticker": str(ticker),
            "change_percent": float(change),
            "freshness": item.get("freshness") or item.get("data_status"),
            "source_url": item.get("source_url"),
        })
    return {
        "status": "observed_only" if quotes else "not_available",
        "direction_confirmed": False,
        "quotes": quotes,
        "reason": (
            "市場第一反應僅為觀測，尚未完成事件與價格的同向核對。"
            if quotes else "本輪沒有可用的事件後市場報價。"
        ),
    }


def build_intelligence_context(
    event: dict[str, Any], observations: Iterable[dict[str, Any]] | None = None, *,
    macro: dict[str, Any] | None = None,
    regime_factors: dict[str, float | int | None] | None = None,
    contagion_observations: dict[str, dict[str, float | None]] | None = None,
    stress_exposures: dict[str, float] | None = None,
    candidate: dict[str, Any] | None = None,
    advice_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    observations_list = list(observations or [])
    graph = build_market_impact_graph(event, observations_list)
    surprise: dict[str, Any]
    if macro is None:
        surprise = {"status": "not_provided", "market_direction": "not_determined"}
    else:
        # Keep partial producer payloads observable.  The calculator requires
        # explicit expected/actual keys so a missing value becomes
        # `insufficient_evidence`, never a TypeError or an invented result.
        surprise = calculate_surprise(
            expected=macro.get("expected"),
            actual=macro.get("actual"),
            previous=macro.get("previous"),
            historical_std=macro.get("historical_std"),
            revision=macro.get("revision"),
            release_time=macro.get("release_time"),
            source_url=macro.get("source_url"),
        )
    reaction = _market_reaction(observations_list)
    surprise["market_reaction"] = reaction
    synchronized = any(path.get("confidence", 0) >= 0.8 for path in graph.get("paths", []))
    regime = classify_regime(regime_factors or {})
    contagion = detect_contagion(contagion_observations or {})
    stress = [
        run_stress_scenario(name, stress_exposures or {})
        for name in ("nasdaq_shock", "semiconductor_shock", "energy_supply_shock")
    ]
    context = advice_context or {}
    candidate_row = candidate if isinstance(candidate, dict) else {}
    advice = evaluate_advice_gate({
        "data_quality_ok": bool(context.get("data_quality_ok")),
        "quote_stale": bool(context.get("quote_stale", True)),
        "crosscheck_ok": synchronized and bool(context.get("crosscheck_ok")),
        "backtest_release": context.get("backtest_release"),
        "backtest_release_contract": context.get("backtest_release_contract"),
        "strategy": candidate_row.get("strategy") or candidate_row.get("strategy_id") or context.get("strategy"),
        "candidate_data_gap": bool(context.get("candidate_data_gap", True)),
        "policy_valid": bool(context.get("policy_valid")),
        "risk_profile_known": bool(context.get("risk_profile_known")),
        "general_research": bool(context.get("general_research", True)),
        "evidence": context.get("evidence") or observations_list,
        "invalidation_condition": context.get("invalidation_condition") or event.get("invalidation_condition"),
        "alternative_scenario": context.get("alternative_scenario"),
        "horizon": context.get("horizon"),
        "confidence": context.get("confidence"),
    })
    return {
        "market_impact_graph": graph,
        "macro_surprise": surprise,
        "market_sync_confirmed": synchronized,
        "evidence_status": "confirmed" if synchronized else "insufficient_evidence",
        "advice_gate": "observation_only" if not advice["allowed"] else "research_only",
        "advice_gate_detail": advice,
        "market_regime": regime,
        "contagion": contagion,
        "stress_scenarios": stress,
        "explainability": build_explainability_card(candidate, advice) if candidate else None,
        "disclaimer": "僅供公開資訊整理與教育性觀察，不構成投資建議。",
    }
