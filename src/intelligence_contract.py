"""Fail-closed validation for evidence shown in a public briefing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]


def _schema_errors(document: dict[str, Any]) -> list[str]:
    schema = json.loads((ROOT / "schemas" / "intelligence.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    return [f"intelligence schema: {error.json_path} {error.message}" for error in validator.iter_errors(document)]


def validate_intelligence(document: dict[str, Any]) -> list[str]:
    """Validate cross-field evidence relationships without inferring causality."""
    if not isinstance(document, dict):
        return ["briefing.intelligence must be an object"]
    errors = _schema_errors(document)
    graph = document.get("market_impact_graph")
    paths = graph.get("paths") if isinstance(graph, dict) else []
    paths = paths if isinstance(paths, list) else []
    market_sync = document.get("market_sync_confirmed") is True
    evidence_status = str(document.get("evidence_status") or "")
    if market_sync and evidence_status != "confirmed":
        errors.append("market_sync_confirmed=true requires evidence_status=confirmed")
    if evidence_status == "confirmed" and not market_sync:
        errors.append("evidence_status=confirmed requires market_sync_confirmed=true")
    synchronized_paths = 0
    for index, path in enumerate(paths):
        if not isinstance(path, dict):
            continue
        path_name = f"briefing.intelligence.market_impact_graph.paths[{index}]"
        path_sync = path.get("market_sync") is True
        raw_evidence = path.get("evidence")
        evidence: list[Any] = raw_evidence if isinstance(raw_evidence, list) else []
        has_market_evidence = any(isinstance(item, dict) and item.get("type") == "market_sync" for item in evidence)
        if path_sync:
            synchronized_paths += 1
            if not has_market_evidence:
                errors.append(f"{path_name}: market_sync=true requires market_sync evidence")
        confidence = path.get("confidence")
        if isinstance(confidence, (int, float)) and float(confidence) >= 0.8 and (not path_sync or not has_market_evidence):
            errors.append(f"{path_name}: high confidence requires synchronized market evidence")
    if market_sync and synchronized_paths == 0:
        errors.append("market_sync_confirmed=true requires at least one synchronized graph path")
    regime = document.get("market_regime")
    if isinstance(regime, dict):
        contributions = regime.get("factor_contributions")
        if isinstance(contributions, dict) and regime.get("factor_count") != len(contributions):
            errors.append("market_regime.factor_count must equal factor_contributions length")
        if regime.get("evidence_sufficient") is False and regime.get("evidence_status") != "insufficient_evidence":
            errors.append("insufficient market-regime evidence must be labeled explicitly")
    contagion = document.get("contagion")
    if isinstance(contagion, dict) and contagion.get("contagion") is True:
        signals = contagion.get("confirmed_signals")
        if contagion.get("evidence_sufficient") is not True or not isinstance(signals, list) or len(signals) < 2:
            errors.append("contagion=true requires at least two confirmed signals")
    scenarios = document.get("stress_scenarios")
    if isinstance(scenarios, list):
        for index, scenario in enumerate(scenarios):
            if isinstance(scenario, dict) and scenario.get("non_predictive") is not True:
                errors.append(f"briefing.intelligence.stress_scenarios[{index}] must be non_predictive")
    binding = document.get("production_binding")
    if isinstance(binding, dict) and binding.get("fail_closed") is True and document.get("advice_gate") != "observation_only":
        errors.append("fail_closed production binding requires advice_gate=observation_only")
    return errors
