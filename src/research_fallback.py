"""Explicit, non-live research fallback metadata."""

from __future__ import annotations

from typing import Any


def mark_stale_research_fallback(report: dict[str, Any], reason: str) -> dict[str, Any]:
    """Mark a last-known-good artifact as degraded without presenting it as live.

    Candidate rows remain in the artifact for audit/rollback, while consumers
    are required to hide them because the report is expired and blocked.
    """
    payload = dict(report)
    payload["availability"] = "expired"
    payload["research_fallback_used"] = True
    payload["research_freshness"] = "stale_fallback"
    payload["publication_state"] = "fallback"
    payload["production_eligible"] = False
    payload["publish_eligible"] = False
    payload["stale_used"] = True
    payload["fallback_reason"] = reason
    payload["blocking_reason"] = reason
    payload["fallback_from_generated_at"] = report.get("generated_at")
    sources = []
    for source in report.get("sources") or []:
        if not isinstance(source, dict):
            sources.append(source)
            continue
        item = dict(source)
        item["stale_fallback"] = True
        item["scan_state"] = "failed"
        item["candidate_state"] = "data_gap"
        item["blocking_reason"] = reason
        sources.append(item)
    if sources:
        payload["sources"] = sources
    return payload
