"""Rolling source health history and observability summaries."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping


def summarize_source_history(records: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record.get("source") or record.get("provider") or "unknown")].append(record)
    result: dict[str, dict[str, Any]] = {}
    for source, items in grouped.items():
        successful = [item for item in items if item.get("status") in ("ok", "success", "complete")]
        latencies = [float(item["latency_ms"]) for item in items if item.get("latency_ms") is not None]
        result[source] = {"observations": len(items), "success_rate": round(len(successful) / len(items), 4) if items else 0,
                          "last_success": max((str(item.get("fetched_at")) for item in successful), default=None),
                          "average_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
                          "stale_cache_uses": sum(bool(item.get("stale_used")) for item in items),
                          "crosscheck_success_rate": round(sum(bool(item.get("cross_checked")) for item in items) / len(items), 4) if items else 0,
                          "parser_errors": sum(item.get("error_type") == "parser" for item in items),
                          "rate_limits": sum(item.get("error_type") == "rate_limit" for item in items)}
    return result
