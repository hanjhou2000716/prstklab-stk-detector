"""Freshness, completeness and cross-source quality scoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class QualityThresholds:
    max_age_minutes: float = 15.0
    warning_age_minutes: float = 60.0
    alert_min_score: float = 80.0
    display_min_score: float = 40.0


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC)


def freshness_state(fetched_at: Any, *, now: datetime | None = None, thresholds: QualityThresholds | None = None) -> tuple[str, float | None]:
    config = thresholds or QualityThresholds()
    timestamp = _parse_timestamp(fetched_at)
    if timestamp is None:
        return "unavailable", None
    reference = now or datetime.now(UTC)
    reference = reference.replace(tzinfo=reference.tzinfo or UTC)
    age = max(0.0, (reference - timestamp).total_seconds() / 60)
    if age <= config.max_age_minutes:
        return "fresh", age
    if age <= config.warning_age_minutes:
        return "recent", age
    return "stale", age


def score_source(
    record: dict[str, Any],
    *,
    now: datetime | None = None,
    thresholds: QualityThresholds | None = None,
) -> dict[str, Any]:
    """Return an auditable 0–100 score and alert/display eligibility.

    Missing evidence receives zero for that dimension.  The score never
    upgrades a stale or unverified source to alert-eligible.
    """
    config = thresholds or QualityThresholds()
    freshness, age = freshness_state(record.get("fetched_at") or record.get("checked_at"), now=now, thresholds=config)
    availability = 100.0 if str(record.get("status", "")).lower() in {"healthy", "ok", "success"} else 0.0
    completeness = max(0.0, min(100.0, float(record.get("completeness", 0) or 0)))
    cross_source = 100.0 if record.get("cross_checked") is True else 0.0
    parsing = max(0.0, min(100.0, float(record.get("parsing_confidence", 0) or 0)))
    latency = max(0.0, min(100.0, float(record.get("latency_score", 100 if freshness in {"fresh", "recent"} else 0) or 0)))
    freshness_score = {"fresh": 100.0, "recent": 70.0, "stale": 0.0, "unavailable": 0.0}.get(freshness, 0.0)
    score = round(
        availability * 0.25
        + freshness_score * 0.25
        + completeness * 0.15
        + cross_source * 0.15
        + parsing * 0.10
        + latency * 0.10,
        1,
    )
    alert_eligible = score >= config.alert_min_score and freshness in {"fresh", "recent"} and cross_source >= 100
    return {
        "provider": record.get("provider") or record.get("source") or "unknown",
        "freshness": freshness,
        "age_minutes": round(age, 1) if age is not None else None,
        "availability": availability,
        "completeness": completeness,
        "cross_source_agreement": cross_source,
        "parsing_confidence": parsing,
        "latency_score": latency,
        "data_quality_score": score,
        "display_eligible": score >= config.display_min_score,
        "alert_eligible": alert_eligible,
        "stale_used": bool(record.get("stale_used")),
        "reasons": _reasons(freshness, cross_source, completeness, availability),
    }


def _reasons(freshness: str, cross_source: float, completeness: float, availability: float) -> list[str]:
    reasons: list[str] = []
    if availability == 0:
        reasons.append("source_unavailable")
    if freshness in {"stale", "unavailable"}:
        reasons.append("quote_stale_or_missing")
    if completeness < 100:
        reasons.append("payload_incomplete")
    if cross_source < 100:
        reasons.append("crosscheck_missing")
    return reasons
