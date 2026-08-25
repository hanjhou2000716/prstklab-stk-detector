"""Build an auditable, fail-closed contract for walk-forward results."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from src.strategy_registry import validate_strategy_release


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
    metric_fields = {
        "trade_count", "average_net_return_percent", "win_rate_percent",
        "total_cost_drag_percent", "cost_drag_percent", "cumulative_net_return_percent",
        "annualized_return_percent", "annualized_volatility_percent", "sharpe",
        "sortino", "max_drawdown_percent", "calmar", "turnover_proxy",
    }
    performance_summary: dict[str, dict[str, dict[str, Any]]] = {}
    for strategy, result in strategies.items():
        summaries = result.get("summary") if isinstance(result, dict) else None
        if not isinstance(summaries, dict):
            continue
        performance_summary[strategy] = {
            str(window): {key: value for key, value in metrics.items() if key in metric_fields}
            for window, metrics in summaries.items()
            if isinstance(metrics, dict)
        }
    identity = {
        "market": market,
        "audit": audit,
        "methodology": report.get("methodology"),
        "strategy_registry": strategy_registry,
        "performance_summary": performance_summary,
        "survivorship_audit": {
            "status": (audit or {}).get("status"),
            "snapshot_dates": list((audit or {}).get("snapshot_dates") or []),
        },
    }
    release_id = f"backtest-{hashlib.sha256(_canonical(identity)).hexdigest()[:16]}"
    # Bind every registry row to the exact release that produced it.  Without
    # this field the strategy registry validator must keep candidates
    # observation-only even when the walk-forward study itself passed.
    for row in strategy_registry:
        row["backtest_release"] = release_id
    registry_errors: list[str] = []
    for index, row in enumerate(strategy_registry):
        for error in validate_strategy_release(row):
            registry_errors.append(f"strategy_registry[{index}]: {error}")
    if registry_errors:
        reasons.extend(registry_errors)
    eligible = not reasons and report.get("status") == "complete"
    return {
        "backtest_release": release_id,
        "market": market,
        "publication_state": "ready" if eligible else "blocked",
        "publish_eligible": eligible,
        "blocking_reasons": reasons,
        "strategy_registry": strategy_registry,
        "strategy_registry_validation": {
            "status": "pass" if not registry_errors else "failed",
            "errors": registry_errors,
        },
        "performance_summary": performance_summary,
        "survivorship_audit": identity["survivorship_audit"],
        "research_only": True,
    }
