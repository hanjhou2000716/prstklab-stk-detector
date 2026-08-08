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
    surprise = calculate_surprise(**(macro or {})) if macro is not None else {"status": "not_provided", "market_direction": "not_determined"}
    synchronized = any(path.get("confidence", 0) >= 0.8 for path in graph.get("paths", []))
    regime = classify_regime(regime_factors or {})
    contagion = detect_contagion(contagion_observations or {})
    stress = [
        run_stress_scenario(name, stress_exposures or {})
        for name in ("nasdaq_shock", "semiconductor_shock", "energy_supply_shock")
    ]
    context = advice_context or {}
    advice = evaluate_advice_gate({
        "data_quality_ok": bool(context.get("data_quality_ok")),
        "quote_stale": bool(context.get("quote_stale", True)),
        "crosscheck_ok": synchronized and bool(context.get("crosscheck_ok")),
        "backtest_release": context.get("backtest_release"),
        "candidate_data_gap": bool(context.get("candidate_data_gap", True)),
        "policy_valid": bool(context.get("policy_valid")),
        "risk_profile_known": bool(context.get("risk_profile_known")),
        "general_research": bool(context.get("general_research", True)),
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
