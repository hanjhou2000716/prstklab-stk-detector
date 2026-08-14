"""Pure, privacy-safe Creator Intelligence release pipeline."""

from __future__ import annotations

from typing import Any

from src.creator_artifact import build_creator_artifact
from src.creator_consensus import build_creator_consensus
from src.creator_correlation import correlate_creator_insight
from src.creator_morning_batch import build_creator_morning_batch
from src.creator_provider_registry import is_known_creator
from src.creator_release import build_creator_release
from src.email_intelligence import normalize_creator_insight

_PARSER_FAILURE_STATES = {"parse_failed", "unsupported_template", "invalid_source", "duplicate"}


def build_creator_intelligence_release(
    records: list[dict[str, Any]],
    *,
    parent_manifest: dict[str, Any],
    history_store: Any | None = None,
    market_snapshot: dict[str, Any] | None = None,
    research_snapshot: dict[str, Any] | None = None,
    batch_as_of: Any | None = None,
) -> dict[str, Any]:
    """Normalize already-sanitized records and build one lineage-bound artifact.

    This boundary intentionally does not accept raw email bodies or attachments.
    Records that contain private fields or unknown creator sources are excluded
    instead of being guessed into a public insight.
    """
    insights: list[dict[str, Any]] = []
    dropped: list[str] = []
    seen: set[str] = set()
    for index, record in enumerate(records):
        if any(record.get(field) for field in ("body", "raw_body", "local_path", "private_url", "attachments")):
            dropped.append(f"{index}:private_field")
            continue
        parse_status = str(record.get("parse_status") or "normalized")
        if parse_status in _PARSER_FAILURE_STATES:
            dropped.append(f"{index}:{parse_status}")
            continue
        if record.get("source_adapter") and record.get("required_fields_present") is False:
            dropped.append(f"{index}:adapter_required_fields_missing")
            continue
        normalized = normalize_creator_insight(record)
        normalized["prstk_correlation"] = correlate_creator_insight(
            normalized,
            market_snapshot=market_snapshot,
            research_snapshot=research_snapshot,
        )
        if (record.get("parse_status") or record.get("source_adapter")) and not normalized["episode_title"]:
            dropped.append(f"{index}:missing_episode_title")
            continue
        if not is_known_creator(normalized["content_origin"]):
            dropped.append(f"{index}:unknown_creator_source")
            continue
        key = str(normalized["episode_key"])
        if key in seen:
            dropped.append(f"{index}:duplicate_episode")
            continue
        seen.add(key)
        insights.append(normalized)
    history_recorded_count = 0
    if history_store is not None:
        for insight in insights:
            history_store.append(insight)
            history_recorded_count += 1
    morning_batch = build_creator_morning_batch(insights, as_of=batch_as_of) if batch_as_of is not None else None
    artifact = build_creator_release(
        insights,
        parent_manifest=parent_manifest,
        creator_consensus=build_creator_consensus(insights),
        morning_batch=morning_batch,
    )
    public_artifact = build_creator_artifact(
        insights,
        snapshot_id=artifact.get("release_id"),
        generated_at=artifact.get("generated_at"),
        parent_release_id=artifact.get("parent_release_id", ""),
        market_snapshot_id=artifact.get("market_snapshot_id", ""),
        research_snapshot_id=artifact.get("research_snapshot_id", "") or str((research_snapshot or {}).get("snapshot_id") or ""),
        event_snapshot_id=artifact.get("event_snapshot_id", ""),
    )
    return {
        "artifact": artifact,
        "public_artifact": public_artifact,
        "accepted_count": len(insights),
        "dropped_count": len(dropped),
        "dropped_reasons": dropped,
        "source_state": "available" if insights else "no_creator_insights",
        "history_recorded_count": history_recorded_count,
    }


__all__ = ["build_creator_intelligence_release"]
