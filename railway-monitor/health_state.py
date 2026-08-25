"""Privacy-safe, thread-safe runtime health state for the Railway monitor."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

# Public diagnostics contain only bounded state, timestamps and counters.
# Credentials, message bodies, transport IDs and recipient identifiers never
# belong in this module or in the serialized health snapshot.
HEALTH_LOCK = threading.Lock()
MAX_HEALTH_HISTORY = 168
HEALTH_HISTORY: list[dict[str, Any]] = []
HEALTH_STATE: dict[str, Any] = {
    "status": "ok",
    "service": "prstk-jin10-monitor",
    "started_at": datetime.now(UTC).isoformat(),
    "jin10": {"status": "not_checked", "last_success_at": None, "last_failure_at": None, "item_count": 0, "error": None},
    "gdelt": {"enabled": True, "status": "not_checked", "event_scan": "not_checked", "last_success_at": None, "last_failure_at": None, "article_count": 0, "alert_count": 0, "pending_count": 0, "pending_reasons": {}, "error": None, "stale_cache_used": False, "health_dispatch_status": "not_checked", "health_dispatch_error": None, "health_dispatch_next_retry_at": None},
    "market_sync": {"status": "not_checked", "source_url": None, "fetched_at": None, "record_count": 0, "error": None},
    "classification": {"status": "not_checked", "updated_at": None, "classification_counts": {}, "unclassified_count": 0, "reason_counts": {}},
    "delivery": {"status": "not_checked", "last_trace_id": None, "last_outbox_status": None, "last_receipt_status": None, "counts": {}, "last_updated_at": None, "last_error": None, "storage": {"status": "not_checked", "durable_volume_detected": False, "state_parent_writable": False, "state_parent_exists": False, "fail_closed_for_high_risk": True}},
    "monitor": {"status": "starting", "poll_interval_seconds": None, "last_cycle_started_at": None, "last_cycle_completed_at": None},
    "gmail": {
        "status": "not_configured", "watch_status": "not_checked",
        "watch_expiration": None, "missing": [],
        "observability": {
            "observations": 0, "parser_error_count": 0,
            "queue_pending_count": 0, "dead_letter_count": 0,
            "history_cursor_present": False, "history_cursor_hash": None, "state": "not_checked",
        },
        "storage": {"status": "not_checked", "durable_volume_detected": False, "state_parent_writable": False, "state_parent_exists": False, "fail_closed_for_high_risk": True},
        "error": None,
    },
    "creator": {
        "status": "not_checked", "received_count": 0, "parsed_count": 0,
        "failed_count": 0, "duplicate_count": 0,
        "public_observation_count": 0, "last_received_at": None,
        "last_parsed_at": None, "last_failure_at": None,
        "today_count": 0, "latest_count": 0,
        "morning_batch_count": 0, "daily_coverage_count": 0,
        "coverage_status": "not_checked", "morning_batch_state": "not_checked",
        "morning_batch_key": None, "consensus_status": "not_checked",
        "last_release_id": None, "last_snapshot_id": None,
        "last_observation_id": None, "last_telegram_delivery_at": None,
        "last_telegram_delivery_status": "not_checked",
    },
    "financialjuice": {
        "status": "not_checked", "received_count": 0, "parsed_count": 0,
        "failed_count": 0, "duplicate_count": 0,
        "public_observation_count": 0, "importance_gte_8_count": 0,
        "pending_cluster_count": 0, "last_received_at": None,
        "last_parsed_at": None, "last_failure_at": None,
        "last_importance_gte_8_at": None, "decision": "not_checked",
        "last_release_id": None, "last_snapshot_id": None,
        "last_observation_id": None, "last_telegram_delivery_at": None,
        "last_telegram_delivery_status": "not_checked",
    },
    "news": {
        "status": "not_checked", "execution_plane": "github_actions",
        "reason": "news_health_is_published_with_release_snapshot",
        "last_success_at": None, "last_failure_at": None,
        "provider_status": {}, "stories_ingested": 0,
        "stories_deduped": 0, "stories_ranked": 0, "relevance_rejected": 0,
    },
}

_HEALTHY_STATES = {"healthy", "ok", "ready", "success", "no_event", "no_new_content", "scan_complete"}
_NO_EVENT_STATES = {"no_event", "no_events", "no_new_content", "empty"}
_CONFIGURATION_STATES = {"configuration_missing", "configuration_required", "not_configured"}
_NOT_CHECKED_STATES = {"not_checked", "starting", "idle"}
_FAILURE_STATES = {
    "failed", "provider_failed", "parse_failed", "scan_failed", "stale", "partial",
    "release_blocked", "rate_limited", "permission_denied", "http_error", "invalid_payload",
}


def summarize_health(state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Summarize component health without collapsing no-event into failure.

    The legacy top-level ``status=ok`` remains untouched for clients that use
    it as an HTTP reachability signal.  This additive summary is the semantic
    status for operators and Mini App source-health consumers.
    """
    source = state if isinstance(state, dict) else HEALTH_STATE
    component_statuses: dict[str, str] = {}
    no_event_count = 0
    configuration_missing_count = 0
    not_checked_count = 0
    failure_count = 0
    healthy_count = 0
    for component, value in source.items():
        if not isinstance(value, dict):
            continue
        status = str(value.get("status") or value.get("state") or "not_checked").strip().casefold()
        component_statuses[str(component)] = status
        if status in _NO_EVENT_STATES:
            no_event_count += 1
        if status in _CONFIGURATION_STATES:
            configuration_missing_count += 1
        elif status in _NOT_CHECKED_STATES:
            not_checked_count += 1
        elif status in _FAILURE_STATES:
            failure_count += 1
        elif status in _HEALTHY_STATES:
            healthy_count += 1
        else:
            # Unknown statuses are not evidence of health.  Keep the endpoint
            # usable while surfacing the unknown state as a degraded component.
            failure_count += 1
    component_count = len(component_statuses)
    if failure_count:
        overall_state = "partial" if healthy_count or no_event_count else "failed"
    elif configuration_missing_count and not (healthy_count or no_event_count):
        overall_state = "configuration_missing"
    elif not_checked_count and not (healthy_count or no_event_count):
        overall_state = "not_checked"
    elif configuration_missing_count or not_checked_count:
        overall_state = "partial"
    else:
        overall_state = "healthy" if component_count else "not_checked"
    return {
        "overall_state": overall_state,
        "component_count": component_count,
        "healthy_count": healthy_count,
        "no_event_count": no_event_count,
        "configuration_missing_count": configuration_missing_count,
        "not_checked_count": not_checked_count,
        "failure_count": failure_count,
        "component_statuses": component_statuses,
    }


def update_health(component: str, **values: Any) -> None:
    """Atomically merge bounded component values into runtime health."""
    with HEALTH_LOCK:
        HEALTH_STATE.setdefault(component, {}).update(values)


def record_health_sample(*, recorded_at: datetime | None = None) -> dict[str, Any]:
    """Append one bounded, privacy-safe poll-cycle health sample.

    The sample contains only component states and aggregate counters; it never
    copies credentials, message bodies, transport IDs, or recipient data.
    Keeping the history in memory avoids turning the public health endpoint
    into a second private datastore while still making short outages visible.
    """
    timestamp = recorded_at or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    with HEALTH_LOCK:
        snapshot = json.loads(json.dumps(HEALTH_STATE))
        summary = summarize_health(snapshot)
        sample = {
            "recorded_at": timestamp.astimezone(UTC).isoformat(),
            "overall_state": summary["overall_state"],
            "failure_count": summary["failure_count"],
            "no_event_count": summary["no_event_count"],
            "component_statuses": summary["component_statuses"],
        }
        HEALTH_HISTORY.append(sample)
        del HEALTH_HISTORY[:-MAX_HEALTH_HISTORY]
        return json.loads(json.dumps(sample))


def health_history_summary(*, now: datetime | None = None) -> dict[str, Any]:
    """Return bounded 24-hour/7-day counts for the current health history."""
    reference = now or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    with HEALTH_LOCK:
        samples = json.loads(json.dumps(HEALTH_HISTORY))

    def parsed_time(row: dict[str, Any]) -> datetime | None:
        try:
            value = datetime.fromisoformat(str(row.get("recorded_at", "")).replace("Z", "+00:00"))
            return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(UTC)
        except (TypeError, ValueError, OverflowError):
            return None

    def window(hours: int) -> dict[str, Any]:
        cutoff = reference.astimezone(UTC) - timedelta(hours=hours)
        rows = [row for row in samples if (stamp := parsed_time(row)) is not None and stamp >= cutoff]
        failures = sum(1 for row in rows if row.get("overall_state") in {"failed", "partial"})
        return {
            "sample_count": len(rows),
            "failure_count": failures,
            "healthy_count": sum(1 for row in rows if row.get("overall_state") == "healthy"),
            "latest_at": rows[-1].get("recorded_at") if rows else None,
        }

    return {
        "sample_count": len(samples),
        "max_samples": MAX_HEALTH_HISTORY,
        "windows": {"24h": window(24), "7d": window(168)},
        "samples": samples,
    }


def snapshot_health() -> dict[str, Any]:
    """Return a detached JSON-safe copy for HTTP responses."""
    with HEALTH_LOCK:
        snapshot = json.loads(json.dumps(HEALTH_STATE))
    snapshot["health_summary"] = summarize_health(snapshot)
    snapshot["observability"] = {"history": health_history_summary()}
    return snapshot


__all__ = [
    "HEALTH_HISTORY", "HEALTH_LOCK", "HEALTH_STATE", "MAX_HEALTH_HISTORY",
    "health_history_summary", "record_health_sample", "snapshot_health",
    "summarize_health", "update_health",
]
