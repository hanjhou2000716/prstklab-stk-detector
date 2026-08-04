"""Public corporate-event normalisation for SEC, MOPS and issuer releases."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


EVENT_TYPES = frozenset({
    "earnings", "guidance", "margin", "capex", "insider", "merger",
    "regulatory", "capital_action", "supply_chain", "other",
})


def _time(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC).isoformat()


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _beat_miss(actual: Any, expected: Any) -> str:
    a, e = _number(actual), _number(expected)
    if a is None or e is None:
        return "unknown"
    return "beat" if a > e else "miss" if a < e else "in_line"


def normalize_corporate_event(record: dict[str, Any]) -> dict[str, Any]:
    """Normalize a public filing without making an investment-direction claim."""
    event_type = str(record.get("event_type") or "other").strip().lower()
    if event_type not in EVENT_TYPES:
        event_type = "other"
    actual_eps = record.get("actual_eps", record.get("eps"))
    expected_eps = record.get("expected_eps")
    actual_revenue = record.get("actual_revenue", record.get("revenue"))
    expected_revenue = record.get("expected_revenue")
    return {
        "ticker": str(record.get("ticker") or ""),
        "issuer": str(record.get("issuer") or record.get("company") or ""),
        "event_type": event_type,
        "form": record.get("form"),
        "title": str(record.get("title") or "").strip(),
        "summary": str(record.get("summary") or record.get("description") or "").strip(),
        "actual_eps": _number(actual_eps),
        "expected_eps": _number(expected_eps),
        "eps_result": _beat_miss(actual_eps, expected_eps),
        "actual_revenue": _number(actual_revenue),
        "expected_revenue": _number(expected_revenue),
        "revenue_result": _beat_miss(actual_revenue, expected_revenue),
        "guidance": record.get("guidance"),
        "gross_margin": _number(record.get("gross_margin")),
        "capex": _number(record.get("capex")),
        "affected_sectors": list(dict.fromkeys(str(item) for item in (record.get("affected_sectors") or []) if str(item).strip())),
        "source_url": record.get("source_url") or record.get("url"),
        "source_tier": record.get("source_tier") or "official",
        "published_at": _time(record.get("published_at") or record.get("filed_at")),
        "fetched_at": _time(record.get("fetched_at")) or datetime.now(UTC).isoformat(),
        "point_in_time": True,
        "directional_claim": False,
    }


def corporate_event_summary(event: dict[str, Any]) -> dict[str, Any]:
    """Create neutral evidence fields for the event report."""
    facts: list[str] = []
    if event.get("eps_result") != "unknown":
        facts.append(f"EPS={event['eps_result']}")
    if event.get("revenue_result") != "unknown":
        facts.append(f"revenue={event['revenue_result']}")
    if event.get("guidance") not in (None, ""):
        facts.append("guidance_disclosed")
    for field in ("gross_margin", "capex"):
        if event.get(field) is not None:
            facts.append(f"{field}_reported")
    return {
        "event_type": event.get("event_type"),
        "evidence": facts,
        "affected_sectors": event.get("affected_sectors") or [],
        "follow_up": ["核對原始申報與公布時間", "觀察相關市場的同步反應"],
        "investment_recommendation": None,
    }