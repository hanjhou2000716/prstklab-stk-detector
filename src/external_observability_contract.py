"""Canonical public observability fields for external intelligence sources.

The producer, release boundary, and tests use this module as the Python-side
contract.  Historical releases may contain one of the legacy aliases, but a
new release is always normalized to the canonical >=9 field.
"""

from __future__ import annotations

from typing import Any

CANONICAL_IMPORTANCE_AT_FIELD = "last_importance_gte_9_at"
LEGACY_IMPORTANCE_AT_FIELDS = (
    "last_importance_ge9_at",
    "last_importance_ge8_at",
    "last_importance_gte_8_at",
)

EXTERNAL_OBSERVABILITY_ALIASES = {
    alias: CANONICAL_IMPORTANCE_AT_FIELD
    for alias in LEGACY_IMPORTANCE_AT_FIELDS
}

EXTERNAL_OBSERVABILITY_FIELDS = frozenset({
    "last_received_at",
    "last_parsed_at",
    "parser_error_count",
    *LEGACY_IMPORTANCE_AT_FIELDS,
    CANONICAL_IMPORTANCE_AT_FIELD,
    "qualifying_item_count",
    "pending_cluster_count",
    "last_notification_decision",
    "last_delivery_at",
    "decision",
    "last_release_id",
    "last_snapshot_id",
    "last_observation_id",
    "last_telegram_delivery_at",
    "last_telegram_delivery_status",
    "importance_gte_8_count",
})

CREATOR_OBSERVABILITY_FIELDS = frozenset({
    "observations",
    "last_received_at",
    "last_parsed_at",
    "parser_error_count",
    "no_event_count",
    "last_delivery_at",
    "morning_batch_count",
    "daily_coverage_count",
    "coverage_status",
    "morning_batch_state",
    "morning_batch_key",
    "consensus_status",
    "last_release_id",
    "last_snapshot_id",
    "last_observation_id",
    "last_telegram_delivery_at",
    "last_telegram_delivery_status",
    "state",
})


def normalize_external_observability(
    value: Any,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Normalize legacy FJ observability aliases without inventing data.

    ``None`` means the optional object is absent.  A non-object is returned as
    ``None`` with a diagnostic so the release boundary can quarantine only the
    optional observability object instead of blocking the core release.
    """
    if value is None:
        return None, []
    if not isinstance(value, dict):
        return None, ["observability_not_object"]

    normalized = dict(value)
    notes: list[str] = []
    canonical_value = normalized.get(CANONICAL_IMPORTANCE_AT_FIELD)
    if canonical_value in (None, ""):
        for alias in LEGACY_IMPORTANCE_AT_FIELDS:
            if normalized.get(alias) not in (None, ""):
                normalized[CANONICAL_IMPORTANCE_AT_FIELD] = normalized[alias]
                notes.append(f"{alias}->{CANONICAL_IMPORTANCE_AT_FIELD}")
                break
    for alias in LEGACY_IMPORTANCE_AT_FIELDS:
        if alias in normalized:
            normalized.pop(alias, None)
            notes.append(f"removed:{alias}")
    return normalized, notes


__all__ = [
    "CANONICAL_IMPORTANCE_AT_FIELD",
    "CREATOR_OBSERVABILITY_FIELDS",
    "EXTERNAL_OBSERVABILITY_FIELDS",
    "EXTERNAL_OBSERVABILITY_ALIASES",
    "LEGACY_IMPORTANCE_AT_FIELDS",
    "normalize_external_observability",
]
