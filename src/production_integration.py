"""Bind research intelligence to production provenance without guessing.

The feature modules pre-date the release pipeline and can be useful even when
an immutable release has not been published yet.  This module is the narrow
contract between those modules and the production snapshot: it adds explicit
binding state, quality counts, and instrument identity while preserving the
fail-closed behaviour of the existing advice gate.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.instrument_master import InstrumentMaster
from src.strategy_registry import validate_strategy_release

PROVENANCE_FIELDS = (
    "release_id",
    "snapshot_id",
    "observation_id",
    "source_tier",
    "source_url",
    "fetched_at",
    "published_at",
    "freshness",
    "data_quality_score",
    "policy_version",
)


def _first(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _quality_score(observations: list[dict[str, Any]]) -> int:
    """Return a conservative 0-100 score from observable metadata only."""
    if not observations:
        return 0
    scores: list[float] = []
    for item in observations:
        value = item.get("data_quality_score")
        if isinstance(value, (int, float)):
            scores.append(float(value))
            continue
        status = str(item.get("data_status") or item.get("freshness") or "").lower()
        if status in {"live", "fresh", "recent_close", "ok"}:
            scores.append(100.0)
        elif status in {"stale", "delayed", "close_only"}:
            scores.append(50.0)
        elif status in {"unavailable", "failed", "invalid"}:
            scores.append(0.0)
        else:
            scores.append(25.0)
    return max(0, min(100, round(sum(scores) / len(scores))))


def summarize_observations(observations: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Summarize quality without treating missing data as a safe market."""
    rows = [item for item in observations if isinstance(item, dict)]
    counts = {"live": 0, "recent_close": 0, "stale": 0, "unavailable": 0, "unknown": 0}
    for item in rows:
        status = str(item.get("freshness") or item.get("data_status") or "unknown").lower()
        if status in {"live", "fresh"}:
            counts["live"] += 1
        elif status in {"recent_close", "close_only"}:
            counts["recent_close"] += 1
        elif status in {"stale", "delayed"}:
            counts["stale"] += 1
        elif status in {"unavailable", "failed", "invalid"}:
            counts["unavailable"] += 1
        else:
            counts["unknown"] += 1
    if counts["unavailable"] or counts["stale"]:
        state = "degraded"
    elif counts["live"] and counts["recent_close"]:
        state = "mixed"
    elif counts["live"]:
        state = "live"
    elif counts["recent_close"]:
        state = "close_only"
    else:
        state = "unavailable"
    return {"count": len(rows), "counts": counts, "overall_state": state, "data_quality_score": _quality_score(rows)}


def annotate_instruments(
    observations: Iterable[dict[str, Any]], master: InstrumentMaster | None = None,
) -> list[dict[str, Any]]:
    """Attach identity metadata; unknown tickers remain unknown, never guessed."""
    registry = master or InstrumentMaster()
    result: list[dict[str, Any]] = []
    for item in observations:
        row = dict(item)
        ticker = row.get("ticker") or row.get("symbol")
        if ticker:
            try:
                instrument = registry.resolve(str(ticker), market=row.get("market"))
            except (KeyError, ValueError):
                row["instrument_resolution"] = "unknown"
            else:
                row["instrument_id"] = instrument.instrument_id
                row["asset_type"] = instrument.asset_type
                row["instrument_timezone"] = instrument.timezone
                row["instrument_resolution"] = "resolved"
        else:
            row["instrument_resolution"] = "missing_ticker"
        result.append(row)
    return result


def bind_strategy_provenance(candidate: dict[str, Any] | None) -> dict[str, Any]:
    """Only unlock a strategy binding when a real backtest release is present."""
    row = candidate or {}
    required = ("strategy_version", "data_version", "backtest_release")
    missing = [key for key in required if not row.get(key)]
    registry = row.get("strategy_registry")
    registry_errors: list[str] = []
    contract_errors: list[str] = []
    contract = row.get("backtest_release_contract")
    if contract is not None:
        if not isinstance(contract, dict):
            contract_errors.append("backtest_release_contract must be an object")
        else:
            if contract.get("publication_state") != "ready" or contract.get("publish_eligible") is not True:
                contract_errors.append("backtest_release_contract is not publishable")
            if row.get("backtest_release") and contract.get("backtest_release") != row.get("backtest_release"):
                contract_errors.append("backtest_release does not match research contract")
    if registry is not None:
        registry_errors.extend(validate_strategy_release(registry))
        if isinstance(registry, dict):
            pairs = {
                "strategy_id": row.get("strategy") or row.get("strategy_id"),
                "strategy_version": row.get("strategy_version"),
                "data_version": row.get("data_version"),
                "backtest_release": row.get("backtest_release"),
            }
            for key, expected in pairs.items():
                if expected not in (None, "") and registry.get(key) != expected:
                    registry_errors.append(f"strategy_registry.{key} does not match candidate")
    if registry_errors:
        missing.append("strategy_registry")
    if contract_errors:
        missing.append("backtest_release_contract")
    return {
        "state": "production" if not missing else "observation_only",
        "strategy_id": row.get("strategy") or row.get("strategy_id"),
        "strategy_version": row.get("strategy_version"),
        "data_version": row.get("data_version"),
        "backtest_release": row.get("backtest_release"),
        "registry_state": "verified" if registry is not None and not registry_errors else "unverified" if registry is not None else "not_provided",
        "registry_errors": registry_errors,
        "contract_state": "verified" if contract is not None and not contract_errors else "unverified" if contract is not None else "not_provided",
        "contract_errors": contract_errors,
        "missing": missing,
        "reason": None if not missing else "invalid_strategy_registry" if registry_errors else "no_valid_backtest_release",
    }


def bind_intelligence(
    intelligence: dict[str, Any], *, snapshot: dict[str, Any] | None = None,
    observations: Iterable[dict[str, Any]] = (), candidate: dict[str, Any] | None = None,
    policy_version: str | None = None,
) -> dict[str, Any]:
    """Add an auditable production binding to an existing intelligence result."""
    source = snapshot or {}
    rows = annotate_instruments(observations)
    quality = summarize_observations(rows)
    provenance = {
        "release_id": _first(source, "release_id"),
        "snapshot_id": _first(source, "snapshot_id", "market_snapshot_id"),
        "observation_id": _first(source, "observation_id"),
        "source_tier": _first(source, "source_tier"),
        "source_url": _first(source, "source_url"),
        "fetched_at": _first(source, "fetched_at", "generated_at"),
        "published_at": _first(source, "published_at"),
        "freshness": _first(source, "freshness", "overall_state"),
        "data_quality_score": quality["data_quality_score"],
        "policy_version": policy_version or _first(source, "policy_version"),
    }
    missing = [key for key, value in provenance.items() if value in (None, "")]
    bound = dict(intelligence)
    bound["production_binding"] = {
        "state": "production" if not missing else "observation_only",
        "provenance": provenance,
        "missing_fields": missing,
        "quality": quality,
        "strategy": bind_strategy_provenance(candidate),
        "fail_closed": bool(missing) or quality["overall_state"] in {"degraded", "unavailable"},
    }
    # Keep the existing advice gate conservative if the release is not bound.
    if missing or quality["overall_state"] in {"degraded", "unavailable"}:
        bound["advice_gate"] = "observation_only"
    return bound
