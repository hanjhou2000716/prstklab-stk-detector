"""Shared alert-budget gate for every formal Telegram delivery path.

The event ledger is the durable source of truth.  This adapter turns its
records into the history shape consumed by :mod:`src.alert_budget`, so a
workflow cannot bypass cooldown, hourly limits, or risk upgrades by calling a
different notifier.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.alert_budget import decide_alert_budget
from src.event_ledger import EventLedger, canonical_event_key


@dataclass(frozen=True)
class DispatchDecision:
    """Auditable decision made before a Telegram send."""

    allowed: bool
    reason: str
    event_key: str
    upgraded: bool = False
    cooldown_remaining: int = 0
    hourly_usage: int = 0
    event_update_usage: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "event_key": self.event_key,
            "upgraded": self.upgraded,
            "cooldown_remaining": self.cooldown_remaining,
            "hourly_usage": self.hourly_usage,
            "event_update_usage": self.event_update_usage,
        }


def _history(ledger: EventLedger) -> list[dict[str, Any]]:
    """Project durable reminders into the budget engine's history format."""
    rows: list[dict[str, Any]] = []
    for key, record in ledger.records.items():
        sent_at = record.get("last_reminded_at")
        if not sent_at:
            continue
        rows.append(
            {
                "event_key": key,
                "event_cluster_key": key,
                "importance": record.get("risk_level", "normal"),
                "sent_at": sent_at,
            }
        )
    return rows


def evaluate_dispatch(
    event: dict[str, Any],
    *,
    ledger: EventLedger | None = None,
    now: datetime | None = None,
    max_hourly: int = 8,
    max_updates_per_event: int = 3,
    cooldown_seconds: int = 1800,
) -> DispatchDecision:
    """Apply the same budget and lifecycle gate to every notifier.

    The event is observed before the decision, but only a successful delivery
    should call :func:`record_dispatch`.  Therefore a failed Telegram call
    does not consume the budget or extend the cooldown.
    """
    current = now or datetime.now(UTC)
    active_ledger = ledger or EventLedger()
    # Snapshot history before observing the incoming state.  ``observe``
    # intentionally updates the durable risk level, but the budget decision
    # must compare against the previously delivered level to detect upgrades.
    history = _history(active_ledger)
    observed = active_ledger.observe(event, now=current)
    key = canonical_event_key(event)
    budget = decide_alert_budget(
        {**event, "event_key": key},
        history,
        now=current,
        max_hourly=max_hourly,
        max_updates_per_event=max_updates_per_event,
        cooldown_seconds=cooldown_seconds,
    )
    if not budget.get("allowed"):
        return DispatchDecision(
            allowed=False,
            reason=str(budget.get("reason") or "budget_blocked"),
            event_key=key,
            upgraded=bool(budget.get("upgraded")),
            cooldown_remaining=_cooldown_remaining(active_ledger, key, current, cooldown_seconds),
            hourly_usage=_hourly_usage(active_ledger, current),
            event_update_usage=_event_usage(active_ledger, key),
        )

    # EventLedger handles the durable 30-minute lifecycle check, including
    # risk upgrades and escalation transitions.  Keep it as a second guard so
    # legacy records cannot bypass the shared policy.
    upgraded = bool(observed.get("risk_upgraded") or observed.get("escalation_upgraded"))
    if not upgraded and not active_ledger.should_remind(event, cooldown_seconds=cooldown_seconds, now=current):
        return DispatchDecision(
            allowed=False,
            reason="cooldown",
            event_key=key,
            upgraded=upgraded,
            cooldown_remaining=_cooldown_remaining(active_ledger, key, current, cooldown_seconds),
            hourly_usage=_hourly_usage(active_ledger, current),
            event_update_usage=_event_usage(active_ledger, key),
        )
    return DispatchDecision(
        allowed=True,
        reason=str(budget.get("reason") or "budget_available"),
        event_key=key,
        upgraded=bool(budget.get("upgraded") or upgraded),
        cooldown_remaining=0,
        hourly_usage=_hourly_usage(active_ledger, current),
        event_update_usage=_event_usage(active_ledger, key),
    )


def record_dispatch(
    event: dict[str, Any], *, ledger: EventLedger | None = None, now: datetime | None = None
) -> str:
    """Record a successful delivery and return its canonical event key."""
    active_ledger = ledger or EventLedger()
    key = active_ledger.mark_reminded(event, now=now)
    active_ledger.save()
    return key


def _event_usage(ledger: EventLedger, key: str) -> int:
    return int(bool(ledger.records.get(key, {}).get("last_reminded_at")))


def _hourly_usage(ledger: EventLedger, now: datetime, window_hours: int = 1) -> int:
    count = 0
    for record in ledger.records.values():
        value = record.get("last_reminded_at")
        if not value:
            continue
        try:
            sent = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            sent = sent if sent.tzinfo else sent.replace(tzinfo=UTC)
        except ValueError:
            continue
        if 0 <= (now - sent).total_seconds() <= window_hours * 3600:
            count += 1
    return count


def _cooldown_remaining(ledger: EventLedger, key: str, now: datetime, cooldown_seconds: int) -> int:
    value = ledger.records.get(key, {}).get("last_reminded_at")
    if not value:
        return 0
    try:
        reminded = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        reminded = reminded if reminded.tzinfo else reminded.replace(tzinfo=UTC)
    except ValueError:
        return 0
    return max(0, int(cooldown_seconds - (now - reminded).total_seconds()))
