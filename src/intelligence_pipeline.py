"""Compose existing intelligence modules into a fail-closed event result."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.advice_gate import build_explainability_card, evaluate_advice_gate
from src.cross_asset_risk import detect_contagion
from src.external_event_pipeline import build_external_events
from src.external_event_risk import cluster_external_events, notification_decision, score_prstk_risk
from src.financialjuice_contract import normalize_financialjuice
from src.market_impact_graph import build_market_impact_graph
from src.market_regime import classify_regime
from src.stress_scenarios import run_stress_scenario
from src.surprise_engine import calculate_surprise

_PRIVATE_EXTERNAL_FIELDS = frozenset({
    "body", "raw_body", "attachments", "data", "local_path", "private_url",
    "gmail_message_id", "gmail_thread_id", "gmail_history_id", "message_id",
    "thread_id", "sender", "recipient", "email_address",
})


def _sanitize_external_record(record: dict[str, Any], *, source: str | None = None) -> dict[str, Any]:
    """Keep direct callers on the same privacy boundary as the file loader."""
    safe = {key: value for key, value in record.items() if key not in _PRIVATE_EXTERNAL_FIELDS}
    if source:
        safe["source"] = source
        safe["content_origin"] = source
    return safe


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
    external_observations: Iterable[dict[str, Any]] | None = None,
    macro: dict[str, Any] | None = None,
    regime_factors: dict[str, float | int | None] | None = None,
    contagion_observations: dict[str, dict[str, float | None]] | None = None,
    stress_exposures: dict[str, float] | None = None,
    candidate: dict[str, Any] | None = None,
    advice_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    observations_list = list(observations or [])
    external_input: list[dict[str, Any]] = []
    for observation in external_observations or []:
        if not isinstance(observation, dict):
            continue
        items = observation.get("items")
        if isinstance(items, list) and items:
            for item in items:
                if isinstance(item, dict):
                    external_input.append(_sanitize_external_record(
                        item,
                        source=str(observation.get("source") or observation.get("content_origin") or "financialjuice"),
                    ))
        else:
            # An unresolved compound envelope contains only private transport
            # metadata and must not become an event or leak its message ID.
            if str(observation.get("parse_status") or "").casefold() == "compound_unresolved":
                continue
            external_input.append(_sanitize_external_record(observation))
    external_clusters = cluster_external_events(external_input)
    external_risk: dict[str, Any] = {"status": "not_available", "clusters": []}
    if external_clusters:
        first_cluster = external_clusters[0]
        first_observation = (first_cluster.get("observations") or [{}])[0]
        financialjuice = None
        if str(first_observation.get("source") or first_observation.get("content_origin") or "").casefold() == "financialjuice":
            financialjuice = normalize_financialjuice({
                **first_observation,
                "event_type": first_cluster.get("event_type"),
                "cross_source_count": first_cluster.get("cross_source_count"),
                "official_confirmed": event.get("official_confirmed"),
                "market_sync_confirmed": event.get("market_sync_confirmed"),
            })
        score = score_prstk_risk(
            first_cluster,
            official_confirmed=bool(event.get("official_confirmed")),
            market_sync_confirmed=bool(event.get("market_sync_confirmed")),
            vendor_importance=event.get("vendor_importance"),
        )
        external_risk = {
            "status": "eligible" if score["notification_eligible"] else "pending",
            "cluster": first_cluster,
            "clusters": external_clusters,
            "score": score,
            "notification": notification_decision(score),
        }
        if financialjuice is not None:
            external_risk["financialjuice"] = financialjuice
        unified_events: list[dict[str, Any]] = []
        for item in external_input:
            if not isinstance(item, dict):
                continue
            unified_events.extend(build_external_events(
                item,
                source_observations=[other for other in external_input if other is not item],
                official_confirmed=bool(event.get("official_confirmed")),
                market_sync_confirmed=bool(event.get("market_sync_confirmed")),
            ))
        external_risk["unified_events"] = unified_events
        external_risk["financialjuice_items"] = [
            {
                "item_id": item.get("item_id"),
                "event_cluster_key": item.get("event_cluster_key"),
                "vendor_importance": item.get("vendor_importance"),
                "headline": item.get("original_headline") or item.get("headline"),
            }
            for item in external_input
            if str(item.get("source") or item.get("content_origin") or "").casefold() == "financialjuice"
        ]
        external_risk["pending_reasons"] = sorted({
            reason
            for unified in unified_events
            for reason in unified.get("pending_reasons", [])
        })
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
    backtest_contract = context.get("backtest_release_contract") or candidate_row.get("backtest_release_contract")
    backtest_release = context.get("backtest_release") or candidate_row.get("backtest_release")
    advice = evaluate_advice_gate({
        "data_quality_ok": bool(context.get("data_quality_ok")),
        "quote_stale": bool(context.get("quote_stale", True)),
        "crosscheck_ok": synchronized and bool(context.get("crosscheck_ok")),
        "backtest_release": backtest_release,
        "backtest_release_contract": backtest_contract,
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
        "external_event_risk": external_risk,
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
