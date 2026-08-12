"""Build and verify an immutable public release manifest.

The manifest is the join point for market, research and event artifacts.  A
Mini App must never combine files from different releases: callers validate
the manifest first and only then load the hash-addressed artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.artifact_contract import validate_release
from src.production_acceptance import (
    production_research_contract_errors,
    validate_production_bundle,
)
from src.research_fallback import mark_stale_research_fallback

DEFAULT_ARTIFACTS = {
    "market.json": Path("site/data/market.json"),
    "research-report.json": Path("site/data/research-report.json"),
    "event-ledger.json": Path("site/data/event-ledger.json"),
}

SOURCE_HEALTH_ARTIFACT = "source-health.json"


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def content_snapshot_id(value: dict[str, Any], prefix: str) -> str:
    """Return a deterministic ID for a normalized artifact payload."""
    existing = str(value.get("snapshot_id") or "").strip()
    if len(existing) >= 8:
        return existing
    digest = hashlib.sha256(_canonical_json(value)).hexdigest()[:16]
    return f"{prefix}-{digest}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_object(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.is_file():
        return None, f"missing artifact: {path.as_posix()}"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, f"invalid artifact {path.as_posix()}: {type(exc).__name__}"
    if not isinstance(value, dict):
        return None, f"artifact must be an object: {path.as_posix()}"
    return value, None


def _source_label_from_quote(quote: dict[str, Any]) -> str | None:
    """Return a provider label only when the payload gives unambiguous evidence.

    Older snapshots occasionally carried ``source_label=Yahoo`` next to a TPEx
    URL.  This is a representational defect, not a reason to discard the
    quote; canonicalising it here keeps the release contract fail-closed while
    preserving the original source URL and timestamp.
    """
    quote_source = str(quote.get("quote_source") or "").lower()
    parsed_host = (urlparse(str(quote.get("source_url") or "")).hostname or "").lower().removeprefix("www.")
    # The URL is the strongest provenance evidence.  Older snapshots can
    # carry a stale source_domain/label from a previous fallback provider;
    # allowing those fields to override the URL creates invalid releases.
    if parsed_host:
        if "tpex.org.tw" in parsed_host:
            return "TPEx"
        if "twse.com.tw" in parsed_host:
            return "TWSE"
        if "taifex.com.tw" in parsed_host:
            return "TAIFEX"
        if parsed_host == "yahoo.com" or parsed_host.endswith(".yahoo.com"):
            return "Yahoo"
    source_domain = str(quote.get("source_domain") or "").lower().removeprefix("www.")
    if "tpex.org.tw" in source_domain or "tpex" in quote_source:
        return "TPEx"
    if "twse.com.tw" in source_domain or "twse" in quote_source:
        return "TWSE"
    if "taifex.com.tw" in source_domain or "taifex" in quote_source:
        return "TAIFEX"
    if source_domain == "yahoo.com" or source_domain.endswith(".yahoo.com"):
        return "Yahoo"
    if "yahoo" in quote_source:
        return "Yahoo"
    return None


def _date_only(value: Any) -> str:
    try:
        return str(value or "").replace("Z", "+00:00")[:10]
    except Exception:
        return ""


def _normalize_market(value: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    for collection in ("indices", "quotes"):
        rows = value.get(collection)
        if not isinstance(rows, list):
            continue
        for index, quote in enumerate(rows):
            if not isinstance(quote, dict):
                continue
            provider = _source_label_from_quote(quote)
            parsed_host = (urlparse(str(quote.get("source_url") or "")).hostname or "").lower().removeprefix("www.")
            if parsed_host and str(quote.get("source_domain") or "").strip().lower() != parsed_host:
                quote["source_domain"] = parsed_host
                notes.append(f"{collection}[{index}].source_domain={parsed_host}")
            if provider and str(quote.get("source_label") or "").strip().lower() != provider.lower():
                quote["source_label"] = provider
                notes.append(f"{collection}[{index}].source_label={provider}")
            if provider and str(quote.get("quote_source") or "").strip().lower().find(provider.lower()) < 0:
                quote["quote_source"] = f"{provider} public quote"
                notes.append(f"{collection}[{index}].quote_source={provider}")
            # Legacy snapshots can retain a current timestamp from a source
            # replaced by a stale fallback. Keep the card visible, but never
            # publish the contradictory combination as live or alertable.
            if quote.get("stale_used") is True and str(quote.get("freshness") or "").lower() == "live":
                quote["freshness"] = "recent_close"
                quote["alert_eligible"] = False
                notes.append(f"{collection}[{index}].freshness=recent_close_for_stale_used")
            technical = quote.get("technical_context")
            quote_date = _date_only(quote.get("quote_date") or quote.get("published_at") or quote.get("quote_time"))
            technical_date = _date_only(technical.get("as_of")) if isinstance(technical, dict) else ""
            if technical_date and quote_date and technical_date < quote_date and quote.get("technical_context_stale") is not True:
                quote["technical_context_stale"] = True
                notes.append(f"{collection}[{index}].technical_context_stale=true")
    return notes


def _gap_count(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float) and value.is_integer():
        return max(0, int(value))
    if isinstance(value, dict):
        numbers = [int(item) for item in value.values() if isinstance(item, (int, float)) and not isinstance(item, bool)]
        return max(0, sum(numbers)) if numbers else None
    return None


def _normalize_research(value: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    sources = value.get("sources")
    if not isinstance(sources, list):
        return notes
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            continue
        visible = source.get("visible_candidates", source.get("candidates"))
        if "visible_candidates" not in source and "candidates" in source:
            source["visible_candidates"] = visible
            notes.append(f"sources[{index}].visible_candidates=legacy candidates")
        if "candidates" not in source and "visible_candidates" in source:
            source["candidates"] = visible
            notes.append(f"sources[{index}].candidates=visible_candidates")
        gaps = _gap_count(source.get("data_gap_counts"))
        if gaps is not None and source.get("data_gap_counts") != gaps:
            source["data_gap_counts"] = gaps
            notes.append(f"sources[{index}].data_gap_counts=integer")

        # A scan summary and its published rows are produced by separate
        # steps.  If the row file is interrupted or replaced, an old summary
        # can still claim formal candidates that are not present in this
        # release.  Do not let that contradiction block every subsequent
        # release (and leave the Mini App showing an older snapshot).  Keep
        # the release usable, but downgrade the source to an explicit data
        # gap and suppress the unproven counts.
        visible_count = _gap_count(visible)
        count_mismatch = False
        for field in ("formal_candidates", "observation_candidates", "formal_candidate_count", "observation_candidate_count"):
            count = _gap_count(source.get(field))
            if count is not None and visible_count is not None and count > visible_count:
                source[field] = 0
                notes.append(f"sources[{index}].{field}=0 (exceeds visible_candidates)")
                count_mismatch = True
        if count_mismatch:
            # A summary that claims completion while its published rows are
            # empty is not a complete scan.  Normalize the machine-readable
            # state together with the candidate counts so the release can
            # remain usable without violating the complete-scan invariant.
            if source.get("scan_state") == "complete":
                source["scan_state"] = "building"
                notes.append(f"sources[{index}].scan_state=building (count mismatch)")
            source["candidate_state"] = "data_gap"
            source["blocking_reason"] = (
                "published candidate rows do not support the scan summary counts; "
                "awaiting a complete research scan"
            )
            source["data_gap_counts"] = max(gaps or 0, 1)
            notes.append(f"sources[{index}].candidate_state=data_gap (count mismatch)")
        if source.get("candidate_state") is None:
            scan_state = str(source.get("scan_state") or "")
            unavailable = source.get("data_unavailable") is True or source.get("data_gap") is True
            if scan_state == "building":
                state = "building"
            elif scan_state == "failed":
                state = "failed"
            elif unavailable or (gaps is not None and gaps > 0):
                state = "data_gap"
            elif isinstance(visible, int) and visible > 0:
                state = "available"
            else:
                state = "no_candidates"
            source["candidate_state"] = state
            notes.append(f"sources[{index}].candidate_state={state}")
    return notes


def _normalize_artifacts(loaded: dict[str, dict[str, Any]]) -> list[str]:
    """Repair legacy representational fields before hashing and auditing.

    This does not invent quotes, candidates, timestamps, or event confirmations;
    unresolved quality problems remain validation errors.
    """
    notes: list[str] = []
    market = loaded.get("market.json")
    if market:
        notes.extend(f"market: {item}" for item in _normalize_market(market))
    research = loaded.get("research-report.json")
    if research:
        notes.extend(f"research: {item}" for item in _normalize_research(research))
        if not str(research.get("snapshot_id") or "").strip():
            research["snapshot_id"] = content_snapshot_id(research, "research")
            notes.append("research: snapshot_id=deterministic")
    events = loaded.get("event-ledger.json")
    if events and not str(events.get("snapshot_id") or "").strip():
        events["snapshot_id"] = content_snapshot_id(events, "event")
        notes.append("events: snapshot_id=deterministic")
    return notes


def _write_normalized_artifact(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.normalize.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def build_release_manifest(
    *,
    root: Path | str = Path("."),
    output: Path | str = Path("site/data/release-manifest.json"),
    policy_version: str | None = None,
    artifacts: dict[str, Path] | None = None,
    require_production_research: bool = False,
    allow_stale_research: bool = False,
    research_fallback_reason: str | None = None,
    max_research_age_hours: float = 24.0,
) -> dict[str, Any]:
    """Build a manifest without fabricating readiness.

    Missing or contract-invalid files produce ``status=invalid``.  This is
    intentional: the public UI can explain an incomplete release instead of
    silently mixing an old file with a new one.
    """
    root = Path(root)
    selected = artifacts or DEFAULT_ARTIFACTS
    resolved = {name: (root / path) for name, path in selected.items()}
    loaded: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    hashes: dict[str, str] = {}
    for name, path in resolved.items():
        value, error = _read_object(path)
        if error:
            errors.append(error)
            continue
        assert value is not None
        loaded[name] = value

    # Routine market/event publishers must remain available when the bounded
    # research scan is incomplete.  Convert that artifact into an explicit
    # stale fallback before hashing it, so the release is internally
    # consistent and the UI can hide candidates instead of silently treating
    # partial research as live.  Strict production callers do not opt into
    # this path unless ``allow_stale_research`` is explicitly set.
    research_candidate = loaded.get("research-report.json")
    fallback_applied = False
    fallback_reason = None
    if allow_stale_research and research_candidate:
        research_errors = production_research_contract_errors(research_candidate)
        if research_errors:
            reason = research_fallback_reason or "; ".join(research_errors)
            loaded["research-report.json"] = mark_stale_research_fallback(
                research_candidate,
                reason,
            )
            fallback_applied = True
            fallback_reason = reason

    normalization_notes = _normalize_artifacts(loaded)
    # Publish source health after legacy normalization so its bound market
    # snapshot ID always points at the exact bytes used by the release.
    market = loaded.get("market.json")
    market_document: dict[str, Any] = market if isinstance(market, dict) else {}
    market_health = market_document.get("source_health")
    if (
        isinstance(market_health, dict)
        and {"status", "sources", "event_scan"}.issubset(market_health)
    ):
        source_health_path = root / "site" / "data" / SOURCE_HEALTH_ARTIFACT
        market_id = content_snapshot_id(market_document, "market")
        source_health = {
            "schema_version": "1.0",
            "snapshot_id": f"{market_id}-health",
            "market_snapshot_id": market_id,
            "generated_at": market_document.get("generated_at"),
            "source_health": market_health,
        }
        try:
            _write_normalized_artifact(source_health_path, source_health)
            resolved[SOURCE_HEALTH_ARTIFACT] = source_health_path
            loaded[SOURCE_HEALTH_ARTIFACT] = source_health
        except OSError as exc:
            errors.append(f"cannot persist source health artifact {source_health_path.as_posix()}: {type(exc).__name__}")
    for name, value in loaded.items():
        path = resolved[name]
        try:
            _write_normalized_artifact(path, value)
            hashes[name] = sha256_file(path)
        except OSError as exc:
            errors.append(f"cannot persist/hash artifact {path.as_posix()}: {type(exc).__name__}")

    market = loaded.get("market.json", {})
    research = loaded.get("research-report.json", {})
    events = loaded.get("event-ledger.json", {})
    backtest_contract = research.get("backtest_release_contract") if isinstance(research, dict) else None
    if not isinstance(backtest_contract, dict):
        backtest_contract = {}
    backtest_release = backtest_contract.get("backtest_release")
    backtest_state = backtest_contract.get("publication_state")
    if backtest_state not in {"ready", "blocked"}:
        backtest_state = "unavailable"
    registry = backtest_contract.get("strategy_registry")
    if not isinstance(registry, list):
        registry = []
    market_id = content_snapshot_id(market, "market") if market else ""
    research_id = content_snapshot_id(research, "research") if research else ""
    event_id = content_snapshot_id(events, "event") if events else ""
    policy = str(policy_version or os.getenv("POLICY_VERSION") or "2026.08")
    created_at = datetime.now(UTC).isoformat()
    release_material = {
        "market_snapshot_id": market_id,
        "research_snapshot_id": research_id,
        "event_snapshot_id": event_id,
        "backtest_release": backtest_release,
        "backtest_publication_state": backtest_state,
        "strategy_registry": registry,
        "artifact_hashes": hashes,
        "policy_version": policy,
    }
    release_id = f"release-{hashlib.sha256(_canonical_json(release_material)).hexdigest()[:16]}"
    public_paths = {
        name: (path.relative_to(root / "site").as_posix() if path.is_relative_to(root / "site") else path.as_posix())
        for name, path in resolved.items()
    }
    manifest: dict[str, Any] = {
        "release_id": release_id,
        "created_at": created_at,
        "market_snapshot_id": market_id,
        "research_snapshot_id": research_id,
        "event_snapshot_id": event_id,
        "backtest_release": backtest_release,
        "backtest_publication_state": backtest_state,
        "strategy_registry": registry,
        "policy_version": policy,
        "schema_versions": {
            "market": str(market.get("snapshot_schema_version") or "1.0"),
            "research": str(research.get("schema_version") or "1.0"),
            "events": str(events.get("schema_version") or "1.0"),
        },
        "artifact_hashes": hashes,
        # Paths are relative to the Pages root so the browser never needs to
        # know the repository checkout layout.
        "artifact_paths": public_paths,
        "normalization_notes": normalization_notes,
        "research_freshness": "unknown",
        "research_fallback_used": fallback_applied,
        "research_fallback_reason": fallback_reason,
        "status": "invalid",
    }
    if fallback_applied:
        # A stale report may be retained as an audit/rollback artifact, but it
        # must never be paired with a new market snapshot in a ready release.
        errors.append("stale research fallback cannot produce a ready manifest")
    if not market_id or not research_id or not event_id:
        errors.append("all three snapshot IDs are required")
    if market and research and "event-ledger.json" in loaded:
        errors.extend(
            validate_release(
                market=market,
                research=research,
                events=events,
                manifest={**manifest, "status": "ready"},
            )
        )
        if require_production_research:
            acceptance = validate_production_bundle(
                manifest={**manifest, "status": "ready"},
                market=market,
                research=research,
                events=events,
                require_production_research=True,
            )
            errors.extend(acceptance.errors)
            market_time = _parse_artifact_time(market.get("generated_at"))
            research_time = _parse_artifact_time(research.get("generated_at"))
            if market_time is None or research_time is None:
                errors.append("production release requires market/research generated_at")
            else:
                age_hours = max(0.0, (market_time - research_time).total_seconds() / 3600.0)
                if age_hours > max(0.0, float(max_research_age_hours)):
                    errors.append("research snapshot is older than production freshness window")
                    manifest["research_freshness"] = "stale"
                else:
                    manifest["research_freshness"] = "fresh"
        elif research:
            # A routine market/event publisher still needs to describe the
            # freshness of a production research snapshot.  Previously this
            # branch always emitted ``unverified`` even when the research
            # artifact was a complete production/full scan.  The resulting
            # ready manifest then failed the downstream delivery gate and
            # made every scheduled brief look stale.  Keep non-production or
            # fallback reports explicitly unverified, but compute the same
            # market-vs-research age used by the strict path whenever the
            # research contract is complete.
            market_time = _parse_artifact_time(market.get("generated_at"))
            research_time = _parse_artifact_time(research.get("generated_at"))
            is_production = (
                research.get("scan_mode") == "production"
                and research.get("scan_scope") == "full"
                and research.get("publish_eligible") is True
                and research.get("production_eligible") is True
                and not fallback_applied
            )
            if is_production and market_time is not None and research_time is not None:
                age_hours = (market_time - research_time).total_seconds() / 3600.0
                if 0 <= age_hours <= max(0.0, float(max_research_age_hours)):
                    manifest["research_freshness"] = "fresh"
                else:
                    manifest["research_freshness"] = "stale"
            else:
                manifest["research_freshness"] = "unverified"
    manifest["validation_errors"] = sorted(set(errors))
    if not errors:
        manifest["status"] = "ready"
    return manifest


def _parse_artifact_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except (TypeError, ValueError):
        return None


def write_release_manifest(manifest: dict[str, Any], output: Path | str) -> None:
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, destination)


def verify_release_files(manifest: dict[str, Any], *, root: Path | str = Path(".")) -> list[str]:
    """Verify that every manifest hash still matches the local artifact."""
    root = Path(root)
    errors: list[str] = []
    hashes = manifest.get("artifact_hashes")
    paths = manifest.get("artifact_paths")
    if not isinstance(hashes, dict) or not isinstance(paths, dict):
        return ["manifest artifact hashes/paths are missing"]
    required = ("market.json", "research-report.json", "event-ledger.json")
    for name in required:
        if name not in hashes:
            errors.append(f"manifest hash missing: {name}")
        if name not in paths:
            errors.append(f"manifest path missing: {name}")
    for name, expected in hashes.items():
        raw_path = paths.get(name)
        if not isinstance(raw_path, str):
            errors.append(f"manifest path missing: {name}")
            continue
        if not raw_path.strip():
            errors.append(f"manifest path empty: {name}")
            continue
        path = root / raw_path
        if not path.is_file():
            errors.append(f"artifact missing: {name}")
            continue
        if not isinstance(expected, str) or len(expected) != 64:
            errors.append(f"manifest hash invalid: {name}")
            continue
        try:
            actual = sha256_file(path)
        except OSError as exc:
            errors.append(f"artifact unreadable {name}: {type(exc).__name__}")
            continue
        if actual != str(expected):
            errors.append(f"artifact hash mismatch: {name}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the public release manifest")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=Path("site/data/release-manifest.json"))
    parser.add_argument("--policy-version", default=None)
    parser.add_argument("--require-production-research", action="store_true")
    parser.add_argument("--allow-stale-research", action="store_true")
    parser.add_argument("--research-fallback-reason", default=None)
    parser.add_argument("--max-research-age-hours", type=float, default=24.0)
    args = parser.parse_args()
    manifest = build_release_manifest(
        root=args.root,
        output=args.output,
        policy_version=args.policy_version,
        require_production_research=args.require_production_research,
        allow_stale_research=args.allow_stale_research,
        research_fallback_reason=args.research_fallback_reason,
        max_research_age_hours=args.max_research_age_hours,
    )
    write_release_manifest(manifest, args.output)
    print(json.dumps({"status": manifest["status"], "release_id": manifest["release_id"], "validation_errors": manifest["validation_errors"]}, ensure_ascii=False))
    return 0 if manifest["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
