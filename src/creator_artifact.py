"""Public Creator Intelligence artifact with bounded retention.

The artifact is derived from sanitized CreatorInsight records.  It never
contains raw mail, private media paths or attachment URLs.  The latest episode
per creator is full; older public history is compact and bounded to five items
while the total public retention is capped at ten episodes per creator.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from src.creator_consensus import build_creator_consensus

PUBLIC_EPISODE_LIMIT = 10
COMPACT_HISTORY_LIMIT = 5
SCHEMA_VERSION = "1.0"
_PRIVATE_FIELDS = {"body", "raw_body", "local_path", "private_url", "attachments", "media_url", "image_url"}
_REJECT_FIELDS = _PRIVATE_FIELDS - {"image_url"}
_SAFE_FIELDS = {
    "creator_id", "creator_name", "episode_key", "episode_id", "episode_title", "published_at",
    "source_url", "content_origin", "topics", "markets", "sectors", "tickers", "key_takeaways",
    "creator_market_view", "creator_strategy_view", "creator_risk_view", "consensus_stance",
    "key_numbers", "claims", "opinions", "verification_state", "evidence_alignment",
    "prstk_correlation", "summary_image_available", "summary_image_hash", "parse_status",
    "parser_version", "created_at", "updated_at", "public_safe",
}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _time(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return ""
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC).isoformat()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _safe_insight(insight: dict[str, Any], *, compact: bool) -> dict[str, Any]:
    """Project only public fields and mark the display density explicitly."""
    projected = {key: insight[key] for key in _SAFE_FIELDS if key in insight}
    projected.pop("summary_image_url", None)
    projected["display_mode"] = "compact" if compact else "full"
    projected["public_safe"] = True
    return projected


def validate_creator_artifact(artifact: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if artifact.get("schema_version") != SCHEMA_VERSION:
        errors.append("unsupported_schema_version")
    if artifact.get("public_safe") is not True:
        errors.append("artifact_not_public_safe")
    consensus = artifact.get("creator_consensus")
    if consensus is not None:
        if not isinstance(consensus, dict):
            errors.append("creator_consensus_not_object")
        else:
            if "is_investment_signal" in consensus and consensus.get("is_investment_signal") is not False:
                errors.append("creator_consensus_is_investment_signal")
            if consensus.get("consensus_state") not in {"aligned", "mixed", "insufficient_sources", "pending_verification", "stale"}:
                if "consensus_state" in consensus:
                    errors.append("creator_consensus_state_invalid")
            if "contributors" in consensus and not isinstance(consensus.get("contributors"), list):
                errors.append("creator_consensus_contributors_missing")
            if "topic_consensus" in consensus and not isinstance(consensus.get("topic_consensus"), list):
                errors.append("creator_consensus_topics_missing")
    if any(field in artifact for field in _PRIVATE_FIELDS):
        errors.append("artifact_contains_private_fields")
    retention = artifact.get("retention")
    if not isinstance(retention, dict) or retention.get("public_per_creator") != PUBLIC_EPISODE_LIMIT:
        errors.append("retention_policy_missing")
    creators = artifact.get("creators")
    if not isinstance(creators, dict):
        return sorted(set(errors + ["creators_missing"]))
    for creator_id, value in creators.items():
        if not isinstance(value, dict) or not isinstance(value.get("episodes"), list):
            errors.append(f"{creator_id}:episodes_missing")
            continue
        episodes = value["episodes"]
        if len(episodes) > PUBLIC_EPISODE_LIMIT:
            errors.append(f"{creator_id}:retention_overflow")
        keys = [str(item.get("episode_key") or "") for item in episodes if isinstance(item, dict)]
        if len(keys) != len(set(keys)):
            errors.append(f"{creator_id}:duplicate_episode")
        for episode in episodes:
            if not isinstance(episode, dict):
                errors.append(f"{creator_id}:episode_not_object")
                continue
            if any(field in episode for field in _PRIVATE_FIELDS):
                errors.append(f"{creator_id}:private_episode_field")
            if episode.get("public_safe") is not True:
                errors.append(f"{creator_id}:episode_not_public_safe")
    return sorted(set(errors))


def build_creator_artifact(
    insights: list[dict[str, Any]],
    *,
    snapshot_id: str | None = None,
    generated_at: Any = None,
    creator_health: dict[str, Any] | None = None,
    parent_release_id: str = "",
    market_snapshot_id: str = "",
    research_snapshot_id: str = "",
    event_snapshot_id: str = "",
    creator_consensus: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a bounded public artifact from already sanitized insights."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    invalid: list[str] = []
    seen: set[str] = set()
    for index, insight in enumerate(insights):
        if not isinstance(insight, dict) or any(insight.get(field) for field in _REJECT_FIELDS):
            invalid.append(f"{index}:private_field")
            continue
        creator_id = _text(insight.get("creator_id") or insight.get("content_origin")) or "unknown"
        episode_key = _text(insight.get("episode_key"))
        if not episode_key or episode_key in seen:
            invalid.append(f"{index}:duplicate_or_missing_episode")
            continue
        seen.add(episode_key)
        grouped.setdefault(creator_id, []).append(insight)
    creators: dict[str, Any] = {}
    for creator_id, rows in grouped.items():
        rows.sort(key=lambda row: _time(row.get("published_at") or row.get("updated_at")), reverse=True)
        retained = rows[:PUBLIC_EPISODE_LIMIT]
        episodes = [
            _safe_insight(item, compact=index >= 1)
            for index, item in enumerate(retained)
        ]
        creators[creator_id] = {
            "creator_id": creator_id,
            "creator_name": _text(retained[0].get("creator_name") or creator_id),
            "health": (creator_health or {}).get(creator_id, {"creator_health": "healthy"}),
            "episodes": episodes,
            "public_episode_count": len(episodes),
        }
    timestamp = _time(generated_at) or datetime.now(UTC).isoformat()
    consensus = creator_consensus if isinstance(creator_consensus, dict) else build_creator_consensus(insights)
    material = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": timestamp,
        "parent_release_id": _text(parent_release_id),
        "market_snapshot_id": _text(market_snapshot_id),
        "research_snapshot_id": _text(research_snapshot_id),
        "event_snapshot_id": _text(event_snapshot_id),
        "creators": creators,
        "creator_consensus": consensus,
        "invalid_records": invalid,
    }
    artifact: dict[str, Any] = {
        **material,
        "snapshot_id": _text(snapshot_id) or f"creator-snapshot-{hashlib.sha256(_canonical(material)).hexdigest()[:16]}",
        "creator_health": creator_health or {},
        "retention": {
            "public_per_creator": PUBLIC_EPISODE_LIMIT,
            "compact_history_per_creator": COMPACT_HISTORY_LIMIT,
            "raw_content_public": False,
            "summary_image_public": False,
        },
        "correlation_metadata": {
            "market_snapshot_id": _text(market_snapshot_id),
            "research_snapshot_id": _text(research_snapshot_id),
            "event_snapshot_id": _text(event_snapshot_id),
        },
        "public_safe": True,
    }
    artifact["validation_errors"] = validate_creator_artifact(artifact)
    artifact["status"] = "ready" if not artifact["validation_errors"] else "unavailable"
    return artifact


__all__ = ["COMPACT_HISTORY_LIMIT", "PUBLIC_EPISODE_LIMIT", "build_creator_artifact", "validate_creator_artifact"]
