"""Deterministic data-quality SLA scoring and fail-closed gates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class QualityThresholds:
    alert_min_score: float = 70.0
    research_min_score: float = 80.0
    max_fresh_age_minutes: float = 30.0
    max_latency_ms: float = 5000.0
    max_failure_streak: int = 3


@dataclass(frozen=True)
class QualityReport:
    provider: str
    score: float
    status: str
    components: dict[str, float]
    allow_display: bool
    allow_alert: bool
    allow_research: bool
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "data_quality_score": self.score,
            "status": self.status,
            "components": dict(self.components),
            "allow_display": self.allow_display,
            "allow_alert": self.allow_alert,
            "allow_research": self.allow_research,
            "reasons": list(self.reasons),
        }


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _freshness_score(age_minutes: float | None, limit: float) -> float:
    if age_minutes is None:
        return 0.0
    if age_minutes <= 0:
        return 1.0
    return _clamp(1.0 - age_minutes / max(limit, 1.0))


def _latency_score(latency_ms: float | None, limit: float) -> float:
    if latency_ms is None:
        return 0.0
    return _clamp(1.0 - float(latency_ms) / max(limit, 1.0))


def _failure_score(streak: int, limit: int) -> float:
    return _clamp(1.0 - max(0, int(streak)) / max(limit, 1))


def _age_minutes(value: Any, *, now: datetime) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    parsed = parsed.replace(tzinfo=parsed.tzinfo or UTC)
    return max(0.0, (now.astimezone(UTC) - parsed.astimezone(UTC)).total_seconds() / 60)


def score_source(
    record: dict[str, Any],
    *,
    now: datetime | None = None,
    thresholds: QualityThresholds | None = None,
) -> QualityReport:
    """Score one provider without converting missing fields into success."""
    policy = thresholds or QualityThresholds()
    checked_at = now or datetime.now(UTC)
    provider = str(record.get("provider") or record.get("key") or "unknown")
    status = str(record.get("status") or "unknown").lower()
    availability = 1.0 if status in {"healthy", "ok", "success"} else 0.5 if status in {"partial", "degraded"} else 0.0
    latency = _latency_score(record.get("latency_ms"), policy.max_latency_ms)
    age = _age_minutes(record.get("fetched_at") or record.get("checked_at") or record.get("last_success_at"), now=checked_at)
    freshness = _freshness_score(age, policy.max_fresh_age_minutes)
    if isinstance(record.get("completeness"), (int, float)):
        completeness = _clamp(float(record["completeness"]))
    else:
        expected = record.get("expected_count")
        count = record.get("item_count")
        completeness = _clamp(float(count) / float(expected)) if isinstance(count, (int, float)) and isinstance(expected, (int, float)) and expected > 0 else 1.0 if status in {"healthy", "ok", "success"} else 0.0
    agreement = _clamp(float(record.get("cross_source_agreement", 1.0 if record.get("cross_checked") else 0.0)))
    parsing = _clamp(float(record.get("parsing_confidence", 1.0 if status in {"healthy", "ok", "success"} else 0.0)))
    failures = max(0, int(record.get("consecutive_failures") or 0))
    failure_score = _failure_score(failures, policy.max_failure_streak)
    components = {
        "availability": availability,
        "latency": latency,
        "freshness": freshness,
        "completeness": completeness,
        "cross_source_agreement": agreement,
        "parsing_confidence": parsing,
        "failure_streak": failure_score,
    }
    weights = {"availability": 25, "latency": 10, "freshness": 20, "completeness": 15, "cross_source_agreement": 15, "parsing_confidence": 10, "failure_streak": 5}
    score = round(sum(components[key] * weight for key, weight in weights.items()), 1)
    reasons: list[str] = []
    if status not in {"healthy", "ok", "success"}:
        reasons.append("source_not_healthy")
    if age is None or age > policy.max_fresh_age_minutes:
        reasons.append("stale_or_unknown_freshness")
    if record.get("stale_used") or record.get("quote_delayed"):
        reasons.append("stale_or_delayed_data")
    if not agreement:
        reasons.append("cross_source_not_confirmed")
    if failures:
        reasons.append("consecutive_failures")
    allow_display = True
    allow_alert = score >= policy.alert_min_score and not any(reason in reasons for reason in ("source_not_healthy", "stale_or_unknown_freshness", "stale_or_delayed_data", "cross_source_not_confirmed"))
    allow_research = score >= policy.research_min_score and not any(reason in reasons for reason in ("source_not_healthy", "stale_or_unknown_freshness", "stale_or_delayed_data"))
    report_status = "healthy" if score >= policy.research_min_score and not reasons else "degraded" if score >= policy.alert_min_score else "failed"
    return QualityReport(provider, score, report_status, components, allow_display, allow_alert, allow_research, tuple(reasons))


def score_sources(records: list[dict[str, Any]], *, now: datetime | None = None, thresholds: QualityThresholds | None = None) -> list[QualityReport]:
    return [score_source(record, now=now, thresholds=thresholds) for record in records]