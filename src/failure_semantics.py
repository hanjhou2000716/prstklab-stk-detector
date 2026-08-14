"""Canonical failure/no-content states shared by ingress and release gates.

The public contracts must distinguish a successful empty scan from an actual
provider failure.  This module keeps that vocabulary in one place without
including transport identifiers, raw payloads, or credentials in the result.
"""

from __future__ import annotations

from typing import Any

FAILURE_STATES = frozenset({
    "healthy",
    "no_new_content",
    "stale",
    "partial",
    "parse_failed",
    "configuration_missing",
    "provider_failed",
    "pending_confirmation",
    "release_blocked",
})

_CONFIGURATION = {"configuration_missing", "configuration_required", "missing_api_key", "not_configured"}
_PARSE_FAILURE = {"parse_failed", "unsupported_template", "invalid_source", "duplicate"}
_PROVIDER_FAILURE = {"failed", "provider_failed", "scan_failed", "error", "failure"}


def classify_failure(record: dict[str, Any] | None) -> str:
    """Return one canonical state without treating missing data as no-event.

    Explicit blocking/error fields win over a legacy status so a provider
    cannot accidentally become healthy merely because it returned an empty
    payload.  Unknown values fail closed to ``provider_failed``.
    """
    if not isinstance(record, dict):
        return "configuration_missing"
    status = str(record.get("status") or record.get("state") or "").strip().lower()
    provider_status = str(record.get("provider_status") or record.get("error_code") or "").strip().lower()
    if record.get("release_blocked") is True or status == "release_blocked":
        return "release_blocked"
    if record.get("pending_confirmation") is True or status in {"pending", "pending_confirmation"}:
        return "pending_confirmation"
    if status in _CONFIGURATION or provider_status in _CONFIGURATION:
        return "configuration_missing"
    if status in _PARSE_FAILURE or provider_status in _PARSE_FAILURE or record.get("parser_error"):
        return "parse_failed"
    if status in _PROVIDER_FAILURE or provider_status in _PROVIDER_FAILURE or record.get("error"):
        return "provider_failed"
    freshness = str(record.get("freshness") or "").strip().lower()
    if status == "stale" or freshness in {"stale", "expired", "recent_close_stale"}:
        return "stale"
    if status in {"partial", "degraded", "optional_degraded", "data_gap"}:
        return "partial"
    if status in {"no_event", "no_events", "empty", "none", "no_new_content"}:
        return "no_new_content"
    if status in {"healthy", "ok", "success", "complete", "completed"}:
        return "healthy"
    return "provider_failed"


def is_alert_eligible(state: str) -> bool:
    """Only healthy data can qualify; empty/failure states are fail-closed."""
    return state == "healthy"


__all__ = ["FAILURE_STATES", "classify_failure", "is_alert_eligible"]
