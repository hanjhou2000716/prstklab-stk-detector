"""Create a bounded, identity-bound event trace for official monitor runs."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _bounded(value: object, limit: int = 160) -> str:
    return str(value or "")[:limit]


def _count(value: object) -> int:
    try:
        return max(0, int(str(value or 0)))
    except (TypeError, ValueError, OverflowError):
        return 0


def _read_rows(path: str | Path | None) -> list[dict[str, Any]]:
    if not path:
        return []
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def build_trace(
    *,
    run_id: object,
    attempt: object,
    sha: object,
    candidate_results: object,
    batch_results_path: str | Path | None = None,
    stages: dict[str, Any] | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """Join per-candidate decisions to actual sender outputs without source text."""
    candidates = candidate_results if isinstance(candidate_results, list) else []
    deliveries = _read_rows(batch_results_path)
    deliveries_by_ref = {
        _bounded(row.get("event_ref"), 64): row
        for row in deliveries if _bounded(row.get("event_ref"), 64)
    }
    deliveries_by_key = {
        _bounded(row.get("notification_key"), 160): row
        for row in deliveries if _bounded(row.get("notification_key"), 160)
    }
    events: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        event_ref = _bounded(raw.get("event_ref"), 64)
        notification_key = _bounded(raw.get("notification_key"), 160)
        delivery = deliveries_by_ref.get(event_ref) or deliveries_by_key.get(notification_key) or {}
        status = _bounded(
            delivery.get("delivery_status")
            or ("failed" if delivery.get("error_type") else "")
            or raw.get("status") or "unknown", 64,
        )
        reason = _bounded(
            delivery.get("reason") or delivery.get("error_type")
            or raw.get("reason") or "not_recorded", 160,
        )
        stage = _bounded(
            "recipient_receipt" if delivery.get("receipt_required") else
            "sender" if delivery else raw.get("stage") or "preflight", 64,
        )
        identity = (event_ref, _bounded(raw.get("key_fingerprint") or notification_key, 160))
        if identity in seen:
            continue
        seen.add(identity)
        events.append({
            "event_ref": event_ref,
            "fact_fingerprint": _bounded(raw.get("fact_fingerprint"), 32),
            "summary_contract_version": _bounded(raw.get("summary_contract_version"), 40),
            "notification_key": _bounded(delivery.get("notification_key") or notification_key, 160),
            "notification_id": _bounded(delivery.get("alert_id") or raw.get("notification_key"), 160),
            "release_id": _bounded(delivery.get("release_id"), 160),
            "snapshot_id": _bounded(delivery.get("snapshot_id") or raw.get("snapshot_id"), 160),
            "claim_key": _bounded(delivery.get("notification_key"), 160),
            "stage": stage,
            "status": status,
            "reason": reason,
            "expected": bool(raw.get("expected", False)),
            "source_published_at": _bounded(raw.get("source_published_at"), 80),
            "expires_at": _bounded(raw.get("expires_at"), 80),
            "first_detected_at": _bounded(raw.get("first_detected_at"), 80),
            "candidate_recorded_at": _bounded(raw.get("recorded_at") or recorded_at, 80),
            "first_failure": (
                {
                    "stage": stage, "reason": reason,
                    "recorded_at": _bounded(raw.get("first_detected_at") or raw.get("recorded_at") or recorded_at, 80),
                }
                if status in {"unknown", "content_incomplete", "summary_timeout", "blocked", "failed", "partial", "contract_mismatch"}
                else None
            ),
            "last_progress_at": _bounded(raw.get("last_progress_at") or recorded_at, 80),
            "delivered_count": _count(delivery.get("delivered_count")),
            "failed_count": _count(delivery.get("failed_count")),
            "receipt_required": bool(delivery.get("receipt_required", False)),
            "error_type": _bounded(delivery.get("error_type"), 64),
        })
    now = recorded_at or datetime.now(UTC).isoformat()
    return {
        "schema_version": "official-event-trace-v1",
        "workflow_run_id": _bounded(run_id, 32),
        "run_attempt": _bounded(attempt, 12),
        "workflow_sha": _bounded(sha, 40),
        "recorded_at": now,
        "stages": {
            _bounded(name, 48): _bounded(value, 160)
            for name, value in (stages or {}).items()
        },
        "events": events,
    }


def write_trace(path: str | Path, **kwargs: Any) -> dict[str, Any]:
    """Atomically persist the trace so even empty/preflight-failed runs upload it."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    trace = build_trace(**kwargs)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(trace, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, output)
    return trace
