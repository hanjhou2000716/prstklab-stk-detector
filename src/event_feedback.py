"""Anonymous, reviewable feedback records for event-alert quality."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any, Iterable


FEEDBACK_LABELS = frozenset({"correct", "irrelevant", "duplicate", "wrong_direction", "insufficient_source", "too_late", "not_needed"})


def normalize_feedback(record: dict[str, Any]) -> dict[str, Any]:
    label = str(record.get("label") or "").strip().lower()
    if label not in FEEDBACK_LABELS:
        raise ValueError("unsupported feedback label")
    received = record.get("received_at")
    try:
        timestamp = datetime.fromisoformat(str(received).replace("Z", "+00:00")) if received else datetime.now(UTC)
    except ValueError as error:
        raise ValueError("received_at is invalid") from error
    return {
        "cluster_id": str(record.get("cluster_id") or ""),
        "label": label,
        "source": str(record.get("source") or "mini_app"),
        "received_at": timestamp.replace(tzinfo=timestamp.tzinfo or UTC).astimezone(UTC).isoformat(),
        "reviewed": bool(record.get("reviewed", False)),
        "anonymous": True,
    }


def summarize_feedback(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = [normalize_feedback(item) for item in records]
    reviewed = [item for item in rows if item["reviewed"]]
    counts = Counter(item["label"] for item in reviewed)
    total = len(reviewed)
    correct = counts["correct"]
    false_positive = counts["irrelevant"] + counts["not_needed"]
    delivered = [item for item in reviewed if item["label"] not in {"too_late", "insufficient_source"}]
    return {
        "reviewed_count": total,
        "label_counts": dict(counts),
        "precision": round(correct / (correct + false_positive), 4) if correct + false_positive else None,
        "false_positive_rate": round(false_positive / total, 4) if total else None,
        "too_late_rate": round(counts["too_late"] / total, 4) if total else None,
        "source_insufficiency_rate": round(counts["insufficient_source"] / total, 4) if total else None,
        "delivery_usable_rate": round(len(delivered) / total, 4) if total else None,
        "threshold_update_allowed": False,
    }