"""Source-health history and SLO aggregates for the Mini App."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

HEALTH_HISTORY_RETENTION_HOURS = 24 * 7
HEALTH_HISTORY_MAX_SAMPLES = 168


def _timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)


def _history_metric(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize already-normalized health samples without inventing data."""
    if not rows:
        return {
            "sample_count": 0,
            "success_rate": None,
            "failure_count": 0,
            "no_event_count": 0,
            "stale_count": 0,
            "crosscheck_rate": None,
            "parser_error_count": 0,
            "state": "no_observations",
        }
    def number(row: dict[str, Any], key: str) -> int:
        try:
            return max(0, int(row.get(key) or 0))
        except (TypeError, ValueError, OverflowError):
            return 0

    def percentage(row: dict[str, Any], key: str) -> float:
        try:
            return max(0.0, min(100.0, float(row.get(key) or 0)))
        except (TypeError, ValueError, OverflowError):
            return 0.0

    observations = sum(number(row, "observations") for row in rows)
    successes = sum(
        number(row, "successful_observations")
        if "successful_observations" in row
        else round(number(row, "observations") * percentage(row, "success_rate") / 100)
        for row in rows
    )
    failures = sum(number(row, "failure_count") for row in rows)
    no_events = sum(number(row, "no_event_count") for row in rows)
    stale = sum(number(row, "stale_count") for row in rows)
    parser_errors = sum(number(row, "parser_error_count") for row in rows)
    crosschecked = sum(
        round(number(row, "observations") * percentage(row, "crosscheck_rate") / 100)
        for row in rows
    )
    return {
        "sample_count": len(rows),
        "success_rate": round(successes / observations * 100, 2) if observations else None,
        "failure_count": failures,
        "no_event_count": no_events,
        "stale_count": stale,
        "crosscheck_rate": round(crosschecked / observations * 100, 2) if observations else None,
        "parser_error_count": parser_errors,
        "state": "failed" if failures and not successes else "partial" if failures or stale else "healthy",
    }


def summarize_health_history(
    records: Iterable[dict[str, Any]], *, now: datetime | None = None,
    retention_hours: int = HEALTH_HISTORY_RETENTION_HOURS,
    max_samples: int = HEALTH_HISTORY_MAX_SAMPLES,
) -> dict[str, Any]:
    """Build bounded 24-hour/7-day source-health history for the public artifact.

    Samples are supplied by the producer and are never synthesized from the
    current row. Invalid timestamps are excluded and reported as a count so a
    malformed history cannot masquerade as a healthy period.
    """
    current = (now or datetime.now(UTC)).astimezone(UTC)
    hours = max(24, min(int(retention_hours), HEALTH_HISTORY_RETENTION_HOURS))
    limit = max(1, min(int(max_samples), HEALTH_HISTORY_MAX_SAMPLES))
    cutoff = current - timedelta(hours=hours)
    valid: list[tuple[datetime, dict[str, Any]]] = []
    invalid = 0
    for record in records:
        if not isinstance(record, dict):
            invalid += 1
            continue
        timestamp = _timestamp(record.get("checked_at") or record.get("recorded_at") or record.get("fetched_at"))
        if timestamp is None:
            invalid += 1
            continue
        if cutoff <= timestamp <= current:
            valid.append((timestamp, record))
    valid.sort(key=lambda item: item[0])
    if len(valid) > limit:
        valid = valid[-limit:]
    samples = [
        {"checked_at": timestamp.isoformat(), **_history_metric([record])}
        for timestamp, record in valid
    ]
    def window(window_hours: int) -> dict[str, Any]:
        start = current - timedelta(hours=window_hours)
        return _history_metric([record for timestamp, record in valid if timestamp >= start])

    return {
        "retention_hours": hours,
        "max_samples": limit,
        "sample_count": len(samples),
        "invalid_sample_count": invalid,
        "last_checked_at": samples[-1]["checked_at"] if samples else None,
        "windows": {"24h": window(24), "7d": window(24 * 7)},
        "samples": samples,
    }


def aggregate_source_health(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(records)
    total = len(rows)
    def semantic(row: dict[str, Any]) -> str:
        return str(row.get("semantic_state") or row.get("state") or row.get("status", "")).lower()
    successful = sum(
        semantic(row) in {"ok", "healthy", "success", "no_event", "no_new_content"}
        for row in rows
    )
    # ``state= no_event`` is an internal compatibility field on legacy rows;
    # the investor count is based on an explicit provider status only.
    no_events = sum(
        str(row.get("status", "")).lower()
        in {"no_event", "no_events", "no_new_content"}
        for row in rows
    )
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

