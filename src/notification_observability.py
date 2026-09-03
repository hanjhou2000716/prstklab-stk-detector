"""Safe, shared notification decision summaries.

The delivery lanes remain separate in purpose, but they expose one bounded
decision vocabulary so a successful scan cannot be mistaken for a Telegram
delivery.  This module never accepts or emits raw recipient identifiers,
tokens, message bodies, or provider payloads.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DECISION_FIELDS = (
    "scan_status",
    "candidate_type",
    "notification_expected",
    "notification_status",
    "notification_reason",
    "delivered_count",
    "failed_count",
    "last_processed_at",
    "last_candidate_at",
    "last_telegram_attempt_at",
    "last_receipt_status",
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def candidate_type(event: dict[str, Any] | None) -> str:
    """Return a stable, non-sensitive candidate category."""
    if not isinstance(event, dict):
        return "none"
    source = str(event.get("source_key") or event.get("source") or "").strip().casefold()
    if source == "financialjuice":
        return "financialjuice"
    if str(event.get("kind") or "").strip().casefold() == "market_signal":
        return "price_signal"
    event_type = str(event.get("event_type") or event.get("kind") or "event").strip().casefold()
    return event_type or "event"


def decision_summary(
    *,
    event: dict[str, Any] | None = None,
    scan_status: str = "completed",
    notification_expected: bool | None = None,
    notification_status: str = "not_attempted",
    notification_reason: str = "",
    delivered_count: int | None = None,
    failed_count: int | None = None,
    last_processed_at: str | None = None,
    last_candidate_at: str | None = None,
    last_telegram_attempt_at: str | None = None,
    last_receipt_status: str | None = None,
) -> dict[str, Any]:
    """Build a bounded decision row suitable for public health surfaces."""
    now = _now()
    expected = bool(event) if notification_expected is None else bool(notification_expected)
    candidate_at = last_candidate_at or (now if event else None)
    summary: dict[str, Any] = {
        "scan_status": str(scan_status or "unknown"),
        "candidate_type": candidate_type(event),
        "notification_expected": expected,
        "notification_status": str(notification_status or "not_attempted"),
        "notification_reason": str(notification_reason or ""),
        "delivered_count": max(0, int(delivered_count or 0)) if delivered_count is not None else None,
        "failed_count": max(0, int(failed_count or 0)) if failed_count is not None else None,
        "last_processed_at": last_processed_at or now,
        "last_candidate_at": candidate_at,
        "last_telegram_attempt_at": last_telegram_attempt_at,
        "last_receipt_status": last_receipt_status,
    }
    return {key: summary[key] for key in DECISION_FIELDS}


def merge_decision_health(
    health: dict[str, Any] | None,
    lane: str,
    summary: dict[str, Any],
) -> dict[str, Any]:
    """Attach one lane summary under the existing source-health envelope."""
    target = dict(health) if isinstance(health, dict) else {}
    existing = target.get("notification_observability")
    lanes = dict(existing) if isinstance(existing, dict) else {}
    lanes[str(lane)] = {key: summary.get(key) for key in DECISION_FIELDS}
    target["notification_observability"] = lanes
    return target


def write_summary(title: str, summary: dict[str, Any]) -> None:
    """Write a safe GitHub Actions step summary when running in Actions."""
    destination = os.getenv("GITHUB_STEP_SUMMARY")
    if not destination:
        return
    lines = [f"## {title}"]
    for key in DECISION_FIELDS:
        value = summary.get(key)
        if value is None:
            value = "unknown"
        value = str(value).replace("\r", " ").replace("\n", " ")
        lines.append(f"- {key}: {value}")
    with Path(destination).open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


__all__ = ["DECISION_FIELDS", "candidate_type", "decision_summary", "merge_decision_health", "write_summary"]
