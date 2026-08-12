"""Source-health history and SLO aggregates for the Mini App."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def aggregate_source_health(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(records)
    total = len(rows)
    def semantic(row: dict[str, Any]) -> str:
        return str(row.get("semantic_state") or row.get("state") or row.get("status", "")).lower()
    successful = sum(semantic(row) in {"ok", "healthy", "success", "no_event"} for row in rows)
    # ``state= no_event`` is an internal compatibility field on legacy rows;
    # the investor count is based on an explicit provider status only.
    no_events = sum(str(row.get("status", "")).lower() in {"no_event", "no_events"} for row in rows)
    configuration_missing = sum(semantic(row) in {"configuration_missing", "configuration_required"} for row in rows)
    stale = sum(bool(row.get("stale_used") or row.get("freshness") == "stale") for row in rows)
    crosschecked = sum(bool(row.get("cross_checked")) for row in rows)
    parser_errors = sum(bool(row.get("parser_error")) for row in rows)
    # Missing optional credentials require operator configuration; they are
    # not evidence that an otherwise healthy provider failed at runtime.
    failures = max(0, total - successful - configuration_missing)
    degraded = failures + stale
    return {
        "observations": total,
        "success_rate": round(successful / total * 100, 2) if total else None,
        "failure_count": failures,
        "configuration_missing_count": configuration_missing,
        "no_event_count": no_events,
        "stale_count": stale,
        "degraded_count": degraded,
        "crosscheck_rate": round(crosschecked / total * 100, 2) if total else None,
        "parser_error_count": parser_errors,
        "state": "healthy" if total and degraded == 0 else "partial" if successful else "failed" if total else "no_observations",
    }


def source_state(*, scanned: bool, has_events: bool, error: str | None = None) -> dict[str, Any]:
    """Separate an empty result from a failed scan."""
    if error:
        return {"state": "scan_failed", "reason": error, "has_events": False}
    if not scanned:
        return {"state": "not_scanned", "reason": "source_not_scanned", "has_events": False}
    return {"state": "events_found" if has_events else "no_events", "reason": None, "has_events": has_events}

