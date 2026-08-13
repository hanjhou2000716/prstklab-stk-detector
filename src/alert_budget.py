"""Alert-budget and escalation policy helpers."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

LEVELS = {"normal": 0, "warning": 1, "high-risk": 2}


def notification_identity(event: dict[str, Any]) -> str:
    """Return the shared identity used by budget, ledger and delivery receipts."""
    for key in ("notification_id", "alert_id", "compound_item_id", "event_cluster_key", "event_key", "source_url"):
        value = str(event.get(key) or "").strip()
        if value:
            return value
    return "unknown-notification"


def _quality_block_reason(event: dict[str, Any]) -> str | None:
    """Fail closed when an event explicitly carries unsafe evidence flags.

    Producers may still expose degraded observations in the Mini App, but a
    budget decision is the last common gate before delivery.  Keeping this
    check here prevents scheduled, official, and manual alert paths from
    accidentally treating stale or unverified observations as sendable.
    """
    if event.get("alert_eligible") is False:
        reasons = event.get("quality_reasons") or event.get("blocking_reason")
        if isinstance(reasons, (list, tuple)) and reasons:
            return str(reasons[0])
        return str(reasons or "quality_gate")
    if event.get("source_quality_ok") is False:
        return "source_quality_gate"
    if event.get("stale_used") is True:
        return "stale_data"
    if event.get("quote_delayed") is True:
        return "quote_delayed"
    if event.get("cross_checked") is False and event.get("requires_crosscheck") is True:
        return "crosscheck_pending"
    return None


def _level(value: Any) -> str:
    """Normalize English and UI-facing Chinese risk labels to one policy scale."""
    text = str(value or "normal").strip().lower().replace("_", "-")
    aliases = {
        "正常": "normal",
        "觀察": "normal",
        "中立": "normal",
        "警戒": "warning",
        "warning": "warning",
        "高風險": "high-risk",
        "高風險警報": "high-risk",
        "high risk": "high-risk",
    }
    return aliases.get(text, text)


def _time(value: Any, fallback: datetime) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return fallback


def decide_alert_budget(
    event: dict[str, Any], history: Iterable[dict[str, Any]], *, now: datetime | None = None,
    max_hourly: int = 8, max_updates_per_event: int = 3, cooldown_seconds: int = 1800,
) -> dict[str, Any]:
    """Decide whether an event may be sent without hiding its reason."""
    current = now or datetime.now(UTC)
    key = notification_identity(event)
    quality_reason = _quality_block_reason(event)
    if quality_reason:
        return {"allowed": False, "reason": quality_reason, "upgraded": False, "event_key": key}
    level = _level(event.get("importance") or event.get("risk_level") or "normal")
    level_value = LEVELS.get(level, 0)
    rows = [row for row in history if notification_identity(row) == key]
    recent = [_time(row.get("sent_at"), current) for row in history if current - _time(row.get("sent_at"), current) <= timedelta(hours=1)]
    previous_level = max((LEVELS.get(_level(row.get("importance") or row.get("risk_level") or "normal"), 0) for row in rows), default=-1)
    upgraded = level_value > previous_level and previous_level >= 0
    if len(recent) >= max_hourly and not upgraded:
        return {"allowed": False, "reason": "hourly_budget_exhausted", "upgraded": False, "event_key": key}
    if len(rows) >= max_updates_per_event and not upgraded:
        return {"allowed": False, "reason": "event_update_budget_exhausted", "upgraded": False, "event_key": key}
    if rows and not upgraded:
        latest = max(_time(row.get("sent_at"), current) for row in rows)
        if current - latest < timedelta(seconds=cooldown_seconds):
            return {"allowed": False, "reason": "cooldown", "upgraded": False, "event_key": key}
    return {"allowed": True, "reason": "risk_upgrade" if upgraded else "budget_available", "upgraded": upgraded, "event_key": key, "notification_id": key}

