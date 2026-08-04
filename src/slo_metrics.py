"""SLO calculations for source, release and delivery reliability."""

from __future__ import annotations

from typing import Any, Iterable, Mapping


def calculate_slo(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    items = list(records)
    total = len(items)
    successful = sum(item.get("status") in ("ok", "success", "complete") for item in items)
    fresh = sum(item.get("freshness") in ("live", "recent") for item in items)
    cross_checked = sum(bool(item.get("cross_checked")) for item in items)
    delivered = sum(item.get("delivery") in ("sent", "delivered", "success") for item in items)
    rate = lambda value: round(value / total, 4) if total else None
    return {"observations": total, "source_success_rate": rate(successful), "fresh_quote_rate": rate(fresh),
            "crosscheck_rate": rate(cross_checked), "telegram_delivery_rate": rate(delivered),
            "stale_quote_rate": round(sum(bool(item.get("stale_used")) for item in items) / total, 4) if total else None,
            "research_completion_rate": rate(sum(item.get("research_complete") is True for item in items))}
