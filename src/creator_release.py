"""Release contract for optional creator-intelligence artifacts.

Creator insights are an additive, fail-soft extension of a market release.
They must point at the parent market/event release and can never rewrite core
artifact hashes or make a previously valid release invalid.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _utc(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC).isoformat()


def validate_creator_release(
    creator_artifact: dict[str, Any],
    *,
    parent_manifest: dict[str, Any],
) -> list[str]:
    """Return contract errors; never mutate or reject the parent release."""
    errors: list[str] = []
    if creator_artifact.get("schema_version") not in {"1.0", "1.1"}:
        errors.append("unsupported creator release schema")
    if creator_artifact.get("public_safe") is not True:
        errors.append("creator artifact is not public_safe")
    parent_release = str(creator_artifact.get("parent_release_id") or "")
    if parent_release != str(parent_manifest.get("release_id") or ""):
        errors.append("creator artifact parent release mismatch")
    for field in ("market_snapshot_id", "event_snapshot_id"):
        if str(creator_artifact.get(field) or "") != str(parent_manifest.get(field) or ""):
            errors.append(f"creator artifact {field} mismatch")
    for item in creator_artifact.get("insights") or []:
        if not isinstance(item, dict):
            errors.append("creator insight must be an object")
            continue
        if item.get("public_safe") is not True:
            errors.append("creator insight is not public_safe")
        if item.get("verification_state") not in {"verified", "partially_verified", "unverified", "contradicted", "not_applicable"}:
            errors.append("creator insight verification state invalid")
        if item.get("raw_body") or item.get("local_path") or item.get("private_url"):
            errors.append("creator insight contains private raw fields")
        if item.get("parse_status") in {"parse_failed", "unsupported_template", "invalid_source", "duplicate"}:
            errors.append("creator insight parser failure cannot be published")
        if item.get("source_adapter") and item.get("required_fields_present") is False:
            errors.append("creator insight adapter required fields missing")
    return sorted(set(errors))


def build_creator_release(
    insights: list[dict[str, Any]],
    *,
    parent_manifest: dict[str, Any],
    generated_at: Any = None,
    creator_consensus: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an additive artifact; invalid creator data remains unavailable."""
    artifact: dict[str, Any] = {
        "schema_version": "1.0",
        "parent_release_id": str(parent_manifest.get("release_id") or ""),
        "market_snapshot_id": str(parent_manifest.get("market_snapshot_id") or ""),
        "event_snapshot_id": str(parent_manifest.get("event_snapshot_id") or ""),
        "generated_at": _utc(generated_at) or datetime.now(UTC).isoformat(),
        "insights": list(insights),
        "public_safe": True,
        "creator_consensus": creator_consensus or {
            "consensus_state": "insufficient_sources",
            "consensus_topics": [],
            "contributors": [],
            "confidence": 0.0,
            "as_of": None,
            "is_investment_signal": False,
        },
    }
    errors = validate_creator_release(artifact, parent_manifest=parent_manifest)
    artifact["validation_errors"] = errors
    artifact["status"] = "ready" if not errors else "unavailable"
    material = {key: value for key, value in artifact.items() if key not in {"release_id", "artifact_hash"}}
    artifact["artifact_hash"] = hashlib.sha256(_canonical(material)).hexdigest()
    artifact["release_id"] = f"creator-{artifact['artifact_hash'][:16]}"
    return artifact


__all__ = ["build_creator_release", "validate_creator_release"]
