"""Deterministic, non-directional consensus for public creator insights."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

_STANCES = {"risk_on", "risk_off", "neutral"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)


def _topics(record: dict[str, Any]) -> list[str]:
    values = record.get("topics") or []
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(_text(value).casefold() for value in values if _text(value)))


def _contributors(records: list[dict[str, Any]]) -> list[str]:
    values = (_text(item.get("creator_id") or item.get("content_origin")) for item in records)
    return sorted({value for value in values if value})


def build_creator_consensus(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Describe comparable creator views without inferring from prose."""
    contributors = _contributors(records)
    topic_records: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        for topic in _topics(record):
            topic_records.setdefault(topic, []).append(record)

    topics: list[dict[str, Any]] = []
    explicit_stances: list[str] = []
    for topic in sorted(topic_records):
        items = topic_records[topic]
        topic_contributors = _contributors(items)
        stances = sorted({
            _text(item.get("consensus_stance")).casefold()
            for item in items
            if _text(item.get("consensus_stance")).casefold() in _STANCES
        })
        explicit_stances.extend(stances)
        topics.append({
            "topic": topic,
            "contributors": topic_contributors,
            "contributor_count": len(topic_contributors),
            "episode_count": len(items),
            "stance": stances[0] if len(stances) == 1 else "mixed" if len(stances) > 1 else "unknown",
            "evidence_state": "comparable" if len(stances) == 1 and len(topic_contributors) >= 2 else "insufficient",
        })

    if len(contributors) < 2:
        state, confidence = "insufficient_sources", 0.0
    elif not explicit_stances:
        state, confidence = "pending_verification", 0.2
    elif len(set(explicit_stances)) == 1:
        state, confidence = "aligned", min(0.8, 0.4 + 0.1 * len(contributors))
    else:
        state, confidence = "mixed", 0.3

    dates = [
        date
        for record in records
        for date in (_time(record.get("updated_at")) or _time(record.get("published_at")),)
        if date is not None
    ]
    return {
        "consensus_state": state,
        "consensus_topics": topics,
        "contributors": contributors,
        "confidence": round(confidence, 3),
        "as_of": max(dates).isoformat() if dates else None,
        "is_investment_signal": False,
    }


__all__ = ["build_creator_consensus"]
