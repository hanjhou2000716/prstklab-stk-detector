"""Privacy-safe projection from the private ingress store to /health."""

from __future__ import annotations

from typing import Any

_MAX_TEXT_LENGTH = 160
_PUBLIC_FIELD_TYPES: dict[str, dict[str, str]] = {
    "creator": {
        "status": "text",
        "received_count": "counter",
        "parsed_count": "counter",
        "failed_count": "counter",
        "duplicate_count": "counter",
        "public_observation_count": "counter",
        "today_count": "counter",
        "latest_count": "counter",
        "morning_batch_count": "counter",
        "daily_coverage_count": "counter",
        "coverage_status": "text",
        "morning_batch_state": "text",
        "morning_batch_key": "text",
        "consensus_status": "text",
        "last_release_id": "text",
        "last_snapshot_id": "text",
        "last_observation_id": "text",
        "last_received_at": "timestamp",
        "last_parsed_at": "timestamp",
        "last_failure_at": "timestamp",
        "last_failure_reason": "text",
        "failure_reason_counts": "mapping",
        "last_telegram_delivery_at": "timestamp",
        "last_telegram_delivery_status": "text",
    },
    "financialjuice": {
        "status": "text",
        "last_sync_at": "timestamp",
        "last_sync_diagnostics": "diagnostics",
        "received_count": "counter",
        "parsed_count": "counter",
        "failed_count": "counter",
        "duplicate_count": "counter",
        "public_observation_count": "counter",
        "importance_gte_8_count": "counter",
        "qualifying_item_count": "counter",
        "pending_cluster_count": "counter",
        "last_received_at": "timestamp",
        "last_parsed_at": "timestamp",
        "last_failure_at": "timestamp",
        "last_failure_reason": "text",
        "failure_reason_counts": "mapping",
        "last_importance_gte_8_at": "timestamp",
        "decision": "text",
        "last_release_id": "text",
        "last_snapshot_id": "text",
        "last_observation_id": "text",
        "last_telegram_delivery_at": "timestamp",
        "last_telegram_delivery_status": "text",
    },
}


def _bounded_text(value: Any) -> str | None:
    """Return a bounded scalar string; never serialize nested/private data."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > _MAX_TEXT_LENGTH:
        return None
    return text


def _counter(value: Any) -> int | None:
    """Accept only non-negative, reasonably bounded integer counters."""
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if 0 <= parsed <= 1_000_000_000 else None


def _project_value(value: Any, kind: str) -> Any:
    if kind == "counter":
        return _counter(value)
    if kind == "mapping":
        if not isinstance(value, dict):
            return None
        projected: dict[str, int] = {}
        for key, count in sorted(value.items(), key=lambda pair: (-int(pair[1]) if isinstance(pair[1], int) else 0, str(pair[0])))[:8]:
            reason = _bounded_text(str(key))
            parsed = _counter(count)
            if reason is not None and parsed is not None:
                projected[reason] = parsed
        return projected
    if kind == "diagnostics":
        if not isinstance(value, dict):
            return None
        raw_counts = value.get("candidate_diagnostics")
        raw_counts = raw_counts.get("counts") if isinstance(raw_counts, dict) else None
        counts: dict[str, int] = {}
        if isinstance(raw_counts, dict):
            for key, count in raw_counts.items():
                reason = _bounded_text(str(key))
                parsed = _counter(count)
                if reason is not None and parsed is not None:
                    counts[reason] = parsed
        reason = _bounded_text(value.get("candidate_diagnostics", {}).get("primary_reason")) if isinstance(value.get("candidate_diagnostics"), dict) else None
        return {
            "recorded_at": _bounded_text(value.get("recorded_at")),
            "status": _bounded_text(value.get("status")),
            "processed": _counter(value.get("processed")) or 0,
            "accepted_new_count": _counter(value.get("accepted_new_count")) or 0,
            "material_candidate_count": _counter(value.get("material_candidate_count")) or 0,
            "duplicate_count": _counter(value.get("duplicate_count")) or 0,
            "failed": _counter(value.get("failed")) or 0,
            "candidate_diagnostics": {"counts": counts, "primary_reason": reason or ""},
        }
    # Timestamps are intentionally treated as bounded text here.  The health
    # endpoint is diagnostic, while timestamp semantics are validated by the
    # producer and release contracts; keeping this adapter dependency-free is
    # required for the standalone Railway bundle.
    return _bounded_text(value)


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
            projected: dict[str, Any] = {}
            for key, kind in _PUBLIC_FIELD_TYPES[component].items():
                if key not in source:
                    continue
                value = _project_value(source[key], kind)
                if value is not None:
                    projected[key] = value
            result[component] = projected
    return result


__all__ = ["project_source_health"]
