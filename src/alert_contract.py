"""Validated, traceable envelope shared by every notification path."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

ALERT_TYPES = {"briefing", "price_signal", "macro_event", "corporate_event", "geopolitical_event", "market_risk", "source_health", "research_observation", "deescalation", "resolution"}
LIFECYCLE_STATES = {"detected", "observation", "pending_confirmation", "confirmed", "escalated", "deescalated", "resolved", "suppressed"}
SEVERITIES = {"normal", "warning", "high-risk"}

@dataclass
class AlertEnvelope:
    alert_id: str
    event_cluster_key: str
    alert_type: str
    lifecycle_state: str
    severity: str
    title: str
    short_caption: str
    release_id: str
    snapshot_id: str
    created_at: str
    market: str = ""
    ticker: str | None = None
    trigger_reason: str = ""
    metrics: list[dict[str, Any]] = field(default_factory=list)
    source_evidence: list[dict[str, Any]] = field(default_factory=list)
    market_evidence: list[dict[str, Any]] = field(default_factory=list)
    data_quality_score: float | None = None
    policy_version: str = ""
    invalidation_condition: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> None:
        if self.alert_type not in ALERT_TYPES or self.lifecycle_state not in LIFECYCLE_STATES or self.severity not in SEVERITIES:
            raise ValueError("invalid alert type, lifecycle state, or severity")
        if not self.alert_id or not self.event_cluster_key or not self.title or not self.release_id or not self.snapshot_id:
            raise ValueError("alert identity and release provenance are required")
        if len(self.short_caption) > 40:
            raise ValueError("short_caption exceeds 40 characters")
        if self.data_quality_score is not None and not 0 <= self.data_quality_score <= 100:
            raise ValueError("data_quality_score must be between 0 and 100")
        parsed = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("created_at must include timezone")

    @classmethod
    def from_event(cls, event: dict[str, Any], *, release_id: str, snapshot_id: str, short_caption: str, lifecycle_state: str = "observation") -> AlertEnvelope:
        now = datetime.now(UTC).isoformat()
        item = cls(
            alert_id=str(event.get("alert_id") or event.get("event_key") or f"alert-{snapshot_id}"),
            event_cluster_key=str(event.get("event_cluster_key") or event.get("event_key") or "unknown-event"),
            alert_type=str(event.get("alert_type") or event.get("kind") or "market_risk"),
            lifecycle_state=lifecycle_state,
            severity=str(event.get("severity") or event.get("importance") or "normal"),
            title=str(event.get("title") or "市場事件"), short_caption=short_caption,
            release_id=release_id, snapshot_id=snapshot_id, created_at=now,
            market=str(event.get("market") or ""), ticker=event.get("ticker"),
            trigger_reason=str(event.get("trigger_reason") or event.get("classification_reason") or ""),
            metrics=list(event.get("metrics") or []), source_evidence=list(event.get("source_evidence") or []),
            market_evidence=list(event.get("market_evidence") or []),
            data_quality_score=event.get("data_quality_score"), policy_version=str(event.get("policy_version") or ""),
            invalidation_condition=str(event.get("invalidation_condition") or ""),
        )
        item.validate()
        return item
