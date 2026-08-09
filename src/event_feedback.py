"""Anonymous, reviewable feedback contract for event-alert quality."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

FEEDBACK_LABELS = {
    "correct",
    "irrelevant",
    "duplicate",
    "wrong_direction",
    "insufficient_source",
    "too_late",
    "not_needed",
}

FEEDBACK_LABEL_ORDER = (
    "correct",
    "irrelevant",
    "duplicate",
    "wrong_direction",
    "insufficient_source",
    "too_late",
    "not_needed",
)


def build_feedback_contract(event: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a public feedback affordance without exposing recipient data."""
    event = event or {}
    event_key = str(event.get("event_key") or event.get("event_cluster_key") or "").strip()
    contract: dict[str, Any] = {
        "enabled": True,
        "labels": list(FEEDBACK_LABEL_ORDER),
        "storage": "review_queue",
        "review_required": True,
        "policy_update_allowed": False,
        "pii_included": False,
    }
    if event_key:
        contract["event_key"] = event_key
    event_type = str(event.get("event_type") or "").strip()
    if event_type:
        contract["event_type"] = event_type
    return contract


def _timestamp(value: Any) -> str:
    if value is None or not str(value).strip():
        return datetime.now(UTC).isoformat()
    return str(value).strip()


def record_feedback(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a PII-free feedback row; reject unknown labels and empty keys."""
    event_key = str(payload.get("event_key") or payload.get("event_cluster_key") or "").strip()
    label = str(payload.get("label") or "").strip().lower()
    if not event_key:
        raise ValueError("event_key is required")
    if label not in FEEDBACK_LABELS:
        raise ValueError(f"unsupported feedback label: {label}")
    row = {
        "event_key": event_key,
        "label": label,
        "submitted_at": _timestamp(payload.get("submitted_at")),
        "reviewed": bool(payload.get("reviewed", False)),
        "source_tier": str(payload.get("source_tier") or "").strip() or None,
        "event_type": str(payload.get("event_type") or "").strip() or None,
    }
    seen = payload.get("event_seen_at")
    delivered = payload.get("delivered_at")
    if seen and delivered:
        row["event_seen_at"] = str(seen)
        row["delivered_at"] = str(delivered)
    return row


def summarize_feedback(rows: Iterable[dict[str, Any]], *, expected_relevant: int | None = None) -> dict[str, Any]:
    """Calculate quality metrics from reviewed rows without changing policy."""
    reviewed = [row for row in rows if row.get("reviewed")]
    counts = Counter(str(row.get("label") or "") for row in reviewed)
    relevant = counts["correct"]
    false_positive = sum(counts[label] for label in ("irrelevant", "duplicate", "not_needed"))
    precision = relevant / (relevant + false_positive) if relevant + false_positive else None
    recall = relevant / expected_relevant if expected_relevant else None
    delays: list[float] = []
    for row in reviewed:
        try:
            start = datetime.fromisoformat(str(row["event_seen_at"]).replace("Z", "+00:00"))
            end = datetime.fromisoformat(str(row["delivered_at"]).replace("Z", "+00:00"))
            delays.append(max(0.0, (end - start).total_seconds()))
        except (KeyError, TypeError, ValueError):
            continue
    return {
        "reviewed_count": len(reviewed),
        "label_counts": dict(counts),
        "precision": precision,
        "recall": recall,
        "false_positive_rate": false_positive / len(reviewed) if reviewed else None,
        "alert_usefulness": relevant / len(reviewed) if reviewed else None,
        "mean_time_to_detect_seconds": sum(delays) / len(delays) if delays else None,
        "policy_update_allowed": False,
    }

