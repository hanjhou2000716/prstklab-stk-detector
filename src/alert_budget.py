"""Alert-budget and escalation policy helpers."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

LEVELS = {"normal": 0, "warning": 1, "high-risk": 2}


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
    key = str(event.get("event_key") or event.get("event_cluster_key") or event.get("source_url") or "").strip()
    level = _level(event.get("importance") or event.get("risk_level") or "normal")
    level_value = LEVELS.get(level, 0)
    rows = [row for row in history if str(row.get("event_key") or row.get("event_cluster_key") or "") == key]
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
    return {"allowed": True, "reason": "risk_upgrade" if upgraded else "budget_available", "upgraded": upgraded, "event_key": key}

