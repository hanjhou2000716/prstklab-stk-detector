"""Deterministic binding between private creator media and an observation.

The Gmail attachment itself never enters a public artifact.  This contract
binds a validated private media summary to the sanitized observation and
episode identity, so a stale image cannot accidentally be shown for another
edition.  Invalid media degrades to text-only delivery rather than a blank
card.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from src.creator_media import creator_media_summary


def _hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def bind_creator_media(
    *,
    observation_id: str,
    episode_key: str,
    media_record: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return a public-safe, deterministic media binding.

    ``media_record`` is expected to be the result of
    :func:`validate_creator_media`; accepting an unvalidated record is a
    fail-closed error.  The returned object never contains bytes, local paths,
    Gmail IDs, or download URLs.
    """
    observation = str(observation_id or "").strip()
    episode = str(episode_key or "").strip()
    if not observation or not episode:
        raise ValueError("media binding requires observation_id and episode_key")
    summary = creator_media_summary(media_record or {})
    errors = list(summary.get("validation_errors") or [])
    if summary.get("availability") != "private_ready" or errors or not summary.get("sha256"):
        return {
            "binding_id": "",
            "observation_ref": _hash(observation)[:20],
            "episode_ref": _hash(episode)[:20],
            "media_mode": "text_only",
            "media": {"availability": "unavailable", "validation_errors": errors, "public_safe": True},
            "public_safe": True,
            "binding_status": "degraded",
            "reason": "media_validation_failed",
        }
    binding_id = "media-bind-" + _hash({
        "observation": observation,
        "episode": episode,
        "sha256": summary["sha256"],
    })[:24]
    return {
        "binding_id": binding_id,
        "observation_ref": _hash(observation)[:20],
        "episode_ref": _hash(episode)[:20],
        "media_mode": "photo" if str(summary.get("mime_type", "")).startswith("image/") else "audio",
        "media": summary,
        "public_safe": True,
        "binding_status": "bound",
        "reason": "validated_private_media",
    }


__all__ = ["bind_creator_media"]
