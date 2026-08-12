"""Pure, privacy-safe Creator Intelligence release pipeline."""

from __future__ import annotations

from typing import Any

from src.creator_consensus import build_creator_consensus
from src.creator_release import build_creator_release
from src.email_intelligence import normalize_creator_insight

_PARSER_FAILURE_STATES = {"parse_failed", "unsupported_template", "invalid_source", "duplicate"}


def build_creator_intelligence_release(
    records: list[dict[str, Any]],
    *,
    parent_manifest: dict[str, Any],
    history_store: Any | None = None,
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
        if (record.get("parse_status") or record.get("source_adapter")) and not normalized["episode_title"]:
            dropped.append(f"{index}:missing_episode_title")
            continue
        if normalized["content_origin"] not in {"haojiao", "gooaye"}:
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
    artifact = build_creator_release(
        insights,
        parent_manifest=parent_manifest,
        creator_consensus=build_creator_consensus(insights),
    )
    return {
        "artifact": artifact,
        "accepted_count": len(insights),
        "dropped_count": len(dropped),
        "dropped_reasons": dropped,
        "source_state": "available" if insights else "no_creator_insights",
        "history_recorded_count": history_recorded_count,
    }


__all__ = ["build_creator_intelligence_release"]
