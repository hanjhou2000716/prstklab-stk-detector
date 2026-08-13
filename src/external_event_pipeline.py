"""Shared, fail-closed pipeline for scheduled news and live external events."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from src.event_classifier import classify_event_fields
from src.external_event_risk import cluster_external_events, notification_decision, score_prstk_risk
from src.financialjuice_contract import normalize_financialjuice

PIPELINE_VERSION = "external-event-pipeline-v1"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def build_external_event(
    record: dict[str, Any],
    *,
    source_observations: list[dict[str, Any]] | None = None,
    official_confirmed: bool = False,
    market_sync_confirmed: bool = False,
) -> dict[str, Any]:
    """Normalize one story and its corroboration into an auditable decision.

    The scheduled report and live monitor can call this function with the
    same fields. Missing official or market evidence remains pending; no
    fallback turns a discovery headline into an alert.
    """
    source = str(record.get("source") or record.get("content_origin") or "unknown").casefold()
    normalized = normalize_financialjuice(record) if source == "financialjuice" else dict(record)
    normalized.setdefault("source", source)
    normalized.setdefault("event_type", record.get("event_type") or record.get("category") or "unknown")
    normalized.setdefault("category", normalized.get("event_type"))
    normalized.setdefault("fetched_at", _now())
    normalized.setdefault("source_tier", "discovery")
    normalized["official_confirmed"] = bool(official_confirmed or record.get("official_confirmed"))
    normalized["market_sync_confirmed"] = bool(market_sync_confirmed or record.get("market_sync_confirmed"))
    classification = classify_event_fields(normalized)
    observations = [normalized, *(source_observations or [])]
    clusters = cluster_external_events(observations)
    cluster = clusters[0] if clusters else {"event_type": classification.get("category") or "unknown", "cross_source_count": 0}
    risk = score_prstk_risk(
        cluster,
        official_confirmed=normalized["official_confirmed"],
        market_sync_confirmed=normalized["market_sync_confirmed"],
        vendor_importance=normalized.get("vendor_importance"),
    )
    decision = notification_decision(risk)
    lifecycle = "confirmed" if decision["allowed"] else "pending_confirmation"
    return {
        "pipeline_version": PIPELINE_VERSION,
        "observation_id": normalized.get("observation_id") or normalized.get("gmail_message_id"),
        "event_cluster_key": cluster.get("event_cluster_key"),
        "classification": classification,
        "cluster": cluster,
        "risk": risk,
        "notification": decision,
        "lifecycle_state": lifecycle,
        "pending_reasons": list(decision.get("reasons") or normalized.get("pending_reasons") or []),
        "source_evidence": cluster.get("observations", []),
        "market_evidence": record.get("market_evidence") or [],
        "created_at": _now(),
    }


def build_external_events(
    record: dict[str, Any],
    *,
    source_observations: list[dict[str, Any]] | None = None,
    official_confirmed: bool = False,
    market_sync_confirmed: bool = False,
) -> list[dict[str, Any]]:
    """Fan out a compound FinancialJuice envelope into the shared event path.

    Non-compound records retain the historical one-event behaviour.  An
    unresolved compound envelope is visible as a blocked result and produces
    no partial events, so a malformed item cannot reach notification logic.
    """
    items = record.get("items")
    if str(record.get("parse_status") or "") == "compound_unresolved":
        return [{
            "pipeline_version": PIPELINE_VERSION,
            "observation_id": record.get("message_id"),
            "event_cluster_key": None,
            "lifecycle_state": "suppressed",
            "notification": {"allowed": False, "status": "pending", "reasons": ["compound_unresolved"]},
            "pending_reasons": ["compound_unresolved"],
            "source_evidence": [],
            "market_evidence": [],
            "parse_status": "compound_unresolved",
            "created_at": _now(),
        }]
    if isinstance(items, list) and items:
        results: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            result = build_external_event(
                {
                    **item,
                    "source": "financialjuice",
                    "content_origin": "financialjuice",
                    "event_type": item.get("candidate_event_type") or item.get("event_type") or "unknown",
                    "original_headline": item.get("original_headline") or item.get("headline"),
                    "chinese_translation": item.get("chinese_translation") or item.get("translation"),
                    "vendor_importance": item.get("vendor_importance"),
                    "source_url": item.get("source_url"),
                    "event_cluster_key": item.get("event_cluster_key"),
                },
                source_observations=source_observations,
                official_confirmed=official_confirmed,
                market_sync_confirmed=market_sync_confirmed,
            )
            result["compound_item_id"] = item.get("item_id")
            result["compound_event_cluster_key"] = item.get("event_cluster_key")
            results.append(result)
        return results
    return [build_external_event(
        record,
        source_observations=source_observations,
        official_confirmed=official_confirmed,
        market_sync_confirmed=market_sync_confirmed,
    )]


__all__ = ["PIPELINE_VERSION", "build_external_event", "build_external_events"]
