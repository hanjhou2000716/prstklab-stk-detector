"""Privacy-safe, thread-safe runtime health state for the Railway monitor."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any


# Public diagnostics contain only bounded state, timestamps and counters.
# Credentials, message bodies, transport IDs and recipient identifiers never
# belong in this module or in the serialized health snapshot.
HEALTH_LOCK = threading.Lock()
HEALTH_STATE: dict[str, Any] = {
    "status": "ok",
    "service": "prstk-jin10-monitor",
    "started_at": datetime.now(timezone.utc).isoformat(),
    "jin10": {"status": "not_checked", "last_success_at": None, "last_failure_at": None, "item_count": 0, "error": None},
    "gdelt": {"enabled": True, "status": "not_checked", "event_scan": "not_checked", "last_success_at": None, "last_failure_at": None, "article_count": 0, "alert_count": 0, "pending_count": 0, "pending_reasons": {}, "error": None, "stale_cache_used": False, "health_dispatch_status": "not_checked", "health_dispatch_error": None, "health_dispatch_next_retry_at": None},
    "market_sync": {"status": "not_checked", "source_url": None, "fetched_at": None, "record_count": 0, "error": None},
    "classification": {"status": "not_checked", "updated_at": None, "classification_counts": {}, "unclassified_count": 0, "reason_counts": {}},
    "delivery": {"status": "not_checked", "last_trace_id": None, "last_outbox_status": None, "last_receipt_status": None, "counts": {}, "last_updated_at": None, "last_error": None},
    "monitor": {"status": "starting", "poll_interval_seconds": None, "last_cycle_started_at": None, "last_cycle_completed_at": None},
    "gmail": {
        "status": "not_configured", "watch_status": "not_checked",
        "watch_expiration": None, "missing": [],
        "observability": {
            "observations": 0, "parser_error_count": 0,
            "queue_pending_count": 0, "dead_letter_count": 0,
            "history_cursor_present": False, "history_cursor_hash": None, "state": "not_checked",
        },
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


def update_health(component: str, **values: Any) -> None:
    """Atomically merge bounded component values into runtime health."""
    with HEALTH_LOCK:
        HEALTH_STATE.setdefault(component, {}).update(values)


def snapshot_health() -> dict[str, Any]:
    """Return a detached JSON-safe copy for HTTP responses."""
    with HEALTH_LOCK:
        return json.loads(json.dumps(HEALTH_STATE))


__all__ = ["HEALTH_LOCK", "HEALTH_STATE", "snapshot_health", "update_health"]
