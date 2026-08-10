"""Build an auditable, fail-closed contract for walk-forward results."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _parameter_hash(strategy: str, config: dict[str, Any]) -> str:
    strategy_config = (config.get("strategy_parameters") or {}).get(strategy, {})
    return hashlib.sha256(_canonical(strategy_config)).hexdigest()[:16]


def build_backtest_release(
    report: dict[str, Any], *, market: str, config: dict[str, Any], code_commit: str = "local",
) -> dict[str, Any]:
    """Return registry metadata and a publication decision for one study.

    A computed metric is not automatically a publishable backtest. Any
    survivorship failure or unresolved point-in-time data gap keeps the result
    explicitly research-only, so downstream advice gates cannot treat it as a
    valid strategy release.
    """
    reasons: list[str] = []
    audit = report.get("survivorship_audit")
    if not isinstance(audit, dict) or audit.get("status") != "pass":
        reasons.append("survivorship audit did not pass")
    strategies = report.get("strategies")
    if not isinstance(strategies, dict) or not strategies:
        reasons.append("no strategy results supplied")
        strategies = {}
    for strategy, result in strategies.items():
        if not isinstance(result, dict):
            reasons.append(f"{strategy}: result is not an object")
            continue
        gaps = result.get("data_gaps")
        if isinstance(gaps, list) and gaps:
            reasons.append(f"{strategy}: unresolved data gaps")

    universe_version = hashlib.sha256(_canonical((audit or {}).get("snapshot_dates", []))).hexdigest()[:16]
    data_version = str(config.get("data_version") or "point-in-time-archive")
    strategy_registry = [
        {
            "strategy_id": strategy,
            "strategy_version": str((config.get("strategy_versions") or {}).get(strategy) or "unversioned"),
            "parameter_hash": _parameter_hash(strategy, config),
            "universe_version": universe_version,
            "data_version": data_version,
            "code_commit": code_commit,
        }
        for strategy in sorted(strategies)
    ]
    identity = {
        "market": market,
        "audit": audit,
        "methodology": report.get("methodology"),
        "strategy_registry": strategy_registry,
    }
    release_id = f"backtest-{hashlib.sha256(_canonical(identity)).hexdigest()[:16]}"
    eligible = not reasons and report.get("status") == "complete"
    return {
        "backtest_release": release_id,
        "market": market,
        "publication_state": "ready" if eligible else "blocked",
        "publish_eligible": eligible,
        "blocking_reasons": reasons,
        "strategy_registry": strategy_registry,
        "research_only": True,
    }
