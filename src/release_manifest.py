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

DEFAULT_ARTIFACTS = {
    "market.json": Path("site/data/market.json"),
    "research-report.json": Path("site/data/research-report.json"),
    "event-ledger.json": Path("site/data/event-ledger.json"),
}


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

    normalization_notes = _normalize_artifacts(loaded)
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
    market_id = content_snapshot_id(market, "market") if market else ""
    research_id = content_snapshot_id(research, "research") if research else ""
    event_id = content_snapshot_id(events, "event") if events else ""
    policy = str(policy_version or os.getenv("POLICY_VERSION") or "2026.08")
    created_at = datetime.now(UTC).isoformat()
    release_material = {
        "market_snapshot_id": market_id,
        "research_snapshot_id": research_id,
        "event_snapshot_id": event_id,
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
        "status": "invalid",
    }
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
    manifest["validation_errors"] = sorted(set(errors))
    if not errors:
        manifest["status"] = "ready"
    return manifest


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
    for name, expected in hashes.items():
        raw_path = paths.get(name)
        if not isinstance(raw_path, str):
            errors.append(f"manifest path missing: {name}")
            continue
        path = root / raw_path
        if not path.is_file():
            errors.append(f"artifact missing: {name}")
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
    args = parser.parse_args()
    manifest = build_release_manifest(root=args.root, output=args.output, policy_version=args.policy_version)
    write_release_manifest(manifest, args.output)
    print(json.dumps({"status": manifest["status"], "release_id": manifest["release_id"], "validation_errors": manifest["validation_errors"]}, ensure_ascii=False))
    return 0 if manifest["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
