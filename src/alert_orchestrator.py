"""Compose one evidence-backed alert decision for every delivery path.

The existing market, official-event and scheduled pipelines each collect
different evidence.  This module is the small shared boundary that turns
that evidence into an :class:`AlertEnvelope`, a lifecycle transition and an
Alert Budget decision without sending anything itself.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from src.alert_budget import decide_alert_budget
from src.alert_caption import make_caption
from src.alert_contract import AlertEnvelope
from src.alert_lifecycle import transition, transition_record
from src.material_change import has_material_change


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _state(event: dict[str, Any], budget_allowed: bool) -> tuple[str, dict[str, Any]]:
    """Apply lifecycle rules using only explicitly supplied evidence."""
    current = str(event.get("lifecycle_state") or "detected")
    evidence = {
        "official_confirmed": event.get("official_confirmed") is True,
        "second_source": event.get("second_source") is True,
        "market_sync": event.get("market_sync") is True,
        "material_change": event.get("material_change") is True,
        "condition_active": event.get("condition_active", True) is not False,
        "budget_allowed": budget_allowed,
    }
    return transition(current, **evidence), evidence


def prepare_alert(
    event: dict[str, Any],
    *,
    release_id: str,
    snapshot_id: str,
    history: Iterable[dict[str, Any]] = (),
    previous_change: float | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a validated alert decision, without performing delivery.

    This is intentionally side-effect free so scheduled jobs, the Worker API
    and offline tests all use the same policy.  Missing evidence leaves the
    alert pending/suppressed rather than inventing confirmation.
    """
    current = now or datetime.now(UTC)
    item = dict(event)
    item.setdefault("alert_id", item.get("event_key") or f"alert-{snapshot_id}")
    item.setdefault("event_cluster_key", item.get("event_key") or item["alert_id"])
    item.setdefault("created_at", current.isoformat())
    item["material_change"] = bool(
        item.get("material_change")
        or has_material_change(
            previous_change=previous_change,
            current_change=_number(item.get("change_percent")),
            asset_class=str(item.get("asset_class") or "market_index"),
            direction_reversed=item.get("direction_reversed") is True,
            new_evidence=item.get("new_evidence") is True,
            lifecycle_change=item.get("lifecycle_change") is True,
        )
    )
    budget = decide_alert_budget(item, history, now=current)
    lifecycle, evidence = _state(item, bool(budget.get("allowed")))
    state_label = {
        "confirmed": "雙來源同向",
        "escalated": "風險升級",
        "suppressed": "暫不推播",
        "pending_confirmation": "等待核對",
        "resolved": "事件解除",
    }.get(lifecycle, "觀察")
    caption = make_caption(
        subject=str(item.get("title") or item.get("market") or "市場事件"),
        change=str(item.get("change") or item.get("change_percent") or ""),
        state=state_label,
        verified=lifecycle in {"confirmed", "escalated"},
    )
    envelope = AlertEnvelope.from_event(
        {**item, "lifecycle_state": lifecycle},
        release_id=release_id,
        snapshot_id=snapshot_id,
        short_caption=caption,
        lifecycle_state=lifecycle,
    )
    envelope.validate()
    return {
        "alert": envelope.to_dict(),
        "lifecycle": transition_record(str(item.get("lifecycle_state") or "detected"), evidence),
        "budget": budget,
        "material_change": item["material_change"],
        "delivery_allowed": bool(budget.get("allowed")) and lifecycle != "suppressed",
    }


__all__ = ["prepare_alert"]
