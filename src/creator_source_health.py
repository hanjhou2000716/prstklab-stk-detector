"""Build privacy-safe source-health rows for optional Creator providers."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from src.creator_provider_registry import CREATOR_PROVIDERS, get_creator_provider
_FAILED_PARSE = {"parse_failed", "unsupported_template", "invalid_source", "duplicate"}


def _provider(record: dict[str, Any]) -> str:
    return str(record.get("content_origin") or record.get("source") or "").strip().lower()


def build_creator_source_health(
    records: Iterable[dict[str, Any]] | None,
    *,
    checked_at: datetime,
    enabled: bool,
    configured: bool,
    failures: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Return one bounded health row per known Creator provider.

    Creator feeds are optional enrichment.  Missing configuration is explicit
    and does not become a core market failure; an empty successful scan is
    ``no_event`` rather than ``failed``.
    """
    now = checked_at.isoformat()
    grouped: dict[str, list[dict[str, Any]]] = {name: [] for name in CREATOR_PROVIDERS}
    for item in records or []:
        if not isinstance(item, dict):
            continue
        name = _provider(item)
        if name in grouped:
            grouped[name].append(item)
    errors = failures or {}
    rows: list[dict[str, Any]] = []
    for provider in CREATOR_PROVIDERS:
        base: dict[str, Any] = {
            "key": f"creator_{provider}",
            "label": get_creator_provider(provider).display_name if get_creator_provider(provider) else f"Creator {provider}",
            "provider": provider,
            "role": "optional",
            "checked_at": now,
            "source_tier": "optional-enrichment",
            "source_url": None,
        }
        if not enabled or not configured:
            base.update({
                "status": "configuration_missing",
                "state": "configuration_required",
                "semantic_state": "configuration_missing",
                "creator_health": "configuration_missing",
                "provider_status": "not_configured",
                "issues": ["optional_creator_source_not_configured"],
            })
        elif provider in errors:
            base.update({
                "status": "failed",
                "state": "failed",
                "semantic_state": "failed",
                "creator_health": "failed",
                "provider_status": "runtime_error",
                "issues": [str(errors[provider])[:160]],
            })
        else:
            provider_records = grouped[provider]
            parse_failures = sum(
                str(item.get("parse_status") or "").strip().lower() in _FAILED_PARSE
                for item in provider_records
            )
            if parse_failures:
                base.update({
                    "status": "failed",
                    "state": "failed",
                    "semantic_state": "failed",
                    "creator_health": "parse_failed",
                    "provider_status": "parse_failed",
                    "issues": [f"{parse_failures} parser failure(s)"],
                })
            elif provider_records:
                base.update({
                    "status": "healthy",
                    "state": "healthy",
                    "semantic_state": "healthy",
                    "creator_health": "healthy",
                    "provider_status": "scan_complete",
                    "accepted_count": len(provider_records),
                    "last_success_at": now,
                    "issues": [],
                })
            else:
                base.update({
                    "status": "no_event",
                    "state": "no_event",
                    "semantic_state": "no_event",
                    "creator_health": "no_new_content",
                    "provider_status": "scan_complete",
                    "accepted_count": 0,
                    "last_success_at": now,
                    "issues": [],
                })
        rows.append(base)
    return rows


def merge_creator_sources(health: dict[str, Any], rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Merge optional Creator rows while preserving core source-health fields."""
    merged = dict(health)
    base_status = str(health.get("status") or "healthy")
    base_runtime_failures = int(health.get("runtime_failure_count") or 0)
    base_configuration = int(health.get("configuration_missing_count") or 0)
    sources = [dict(item) for item in (health.get("sources") or []) if isinstance(item, dict)]
    by_key = {str(item.get("key")): item for item in sources}
    for row in rows:
        if not isinstance(row, dict):
            continue
        by_key[str(row.get("key") or "creator_unknown")] = dict(row)
    sources = list(by_key.values())
    gaps = [
        item for item in sources
        if str(item.get("semantic_state") or item.get("state") or item.get("status") or "")
        in {"configuration_missing", "fallback_active", "stale", "partial", "failed", "critical"}
    ]
    creator_gaps = [item for item in gaps if str(item.get("key") or "").startswith("creator_")]
    runtime_gaps = [item for item in creator_gaps if item.get("semantic_state") != "configuration_missing"]
    configuration = [item for item in creator_gaps if item.get("semantic_state") == "configuration_missing"]
    merged.update({
        "sources": sources,
        "data_gaps": [
            {"source": item.get("label", item.get("key", "")), "key": item.get("key", ""), "issues": item.get("issues", [])}
            for item in gaps
        ],
        "missing_source_count": int(health.get("missing_source_count") or 0) + len(creator_gaps),
        "runtime_failure_count": base_runtime_failures + len(runtime_gaps),
        "configuration_missing_count": base_configuration + len(configuration),
        "gap_source_keys": [str(item.get("key") or "") for item in gaps],
        "status": (
            "critical" if base_status == "critical" else
            "partial" if base_status == "partial" or runtime_gaps else
            base_status
        ),
    })
    observability = dict(merged.get("observability") or {})
    observability.update({
        "observations": len(sources),
        "configuration_missing_count": base_configuration + len(configuration),
        "runtime_failure_count": base_runtime_failures + len(runtime_gaps),
        "no_event_count": sum(item.get("status") == "no_event" for item in sources),
    })
    merged["observability"] = observability
    state_counts = dict(health.get("state_counts") or {})
    source_roles = dict(health.get("source_roles") or {})
    for row in creator_gaps + [item for item in sources if str(item.get("key") or "").startswith("creator_") and item not in creator_gaps]:
        state = str(row.get("state") or "")
        role = str(row.get("role") or "optional")
        if state:
            state_counts[state] = state_counts.get(state, 0) + 1
        source_roles[role] = source_roles.get(role, 0) + 1
    merged["state_counts"] = state_counts
    merged["source_roles"] = source_roles
    return merged


__all__ = ["CREATOR_PROVIDERS", "build_creator_source_health", "merge_creator_sources"]
