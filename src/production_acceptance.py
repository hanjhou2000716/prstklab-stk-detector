"""Fail-closed production acceptance checks for the public release.

This module intentionally validates semantics, not just file presence.  It is
used by CI and by the Pages publisher before a release can be considered
deliverable.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REQUIRED_RESEARCH_STRATEGIES = frozenset({
    ("taiwan", "momentum"),
    ("taiwan", "price_action"),
    ("taiwan", "resonance"),
    ("taiwan", "value"),
    ("us", "momentum"),
    ("us", "price_action"),
    ("us", "resonance"),
    ("us", "value"),
})


@dataclass(frozen=True)
class AcceptanceResult:
    allowed: bool
    errors: tuple[str, ...] = field(default_factory=tuple)


def _read_json_object(path: Path) -> dict[str, Any]:
    """Read one JSON object for the acceptance CLI without crossing its root."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact must be an object: {path.name}")
    return value


def load_acceptance_bundle(*, manifest_path: Path, site_root: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load the three required release artifacts referenced by a manifest.

    This is intentionally separate from the Pages network gate: it gives CI,
    operators and incident responders a deterministic local command that uses
    the exact manifest paths while rejecting path traversal and missing files.
    """
    manifest_path = manifest_path.resolve()
    root = (site_root or manifest_path.parent.parent).resolve()
    try:
        manifest_path.relative_to(root)
    except ValueError as exc:
        raise ValueError("manifest must be inside site_root") from exc
    manifest = _read_json_object(manifest_path)
    paths = manifest.get("artifact_paths")
    if not isinstance(paths, dict):
        raise ValueError("manifest artifact_paths is missing")
    artifacts: dict[str, dict[str, Any]] = {"manifest": manifest}
    artifact_keys = {
        "market.json": "market",
        "research-report.json": "research",
        "event-ledger.json": "event-ledger",
    }
    for name, key in artifact_keys.items():
        raw_path = paths.get(name)
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError(f"manifest path missing: {name}")
        target = (root / raw_path).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"artifact path leaves site_root: {name}") from exc
        artifacts[key] = _read_json_object(target)
    return artifacts


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
    backtest = research.get("backtest_release_contract")
    if isinstance(backtest, dict) and backtest.get("publication_state") == "ready":
        registry = backtest.get("strategy_registry")
        if not isinstance(registry, list) or not registry:
            errors.append("ready backtest contract requires strategy_registry")
        else:
            registry_ids = {str(row.get("strategy_id")) for row in registry if isinstance(row, dict) and row.get("strategy_id")}
            candidates = research.get("candidates")
            if isinstance(candidates, list):
                for index, candidate in enumerate(candidates):
                    if isinstance(candidate, dict):
                        strategy_id = candidate.get("strategy") or candidate.get("strategy_id")
                        if strategy_id and str(strategy_id) not in registry_ids:
                            errors.append(f"research candidate {index} strategy is absent from ready backtest registry")
    if str(research.get("scan_mode") or "") != "production":
        errors.append("research artifact is not a production scan")
    mixed_strategy = research.get("publication_state") == "mixed_strategy"
    if research.get("publish_eligible") is not True:
        errors.append("production research is not publish_eligible")
    if not mixed_strategy and research.get("production_eligible") is not True:
        errors.append("production research is not production_eligible")
    if mixed_strategy and research.get("production_eligible") is True:
        errors.append("mixed strategy research cannot be production_eligible")
    if not mixed_strategy and str(research.get("scan_scope") or "") != "full":
        errors.append("production research scan scope is not full")
    run = research.get("research_run")
    if not isinstance(run, dict):
        errors.append("production research run provenance is missing")
    else:
        if not str(run.get("run_id") or "").strip():
            errors.append("production research run_id is missing")
        if not str(run.get("source_commit_sha") or "").strip():
            errors.append("production research source_commit_sha is missing")
        if str(run.get("scan_mode") or "") != "production":
            errors.append("research run scan mode does not match production")
        if not mixed_strategy and str(run.get("scan_scope") or "") != "full":
            errors.append("research run scan scope is not full")
        if mixed_strategy and str(run.get("scan_scope") or "") not in {"full", "bounded"}:
            errors.append("mixed strategy research run scan scope is invalid")
        if str(research.get("run_id") or "") != str(run.get("run_id") or ""):
            errors.append("research run_id does not match research_run provenance")
    generated_at = _parse_time(research.get("generated_at"))
    finished_at = _parse_time(run.get("run_finished_at")) if isinstance(run, dict) else None
    if generated_at is None:
        errors.append("production research generated_at is missing or invalid")
    if finished_at is None:
        errors.append("production research run_finished_at is missing or invalid")
    if generated_at is not None and finished_at is not None:
        if generated_at > finished_at + timedelta(minutes=5):
            errors.append("production research generated_at is after run_finished_at")
    expected = _count(research.get("universe_expected"))
    scanned = _count(research.get("universe_scanned"))
    completed = _count(research.get("universe_completed"))
    if not mixed_strategy:
        if expected <= 0 or scanned < expected or completed < expected:
            errors.append("production research universe is incomplete")
        if scanned != completed + _count(research.get("universe_failed")):
            errors.append("production research universe counts are inconsistent")
        if _count(research.get("universe_failed")):
            errors.append("production research contains failed universe records")
    for index, source in enumerate(research.get("sources", [])) if isinstance(research.get("sources"), list) else []:
        if not isinstance(source, dict):
            errors.append(f"research source {index} is not an object")
            continue
        scan_state = str(source.get("scan_state") or "")
        historical = mixed_strategy and source.get("historical_fallback") is True
        if historical:
            # The current attempt is intentionally visible as failed/building;
            # its old rows are validated as historical and never count as a
            # current complete scan.
            visible = _count(source.get("visible_candidates", source.get("candidates")))
            if visible == 0:
                errors.append(f"research source {index} historical fallback has no rows")
            continue
        if mixed_strategy and scan_state in {"failed", "building"}:
            # A strategy without a last-good version is still represented in
            # the eight-entry matrix, but it must not block other complete
            # strategies from publishing this mixed-date research page.
            continue
        if scan_state != "complete":
            errors.append(f"research source {index} is not complete")
        if scan_state == "complete" and any(
            source.get(key) is True for key in ("source_unavailable", "data_unavailable", "provider_failed")
        ):
            errors.append(f"research source {index} complete state contradicts unavailable source")
        failed = _count(source.get("failed_records", source.get("failed", source.get("universe_failed"))))
        requested = _count(source.get("requested_records", source.get("requested", source.get("universe_expected"))))
        completed_source = _count(source.get("complete_records", source.get("data_complete", source.get("universe_completed"))))
        scanned_source = _count(source.get("universe_scanned", source.get("requested", source.get("universe_expected"))))
        if requested <= 0 or scanned_source < requested or completed_source < requested or failed:
            errors.append(f"research source {index} universe is incomplete")
        if scanned_source != completed_source + failed:
            errors.append(f"research source {index} universe counts are inconsistent")
        candidate_state = str(source.get("candidate_state") or "")
        visible = _count(source.get("visible_candidates", source.get("candidates")))
        if candidate_state == "available" and visible == 0:
            errors.append(f"research source {index} available state has no visible candidates")
        if candidate_state == "no_candidates" and visible:
            errors.append(f"research source {index} no_candidates state has visible candidates")
        if scan_state == "complete" and candidate_state in {"data_gap", "data_unavailable", "failed", "building"}:
            errors.append(f"research source {index} complete state contradicts candidate state {candidate_state}")
    return sorted(set(errors))


def production_strategy_matrix_errors(research: dict[str, Any]) -> list[str]:
    """Require every market/strategy source for a strict public release.

    Aggregate universe counts are not sufficient evidence of a complete
    research release: a producer could accidentally omit one strategy while
    reporting the other rows as complete.  The matrix is deliberately
    explicit so a missing or duplicated source fails closed instead of
    becoming an empty strategy drawer in the Mini App.
    """
    sources = research.get("sources")
    if not isinstance(sources, list):
        return ["production research source matrix is missing"]
    seen: list[tuple[str, str]] = []
    errors: list[str] = []
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            continue
        key = (str(source.get("market") or "").strip().lower(), str(source.get("strategy") or "").strip().lower())
        if key in seen:
            errors.append(f"production research source matrix has duplicate {key[0]}/{key[1]} at index {index}")
        seen.append(key)
    actual = set(seen)
    missing = sorted(REQUIRED_RESEARCH_STRATEGIES - actual)
    if missing:
        errors.append("production research source matrix missing: " + ", ".join(f"{market}/{strategy}" for market, strategy in missing))
    unknown = sorted(actual - REQUIRED_RESEARCH_STRATEGIES)
    if unknown:
        errors.append("production research source matrix has unknown entries: " + ", ".join(f"{market}/{strategy}" for market, strategy in unknown))
    if research.get("publication_state") == "mixed_strategy":
        rows = research.get("strategy_publication")
        by_key = {
            (str(item.get("market")), str(item.get("strategy"))): item
            for item in rows if isinstance(item, dict)
        } if isinstance(rows, list) else {}
        if set(by_key) != REQUIRED_RESEARCH_STRATEGIES:
            errors.append("mixed strategy publication matrix is incomplete")
        elif not any(item.get("eligible") is True for item in by_key.values()):
            errors.append("mixed strategy publication has no eligible strategy")
    return errors


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
    if require_production_research and not explicit_fallback:
        errors.extend(production_strategy_matrix_errors(research))

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


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a local PRStK release bundle.")
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Path to release-manifest.json (normally site/data/release-manifest.json).",
    )
    parser.add_argument(
        "--site-root",
        type=Path,
        help="Root containing the manifest's artifact paths; defaults to the manifest's site root.",
    )
    parser.add_argument(
        "--require-production-research",
        action="store_true",
        help="Require a complete production research matrix instead of allowing a legacy snapshot.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run a fail-closed local acceptance check and emit machine-readable JSON."""
    args = _build_cli_parser().parse_args(argv)
    try:
        bundle = load_acceptance_bundle(manifest_path=args.manifest, site_root=args.site_root)
        result = validate_production_bundle(
            manifest=bundle["manifest"],
            market=bundle["market"],
            research=bundle["research"],
            events=bundle["event-ledger"],
            require_production_research=args.require_production_research,
        )
        payload = {
            "allowed": result.allowed,
            "release_id": bundle["manifest"].get("release_id"),
            "errors": list(result.errors),
        }
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        payload = {"allowed": False, "release_id": None, "errors": [str(exc)]}
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if payload["allowed"] else 1


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI smoke test
    raise SystemExit(main())

