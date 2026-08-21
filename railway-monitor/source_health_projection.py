"""Privacy-safe projection from the private ingress store to /health."""

from __future__ import annotations

from typing import Any


_PUBLIC_FIELDS: dict[str, frozenset[str]] = {
    "creator": frozenset({
        "status", "received_count", "parsed_count", "failed_count",
        "duplicate_count", "public_observation_count", "last_received_at",
        "last_parsed_at", "last_failure_at", "today_count", "latest_count",
        "morning_batch_count", "coverage_status", "consensus_status",
        "last_release_id", "last_telegram_delivery_at",
    }),
    "financialjuice": frozenset({
        "status", "received_count", "parsed_count", "failed_count",
        "duplicate_count", "public_observation_count",
        "importance_gte_8_count", "pending_cluster_count", "last_received_at",
        "last_parsed_at", "last_failure_at", "decision", "last_release_id",
        "last_telegram_delivery_at",
    }),
}


def project_source_health(diagnostics: Any) -> dict[str, dict[str, Any]]:
    """Extract only bounded Creator/FJ counters from a store diagnostic.

    Keeping this adapter outside ``app.py`` makes the public health contract
    testable without importing the long-running Railway server and prevents
    accidental promotion of raw Gmail transport data.
    """
    if not isinstance(diagnostics, dict):
        return {}
    store = diagnostics.get("store")
    values = store.get("source_health") if isinstance(store, dict) else None
    if not isinstance(values, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for component in ("creator", "financialjuice"):
        source = values.get(component)
        if isinstance(source, dict):
            # Explicit allow-list: diagnostics may contain private transport
            # metadata in future versions and must never leak it to /health.
            result[component] = {
                key: source[key]
                for key in _PUBLIC_FIELDS[component]
                if key in source
            }
    return result


__all__ = ["project_source_health"]
