"""Fail-closed production acceptance checks for the public release.

This module intentionally validates semantics, not just file presence.  It is
used by CI and by the Pages publisher before a release can be considered
deliverable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AcceptanceResult:
    allowed: bool
    errors: tuple[str, ...] = field(default_factory=tuple)


def _count(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def validate_production_bundle(
    *,
    manifest: dict[str, Any],
    market: dict[str, Any],
    research: dict[str, Any],
    events: dict[str, Any],
    require_production_research: bool = False,
) -> AcceptanceResult:
    """Check cross-artifact invariants before Pages or Telegram delivery."""

    errors: list[str] = []
    if manifest.get("status") != "ready":
        errors.append("manifest status is not ready")
    release_id = str(manifest.get("release_id") or "")
    if not release_id:
        errors.append("release_id is missing")

    # New research artifacts carry an explicit publication contract. Legacy
    # snapshots without these fields remain readable for rollback, but a
    # newly generated production report may never pass the delivery gate
    # while its universe is partial or a provider failed.
    scan_mode = str(research.get("scan_mode") or "")
    if require_production_research and scan_mode != "production":
        errors.append("research artifact is not a production scan")
    if scan_mode == "production" or require_production_research:
        if research.get("publish_eligible") is not True:
            errors.append("production research is not publish_eligible")
        if research.get("production_eligible") is not True:
            errors.append("production research is not production_eligible")
        research_expected = _count(research.get("universe_expected"))
        completed = _count(research.get("universe_completed"))
        scanned = _count(research.get("universe_scanned"))
        if research_expected <= 0 or completed < research_expected or scanned < research_expected:
            errors.append("production research universe is incomplete")
        if str(research.get("scan_scope") or "") != "full":
            errors.append("production research scan scope is not full")

    expected_market = str(manifest.get("market_snapshot_id") or "")
    expected_research = str(manifest.get("research_snapshot_id") or "")
    expected_events = str(manifest.get("event_snapshot_id") or "")
    for label, artifact, expected in (
        ("market", market, expected_market),
        ("research", research, expected_research),
        ("events", events, expected_events),
    ):
        actual = str(artifact.get("snapshot_id") or artifact.get("snapshot", {}).get("snapshot_id") or "")
        if expected and actual and actual != expected:
            errors.append(f"{label} snapshot does not match manifest")
        if expected and not actual:
            errors.append(f"{label} snapshot is missing")

    market_state = str(market.get("overall_state") or "")
    if market_state == "live" and (_count(market.get("stale_count")) or _count(market.get("unavailable_count"))):
        errors.append("market overall_state live contradicts stale/unavailable counts")
    for source in research.get("sources", []) if isinstance(research.get("sources"), list) else []:
        if not isinstance(source, dict):
            continue
        state = str(source.get("candidate_state") or "")
        if state == "complete" and any(source.get(name) for name in ("data_gap", "data_unavailable")):
            errors.append("research complete contradicts data gap")
        formal = _count(source.get("formal_candidates", source.get("formal_candidate_count")))
        visible = _count(source.get("visible_candidates", source.get("candidates")))
        if formal > visible:
            errors.append("research formal candidates exceed visible candidates")

    # A release with no events is valid; an event artifact with no provenance is
    # not allowed to become a high-risk notification.
    for event in events.get("events", []) if isinstance(events.get("events"), list) else []:
        if not isinstance(event, dict):
            continue
        if str(event.get("severity") or "") in {"high-risk", "critical"} and not event.get("source_evidence"):
            errors.append("high-risk event is missing source evidence")
    return AcceptanceResult(not errors, tuple(sorted(set(errors))))

