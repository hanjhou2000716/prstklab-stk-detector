"""One pre-delivery audit joining artifact contracts and quality gates."""

from __future__ import annotations

from typing import Any

from src.artifact_contract import validate_release


def validate_pre_delivery(
    *, market: dict[str, Any], research: dict[str, Any], manifest: dict[str, Any], event_health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    errors = validate_release(market=market, research=research, manifest=manifest)
    if event_health:
        if event_health.get("state") in {"failed", "no_observations"}:
            errors.append("event source health is not publishable")
        if event_health.get("stale_count", 0) and event_health.get("allow_stale_publish") is not True:
            errors.append("stale event observations require explicit publish policy")
    return {"allowed": not errors, "errors": sorted(set(errors)), "release_id": manifest.get("release_id", "")}

