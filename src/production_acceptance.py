"""Fail-closed production acceptance checks for the public release.

This module intentionally validates semantics, not just file presence.  It is
used by CI and by the Pages publisher before a release can be considered
deliverable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
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


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except (TypeError, ValueError):
        return None


def production_research_contract_errors(research: dict[str, Any]) -> list[str]:
    """Return errors for a research artifact that is eligible for publication.

    A report is not production-ready merely because it has rows.  The scan
    must cover the declared universe, use the production/full contract and
    explicitly opt in to publication.  This helper is shared by manifest and
    delivery gates so a workflow cannot accidentally bypass the same rules.
    """
    errors: list[str] = []
    if str(research.get("scan_mode") or "") != "production":
        errors.append("research artifact is not a production scan")
    if research.get("publish_eligible") is not True:
        errors.append("production research is not publish_eligible")
    if research.get("production_eligible") is not True:
        errors.append("production research is not production_eligible")
    if str(research.get("scan_scope") or "") != "full":
        errors.append("production research scan scope is not full")
    expected = _count(research.get("universe_expected"))
    scanned = _count(research.get("universe_scanned"))
    completed = _count(research.get("universe_completed"))
    if expected <= 0 or scanned < expected or completed < expected:
        errors.append("production research universe is incomplete")
    for index, source in enumerate(research.get("sources", [])) if isinstance(research.get("sources"), list) else []:
        if not isinstance(source, dict):
            errors.append(f"research source {index} is not an object")
            continue
        if str(source.get("scan_state") or "") != "complete":
            errors.append(f"research source {index} is not complete")
        failed = _count(source.get("failed_records", source.get("failed")))
        requested = _count(source.get("requested_records", source.get("requested")))
        completed_source = _count(source.get("complete_records", source.get("data_complete")))
        if requested <= 0 or completed_source < requested or failed:
            errors.append(f"research source {index} universe is incomplete")
    return sorted(set(errors))


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
    explicit_fallback = bool(
        research.get("research_fallback_used") is True
        or research.get("publication_state") == "fallback"
    )
    if require_production_research and explicit_fallback:
        errors.append("production release cannot use stale research fallback")
    elif require_production_research and not explicit_fallback:
        errors.extend(production_research_contract_errors(research))
    elif scan_mode == "production" and not explicit_fallback:
        errors.extend(production_research_contract_errors(research))

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

