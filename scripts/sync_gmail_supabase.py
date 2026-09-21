"""Synchronise bounded Gmail history using Supabase-backed private state."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RAILWAY = ROOT / "railway-monitor"
# Put the canonical application package first.  The Railway directory still
# supplies its standalone top-level adapters (gmail_history_sync, email_store,
# etc.), but ``src`` must resolve to the same summary/priority producer used by
# the monitor; otherwise Gmail ingress can wake the monitor on a looser copy of
# the contract.
for path in (RAILWAY, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from gmail_history_sync import (  # noqa: E402
    reconcile_priority_pending,
    sync_gmail_history,
    sync_latest_financialjuice,
)
from gmail_watch import GmailWatchConfig  # noqa: E402
from supabase_email_store import SupabaseEmailStore  # noqa: E402

from gmail_ingress import GmailIngressService  # noqa: E402

SYNC_RESULT_KEYS = (
    "status", "processed", "failed", "duplicate", "duplicate_count", "accepted_new_count",
    "material_candidate_count", "priority_candidate_count", "skipped", "history_gap",
    "failure_types", "latest_financialjuice_diagnostics", "candidate_diagnostics",
    "notification_requested", "sync_started_at", "sync_completed_at",
    "storage_error", "diagnostic_reason", "supabase_retry_count",
    "recovery_status", "retryable", "request_attempts", "consecutive_failure_count",
    "first_failure_at", "cursor_preserved", "next_retry_at", "escalation_reason",
    "priority_pending_error_reasons",
    "priority_pending_refs",
    "priority_event_refs",
    "priority_recovery_scan_status", "priority_recovery_error",
    "priority_recovery_status",
    "priority_recovery_checked_at",
    "priority_pending_count", "priority_pending_expired_count",
)

TRANSIENT_STORAGE_ERRORS = frozenset({
    "supabase_transport_error", "supabase_http_429", "supabase_http_500",
    "supabase_http_502", "supabase_http_503", "supabase_http_504",
})
TRANSIENT_GMAIL_ERRORS = frozenset({
    "http_429", "http_500", "http_502", "http_503", "http_504",
    "timeoutexception", "httpx.timeoutexception", "network_error",
})


def build_safe_sync_result(
    result: dict[str, Any],
    *,
    notification_requested: bool,
    sync_started_at: str,
    sync_completed_at: str,
) -> dict[str, Any]:
    """Project the sync result into the workflow's stable, public-safe contract."""
    safe = {key: result[key] for key in SYNC_RESULT_KEYS if key in result}
    safe["notification_requested"] = notification_requested
    safe["sync_started_at"] = sync_started_at
    safe["sync_completed_at"] = sync_completed_at
    safe.setdefault("recovery_status", "healthy" if int(safe.get("failed") or 0) == 0 else "persistent_failure")
    safe.setdefault("retryable", False)
    safe.setdefault("supabase_retry_count", 0)
    safe.setdefault("request_attempts", 0)
    safe.setdefault("consecutive_failure_count", 0)
    safe.setdefault("first_failure_at", None)
    safe.setdefault("cursor_preserved", None)
    safe.setdefault("next_retry_at", None)
    safe.setdefault("escalation_reason", None)
    return safe


def _safe_storage_error(error: BaseException) -> str:
    value = str(error).strip()
    if value.startswith("supabase_http_") or value in {"supabase_transport_error", "supabase_store_not_configured"}:
        return value[:80]
    return "supabase_storage_error"


def _is_transient_error(value: Any) -> bool:
    text = str(value or "").strip().casefold()
    return text in TRANSIENT_STORAGE_ERRORS or text in TRANSIENT_GMAIL_ERRORS or any(
        marker in text for marker in ("timeout", "connectionerror", "connecterror")
    )


def _result_error(result: dict[str, Any]) -> str:
    return str(result.get("storage_error") or result.get("status") or "").strip()


def _next_retry_at() -> str:
    return (datetime.now(UTC) + timedelta(minutes=5)).isoformat()


def _attach_priority_recovery(store: Any, result: dict[str, Any]) -> dict[str, Any]:
    """Attach the durable FJ scan to every regular five-minute sync result."""
    recovery = reconcile_priority_pending(store)
    result["priority_recovery_checked_at"] = datetime.now(UTC).isoformat()
    for key in (
        "priority_recovery_scan_status", "priority_recovery_error",
        "priority_recovery_status",
        "priority_recovery_checked_at",
        "priority_pending_count", "priority_pending_expired_count",
        "priority_pending_refs", "priority_event_refs",
    ):
        if key in recovery:
            result[key] = recovery[key]
    if recovery.get("priority_recovery_scan_status") == "failed":
        result["failed"] = max(1, _safe_int(result.get("failed")))
        result["status"] = "priority_recovery_scan_failed"
        result["storage_error"] = str(recovery.get("priority_recovery_error") or "priority_recovery_scan_failed")[:80]
        result["diagnostic_reason"] = "priority_recovery_scan_failed"
        result["cursor_preserved"] = True
    return result


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _apply_recovery_state(store: Any, result: dict[str, Any]) -> dict[str, Any]:
    """Classify transient failures without changing the cursor or delivery path."""
    now = datetime.now(UTC).isoformat()
    run_id = str(os.environ.get("GITHUB_RUN_ID") or "").strip()
    run_sha = str(os.environ.get("GITHUB_SHA") or "").strip()
    attempts = _safe_int(result.get("request_attempts") or getattr(store, "last_request_attempts", 0))
    retry_count = _safe_int(result.get("supabase_retry_count") or getattr(store, "last_retry_count", 0))
    result["request_attempts"] = attempts
    result["supabase_retry_count"] = retry_count
    result["cursor_preserved"] = bool(result.get("failed"))

    error = _result_error(result)
    if not result.get("failed"):
        clear = getattr(store, "clear_sync_failure", None)
        recovered = False
        if callable(clear):
            try:
                recovery = clear(success_at=now)
                recovered = bool(recovery.get("had_failure")) if isinstance(recovery, dict) else False
            except Exception:
                # A healthy sync must not be turned into a delivery failure by
                # an optional health cleanup call.
                recovered = False
        result["recovery_status"] = "recovered_after_retry" if recovered or retry_count else "healthy"
        result["retryable"] = False
        result["consecutive_failure_count"] = 0
        result["cursor_preserved"] = False
        return result

    retryable = _is_transient_error(error)
    result["retryable"] = retryable
    if not retryable:
        result["recovery_status"] = "persistent_failure"
        result["escalation_reason"] = "non_retryable_failure"
        return result

    record = getattr(store, "record_sync_failure", None)
    if not callable(record):
        result["recovery_status"] = "persistent_failure"
        result["escalation_reason"] = "retry_state_unavailable"
        return result
    try:
        state = record(
            error=error,
            failed_at=now,
            run_id=run_id or None,
            run_sha=run_sha or None,
            next_retry_at=_next_retry_at(),
        )
    except Exception:
        result["recovery_status"] = "persistent_failure"
        result["escalation_reason"] = "retry_state_unavailable"
        return result
    if not isinstance(state, dict):
        result["recovery_status"] = "persistent_failure"
        result["escalation_reason"] = "retry_state_invalid"
        return result
    recovery_status = str(state.get("status") or "persistent_failure")
    result["recovery_status"] = recovery_status if recovery_status in {"retry_pending", "persistent_failure"} else "persistent_failure"
    result["consecutive_failure_count"] = _safe_int(state.get("consecutive_failure_count"))
    result["first_failure_at"] = state.get("first_failure_at")
    result["next_retry_at"] = state.get("next_retry_at")
    result["escalation_reason"] = (
        "first_transient_failure" if result["recovery_status"] == "retry_pending"
        else "persistent_transient_failure"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-messages", type=int, default=50)
    parser.add_argument("--notify", choices=("true", "false"), default="true", help="Allow downstream event notification for this sync")
    parser.add_argument("--history-id", default=None, help="Pub/Sub cursor supplied by the Worker")
    parser.add_argument("--latest-financialjuice", action="store_true", help="Reprocess only the newest FJ mail without moving the cursor")
    args = parser.parse_args()
    config = GmailWatchConfig.from_env()
    sync_started_at = datetime.now(UTC).isoformat()
    try:
        store: Any = SupabaseEmailStore()
        cursor = store.cursor()
    except Exception as error:
        # A cursor outage must remain a visible failed decision even though
        # the database is unavailable for persisting the diagnostic itself.
        # The workflow summary consumes this safe JSON and the next bounded
        # run retries from the unchanged cursor.
        safe = build_safe_sync_result(
            {
                "status": "cursor_read_failed",
                "processed": 0,
                "failed": 1,
                "duplicate": 0,
                "duplicate_count": 0,
                "accepted_new_count": 0,
                "material_candidate_count": 0,
                "priority_candidate_count": 0,
                "candidate_diagnostics": {
                    "counts": {},
                    "primary_reason": "gmail_cursor_read_failed",
                },
                "storage_error": _safe_storage_error(error),
                "diagnostic_reason": "gmail_cursor_read_failed",
                "supabase_retry_count": int(getattr(locals().get("store"), "last_retry_count", 0) or 0),
                "request_attempts": int(getattr(locals().get("store"), "last_request_attempts", 0) or 0),
                "cursor_preserved": True,
            },
            notification_requested=args.notify == "true",
            sync_started_at=sync_started_at,
            sync_completed_at=datetime.now(UTC).isoformat(),
        )
        if "store" in locals():
            raw = dict(safe)
            raw["failed"] = 1
            raw = _apply_recovery_state(store, raw)
            safe = build_safe_sync_result(
                raw,
                notification_requested=args.notify == "true",
                sync_started_at=sync_started_at,
                sync_completed_at=datetime.now(UTC).isoformat(),
            )
        else:
            safe["recovery_status"] = "persistent_failure"
            safe["retryable"] = False
            safe["escalation_reason"] = "store_unavailable"
        print(json.dumps(safe, ensure_ascii=False, sort_keys=True))
        return 0 if safe.get("recovery_status") == "retry_pending" else 1
    pending = str(args.history_id or cursor.get("pending_history_id") or "").strip()
    baseline = str(cursor.get("last_history_id") or "").strip()
    event_history_id = "" if args.latest_financialjuice else pending
    update_event = getattr(store, "update_pubsub_event", None)
    if event_history_id and callable(update_event):
        update_event(event_history_id, dispatch_status="processing", sync_started_at=sync_started_at, dispatch_error=None)
    if not baseline and pending:
        # A freshly-created Watch returns a baseline cursor.  If an operator
        # invokes this workflow before the first renewal persisted it, use the
        # notification cursor as a fail-closed baseline (no historical replay).
        store.save_cursor(last_history_id=pending)
    ingress = GmailIngressService(store, config)
    if args.latest_financialjuice:
        result = asyncio.run(sync_latest_financialjuice(config, store, ingress))
        # The operator replay is diagnostic-only.  It may refresh a sanitized
        # observation, but it must never wake the realtime event monitor.
        result["material_candidate_count"] = 0
        result["priority_candidate_count"] = 0
        diagnostics = result.get("candidate_diagnostics")
        if isinstance(diagnostics, dict):
            counts = diagnostics.setdefault("counts", {})
            counts["new_event_eligible"] = 0
            counts["manual_replay"] = 1
            diagnostics["primary_reason"] = "manual_replay"
    else:
        result = asyncio.run(sync_gmail_history(config, store, ingress, max_messages=args.max_messages))
    result = _attach_priority_recovery(store, result)
    result = _apply_recovery_state(store, result)
    result["notification_requested"] = args.notify == "true"
    sync_completed_at = datetime.now(UTC).isoformat()
    if event_history_id and callable(update_event):
        failed = int(result.get("failed") or 0)
        status = str(result.get("status") or "unknown")
        update_event(
            event_history_id,
            dispatch_status="completed" if failed == 0 and status in {"healthy", "no_history_cursor"} else "failed",
            sync_completed_at=sync_completed_at,
            candidate_decided_at=sync_completed_at,
            dispatch_error=None if failed == 0 else status[:120],
        )
    if pending and result.get("status") in {"healthy", "no_history_cursor"}:
        # A new Pub/Sub notification can arrive while this run is processing.
        # Clear only the exact hint this run consumed; never overwrite a newer
        # pending cursor with a blind save_cursor(...=None).
        clear_pending = getattr(store, "clear_pending_history_if_matches", None)
        if not callable(clear_pending):
            raise RuntimeError("cursor_contract_missing:clear_pending_history_if_matches")
        clear_pending(pending)
    safe = build_safe_sync_result(
        result,
        notification_requested=args.notify == "true",
        sync_started_at=sync_started_at,
        sync_completed_at=sync_completed_at,
    )
    print(json.dumps(safe, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("failed", 0) == 0 or result.get("recovery_status") == "retry_pending" else 1


if __name__ == "__main__":
    raise SystemExit(main())
