"""Fail-closed release verification immediately before notifications."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests

from src.artifact_contract import validate_news_release, validate_release, validate_source_health_artifact
from src.asset_contract import validate_assets
from src.creator_artifact import validate_creator_artifact
from src.creator_release import validate_creator_release
from src.production_acceptance import validate_production_bundle
from src.release_manifest import verify_release_files


def _external_observation_lineage_errors(market: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    """Ensure sanitized external observations belong to this market release."""
    if "external_observation_count" not in manifest:
        return []
    rows = market.get("external_observations")
    if not isinstance(rows, list):
        rows = []
    identities: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        observation_id = str(row.get("observation_id") or "").strip()
        source = str(row.get("source") or row.get("content_origin") or "").strip().casefold()
        if observation_id:
            identities.append({"observation_id": observation_id, "source": source})
    identities.sort(key=lambda item: (item["observation_id"], item["source"]))
    actual_hash = hashlib.sha256(json.dumps(identities, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    errors: list[str] = []
    declared_count = manifest.get("external_observation_count")
    try:
        declared_count_value = int(declared_count) if declared_count is not None else 0
    except (TypeError, ValueError):
        errors = ["external observation count is not an integer"]
        declared_count_value = -1
    else:
        errors = []
    if declared_count_value != len(identities):
        errors.append("external observation count does not match manifest")
    declared_hash = str(manifest.get("external_observation_ids_hash") or "")
    if declared_hash and declared_hash != actual_hash:
        errors.append("external observation IDs hash does not match manifest")
    declared_sources = sorted(str(item) for item in (manifest.get("external_observation_sources") or []))
    actual_sources = sorted({item["source"] for item in identities if item["source"]})
    if declared_sources != actual_sources:
        errors.append("external observation sources do not match manifest")
    return errors


def _cache_busted_url(url: str, *, release_id: str, attempt: int) -> str:
    """Avoid a stale Pages/CDN response during propagation verification."""
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({"release_id": release_id, "attempt": str(attempt)})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@dataclass(frozen=True)
class ReleaseGateResult:
    allowed: bool
    release_id: str = ""
    snapshot_id: str = ""
    errors: tuple[str, ...] = field(default_factory=tuple)
    manifest: dict[str, Any] = field(default_factory=dict)


def _validate_creator_artifact(artifact: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    """Validate an optional creator artifact against the exact parent release."""
    errors = validate_creator_release(
        artifact,
        parent_manifest={
            "release_id": manifest.get("release_id"),
            "market_snapshot_id": manifest.get("market_snapshot_id"),
            "research_snapshot_id": manifest.get("research_snapshot_id"),
            "event_snapshot_id": manifest.get("event_snapshot_id"),
        },
    )
    declared_id = manifest.get("creator_release_id")
    if declared_id and str(artifact.get("release_id") or "") != str(declared_id):
        errors.append("creator artifact release_id does not match manifest")
    if manifest.get("creator_status") == "ready" and artifact.get("status") != "ready":
        errors.append("manifest declares creator release ready but artifact is not ready")
    return sorted(set(errors))


def _validate_creator_public_artifact(artifact: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    """Validate the bounded public Creator artifact without trusting its status."""
    errors = validate_creator_artifact(artifact)
    for artifact_field in ("parent_release_id", "market_snapshot_id", "research_snapshot_id", "event_snapshot_id"):
        expected = manifest.get("release_id") if artifact_field == "parent_release_id" else manifest.get(artifact_field)
        if str(artifact.get(artifact_field) or "") != str(expected or ""):
            errors.append(f"creator public artifact {artifact_field} mismatch")
    if manifest.get("creator_public_status") == "ready" and artifact.get("status") != "ready":
        errors.append("manifest declares creator public artifact ready but artifact is not ready")
    declared_id = manifest.get("creator_snapshot_id")
    if declared_id and str(artifact.get("snapshot_id") or "") != str(declared_id):
        errors.append("creator public artifact snapshot_id does not match manifest")
    return sorted(set(errors))


def _validate_news_artifact(artifact: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    """Validate the optional News artifact as part of the same release.

    News is fail-soft at collection time, but once a publisher advertises
    ``news.json`` its lineage is no longer optional: the browser and notifier
    must never combine headlines from another market snapshot.
    """
    errors = validate_news_release(artifact)
    expected_market = str(manifest.get("market_snapshot_id") or "")
    if expected_market and str(artifact.get("market_snapshot_id") or "") != expected_market:
        errors.append("news artifact market_snapshot_id does not match manifest")
    declared_news = str(manifest.get("news_snapshot_id") or "")
    if declared_news and str(artifact.get("snapshot_id") or "") != declared_news:
        errors.append("news artifact snapshot_id does not match manifest")
    if manifest.get("news_status") == "ready" and artifact.get("status") not in {"ready", "no_event"}:
        errors.append("manifest declares news ready but artifact is not publishable")
    return sorted(set(errors))


def _load_release_artifacts(manifest: dict[str, Any], *, site_root: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Load and validate the contract artifacts referenced by a manifest."""
    paths = manifest.get("artifact_paths")
    if not isinstance(paths, dict):
        return {}, ["manifest artifact paths are missing"]
    loaded: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for name in ("market.json", "research-report.json", "event-ledger.json", "source-health.json", "creator-release.json", "creator-insights.json", "news.json"):
        if name in {"source-health.json", "creator-release.json", "creator-insights.json", "news.json"} and name not in paths:
            continue
        raw_path = paths.get(name)
        if not isinstance(raw_path, str):
            errors.append(f"manifest path missing: {name}")
            continue
        path = site_root / raw_path
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"artifact unreadable {name}: {type(exc).__name__}")
            continue
        if not isinstance(value, dict):
            errors.append(f"artifact must be an object: {name}")
            continue
        loaded[name] = value
    creator = loaded.get("creator-release.json")
    if creator is not None:
        errors.extend(_validate_creator_artifact(creator, manifest))
    creator_public = loaded.get("creator-insights.json")
    if creator_public is not None and manifest.get("creator_public_status") == "ready":
        errors.extend(_validate_creator_public_artifact(creator_public, manifest))
    news = loaded.get("news.json")
    if news is not None:
        errors.extend(_validate_news_artifact(news, manifest))
    return loaded, errors


def _fetch_public_release_artifacts(
    manifest: dict[str, Any], *, public_url: str, timeout: float,
    require_production_research: bool = False,
    max_research_age_hours: float = 24.0,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Fetch and verify the immutable bundle advertised by a Pages manifest.

    Verifying only the manifest URL is insufficient: a CDN or deployment can
    serve a ready manifest while one of its referenced artifacts is stale,
    missing, or from a different release.  The remote bytes are hashed before
    parsing so a semantically valid but different JSON file cannot pass.
    """
    paths = manifest.get("artifact_paths")
    hashes = manifest.get("artifact_hashes")
    if not isinstance(paths, dict) or not isinstance(hashes, dict):
        return {}, ["public manifest artifact paths/hashes are missing"]
    base = urlsplit(public_url)
    if base.scheme != "https" or not base.hostname:
        return {}, ["public release URL must use HTTPS"]
    headers = {
        "Accept": "application/json",
        "Cache-Control": "no-cache, no-store",
        "Pragma": "no-cache",
        "User-Agent": "PRStK-release-gate",
    }
    loaded: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for name in ("market.json", "research-report.json", "event-ledger.json", "source-health.json", "creator-release.json", "creator-insights.json", "news.json"):
        if name in {"source-health.json", "creator-release.json", "creator-insights.json", "news.json"} and name not in paths:
            continue
        raw_path = paths.get(name)
        expected_hash = hashes.get(name)
        if not isinstance(raw_path, str) or not raw_path.strip():
            errors.append(f"public manifest path missing: {name}")
            continue
        if not isinstance(expected_hash, str) or len(expected_hash) != 64:
            errors.append(f"public manifest hash missing: {name}")
            continue
        url = urljoin(public_url.rstrip("/") + "/", raw_path.lstrip("/"))
        target = urlsplit(url)
        if target.scheme != base.scheme or target.hostname != base.hostname:
            errors.append(f"public artifact URL leaves release host: {name}")
            continue
        try:
            response = requests.get(url, timeout=timeout, headers=headers)
            response.raise_for_status()
            body = bytes(response.content)
        except (requests.RequestException, TypeError, ValueError) as exc:
            errors.append(f"public artifact unavailable {name}: {type(exc).__name__}")
            continue
        actual_hash = hashlib.sha256(body).hexdigest()
        if actual_hash != expected_hash:
            errors.append(f"public artifact hash mismatch: {name}")
            continue
        try:
            value = json.loads(body.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            errors.append(f"public artifact invalid JSON: {name}")
            continue
        if not isinstance(value, dict):
            errors.append(f"public artifact must be an object: {name}")
            continue
        loaded[name] = value
    creator = loaded.get("creator-release.json")
    if creator is not None:
        errors.extend(_validate_creator_artifact(creator, manifest))
    creator_public = loaded.get("creator-insights.json")
    if creator_public is not None and manifest.get("creator_public_status") == "ready":
        errors.extend(_validate_creator_public_artifact(creator_public, manifest))
    news = loaded.get("news.json")
    if news is not None:
        errors.extend(_validate_news_artifact(news, manifest))
    if errors:
        return loaded, errors
    if "source-health.json" in paths:
        health = loaded.get("source-health.json")
        if health is None:
            return loaded, ["public source-health artifact is missing"]
        source_health = health.get("source_health")
        if not isinstance(source_health, dict):
            return loaded, ["public source-health artifact envelope is invalid"]
        errors.extend(validate_source_health_artifact(health))
    errors.extend(
        validate_release(
            market=loaded["market.json"],
            research=loaded["research-report.json"],
            events=loaded["event-ledger.json"],
            manifest=manifest,
        )
    )
    errors.extend(_external_observation_lineage_errors(loaded["market.json"], manifest))
    if require_production_research:
        acceptance = validate_production_bundle(
            manifest=manifest,
            market=loaded["market.json"],
            research=loaded["research-report.json"],
            events=loaded["event-ledger.json"],
            require_production_research=True,
        )
        errors.extend(acceptance.errors)
        errors.extend(
            _strict_research_freshness_errors(
                manifest,
                loaded["research-report.json"],
                max_research_age_hours=max_research_age_hours,
                public=True,
            )
        )
    return loaded, errors


def _strict_research_freshness_errors(
    manifest: dict[str, Any],
    research: dict[str, Any],
    *,
    max_research_age_hours: float,
    public: bool = False,
) -> list[str]:
    """Reject a labelled-fresh report whose timestamp is actually too old."""
    prefix = "public production release" if public else "production release"
    errors: list[str] = []
    if manifest.get("research_freshness") != "fresh":
        errors.append(f"{prefix} research_freshness is not fresh")
    value = research.get("generated_at")
    try:
        generated = datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
        if generated is not None:
            generated = generated.replace(tzinfo=UTC) if generated.tzinfo is None else generated.astimezone(UTC)
    except (TypeError, ValueError):
        generated = None
    if generated is None:
        return errors
    now = datetime.now(UTC)
    if generated > now + timedelta(minutes=5):
        errors.append(f"{prefix} research generated_at is in the future")
    else:
        age_hours = max(0.0, (now - generated).total_seconds() / 3600.0)
        if age_hours > max(0.0, float(max_research_age_hours)):
            errors.append(f"{prefix} research is older than {max_research_age_hours:g} hours")
    return errors


def verify_release_for_delivery(
    *,
    manifest_path: Path | str = Path("site/data/release-manifest.json"),
    expected_snapshot_id: str | None = None,
    public_url: str | None = None,
    timeout: float = 15.0,
    public_attempts: int = 12,
    public_delay: float = 5.0,
    require_production_research: bool = False,
    max_research_age_hours: float = 24.0,
) -> ReleaseGateResult:
    """Verify readiness, local hashes and optionally the deployed Pages copy."""
    path = Path(manifest_path)
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return ReleaseGateResult(False, errors=(f"manifest unreadable: {type(exc).__name__}",))
    if not isinstance(manifest, dict):
        return ReleaseGateResult(False, errors=("manifest must be a JSON object",))

    errors: list[str] = []
    if manifest.get("status") != "ready":
        errors.append("manifest status is not ready")
    release_id = str(manifest.get("release_id") or "")
    snapshot_id = str(manifest.get("market_snapshot_id") or "")
    if not release_id:
        errors.append("release_id is missing")
    if not snapshot_id:
        errors.append("market_snapshot_id is missing")
    if expected_snapshot_id and snapshot_id != str(expected_snapshot_id):
        errors.append("manifest market snapshot does not match prepared snapshot")

    # Manifest artifact paths are relative to the Pages root (site/).
    site_root = path.parent.parent if path.parent.name == "data" else path.parent
    errors.extend(verify_release_files(manifest, root=site_root))
    # A Pages release is not deliverable with a mixed-generation static shell.
    # Keep legacy rollback fixtures readable when no asset manifest exists,
    # but fail closed whenever a publisher has emitted one.
    asset_manifest = site_root / "asset-manifest.json"
    if asset_manifest.is_file():
        errors.extend(validate_assets(site_root))
    artifacts, artifact_errors = _load_release_artifacts(manifest, site_root=site_root)
    errors.extend(artifact_errors)
    if not artifact_errors and not errors:
        errors.extend(
            validate_release(
                market=artifacts["market.json"],
                research=artifacts["research-report.json"],
                events=artifacts["event-ledger.json"],
                manifest=manifest,
            )
        )
        errors.extend(_external_observation_lineage_errors(artifacts["market.json"], manifest))
        if "source-health.json" in artifacts:
            health = artifacts["source-health.json"].get("source_health")
            if not isinstance(health, dict):
                errors.append("source-health artifact envelope is invalid")
            else:
                errors.extend(validate_source_health_artifact(artifacts["source-health.json"]))
        acceptance = validate_production_bundle(
            manifest=manifest,
            market=artifacts["market.json"],
            research=artifacts["research-report.json"],
            events=artifacts["event-ledger.json"],
            require_production_research=require_production_research,
        )
        errors.extend(acceptance.errors)
        if require_production_research:
            errors.extend(
                _strict_research_freshness_errors(
                    manifest,
                    artifacts["research-report.json"],
                    max_research_age_hours=max_research_age_hours,
                )
            )

    if public_url:
        remote_url = public_url.rstrip("/") + "/data/release-manifest.json"
        public_error = "public manifest unavailable: UnknownError"
        attempts = max(1, int(public_attempts))
        for attempt in range(attempts):
            try:
                request_url = _cache_busted_url(
                    remote_url,
                    release_id=release_id,
                    attempt=attempt + 1,
                )
                response = requests.get(
                    request_url,
                    timeout=timeout,
                    headers={
                        "Accept": "application/json",
                        "Cache-Control": "no-cache, no-store",
                        "Pragma": "no-cache",
                        "User-Agent": "PRStK-release-gate",
                    },
                )
                response.raise_for_status()
                remote = response.json()
                if not isinstance(remote, dict):
                    public_error = "public manifest is not an object"
                elif remote.get("status") != "ready":
                    public_error = "public manifest status is not ready"
                elif str(remote.get("release_id") or "") != release_id:
                    public_error = "public manifest release_id does not match local release"
                elif expected_snapshot_id and str(remote.get("market_snapshot_id") or "") != str(expected_snapshot_id):
                    public_error = "public manifest market snapshot does not match prepared snapshot"
                else:
                    _, bundle_errors = _fetch_public_release_artifacts(
                        remote,
                        public_url=public_url,
                        timeout=timeout,
                        require_production_research=require_production_research,
                        max_research_age_hours=max_research_age_hours,
                    )
                    if bundle_errors:
                        public_error = "; ".join(sorted(set(bundle_errors)))
                    else:
                        public_error = ""
                        break
            except (requests.RequestException, ValueError) as exc:
                public_error = f"public manifest unavailable: {type(exc).__name__}"
            if attempt < attempts - 1 and public_delay > 0:
                time.sleep(public_delay)
        if public_error:
            errors.append(public_error)

    return ReleaseGateResult(
        not errors,
        release_id=release_id,
        snapshot_id=snapshot_id,
        errors=tuple(sorted(set(errors))),
        manifest=manifest,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a public release before delivery")
    parser.add_argument("--manifest", type=Path, default=Path("site/data/release-manifest.json"))
    parser.add_argument("--expected-snapshot-id", default=None)
    parser.add_argument("--public-url", default=None)
    parser.add_argument("--public-attempts", type=int, default=12)
    parser.add_argument("--public-delay", type=float, default=5.0)
    parser.add_argument(
        "--require-production-research",
        action="store_true",
        help="require a fresh production/full research artifact for delivery",
    )
    parser.add_argument("--max-research-age-hours", type=float, default=24.0)
    args = parser.parse_args()
    result = verify_release_for_delivery(
        manifest_path=args.manifest,
        expected_snapshot_id=args.expected_snapshot_id,
        public_url=args.public_url,
        public_attempts=args.public_attempts,
        public_delay=args.public_delay,
        require_production_research=args.require_production_research,
        max_research_age_hours=args.max_research_age_hours,
    )
    values = {
        "allowed": result.allowed,
        "release_id": result.release_id,
        "snapshot_id": result.snapshot_id,
        "errors": ";".join(result.errors),
    }
    lines = [f"{key}={str(value).lower() if isinstance(value, bool) else value}" for key, value in values.items()]
    destination = os.getenv("GITHUB_OUTPUT")
    if destination:
        with Path(destination).open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    else:
        print("\n".join(lines))
    return 0 if result.allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())
