"""Deterministic alert budget and cooldown policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class AlertDecision:
    allowed: bool
    reason: str
    priority: str

    def as_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "reason": self.reason, "priority": self.priority}


@dataclass
class AlertBudget:
    hourly_limit: int = 12
    event_update_limit: int = 3
    cooldown_minutes: int = 30
    quiet_start_hour: int = 23
    quiet_end_hour: int = 6

    def decide(self, *, now: datetime, event_key: str, event_times: list[datetime], hourly_times: list[datetime], priority: str = "normal", overnight: bool = False) -> AlertDecision:
        if priority == "high":
            return AlertDecision(True, "risk_upgrade_bypasses_budget", priority)
        if overnight or self.quiet_start_hour <= now.hour or now.hour < self.quiet_end_hour:
            return AlertDecision(False, "overnight_quiet_mode", priority)
        hour_ago = now - timedelta(hours=1)
        if sum(timestamp >= hour_ago for timestamp in hourly_times) >= self.hourly_limit:
            return AlertDecision(False, "hourly_budget_exhausted", priority)
        recent = [timestamp for timestamp in event_times if timestamp >= now - timedelta(minutes=self.cooldown_minutes)]
        if recent:
            return AlertDecision(False, "event_cooldown", priority)
        if len([timestamp for timestamp in event_times if timestamp >= hour_ago]) >= self.event_update_limit:
            return AlertDecision(False, "event_update_budget_exhausted", priority)
        return AlertDecision(True, "budget_available", priority)


def merge_low_risk(events: list[dict[str, Any]], *, max_items: int = 4) -> dict[str, Any]:
    """Group low-risk events into one digest while retaining evidence IDs."""
    selected = events[:max_items]
    return {"type": "low_risk_digest", "count": len(events), "events": selected, "merged": len(events) > 1}
