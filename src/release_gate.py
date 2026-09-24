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
from src.release_manifest import PUBLISHABLE_RELEASE_STATUSES, verify_release_files


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


def _http_status(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def _is_retryable_http_error(exc: BaseException) -> bool:
    if not isinstance(exc, requests.RequestException):
        return False
    status = _http_status(exc)
    # A missing response usually means DNS, TLS, connection, or read timeout.
    # Those can recover during Pages propagation; permanent 4xx responses cannot.
    return status is None or status in {404, 408, 425, 429} or status >= 500


def _utc_timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _is_newer_manifest(remote: dict[str, Any], local: dict[str, Any]) -> bool:
    remote_created = _utc_timestamp(remote.get("created_at"))
    local_created = _utc_timestamp(local.get("created_at"))
    return remote_created is not None and local_created is not None and remote_created > local_created


def _request_timeout(timeout: float, deadline: float | None) -> float:
    if deadline is None:
        return timeout
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise requests.Timeout("release gate total deadline reached")
    return min(timeout, remaining)


@dataclass(frozen=True)
class ReleaseGateResult:
    allowed: bool
    release_id: str = ""
    snapshot_id: str = ""
    errors: tuple[str, ...] = field(default_factory=tuple)
    manifest: dict[str, Any] = field(default_factory=dict)
    gate_status: str = "blocked"
    error_category: str = "contract_mismatch"
    expected_release_id: str = ""
    actual_release_id: str = ""
    expected_snapshot_id: str = ""
    actual_snapshot_id: str = ""
    deployment_id: str = ""
    manifest_url: str = ""
    http_status: int | None = None
    attempts: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    elapsed_seconds: float = 0.0
    retryable: bool = False
    superseded: bool = False


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


def _validate_bootstrap_artifact(artifact: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    """Validate the small first-paint projection before Telegram delivery."""
    errors: list[str] = []
    if str(artifact.get("schema_version") or "") != "1.0":
        errors.append("bootstrap schema version is invalid")
    if str(artifact.get("release_id") or "") != str(manifest.get("release_id") or ""):
        errors.append("bootstrap release_id does not match manifest")
    if str(artifact.get("snapshot_id") or "") != str(manifest.get("market_snapshot_id") or ""):
        errors.append("bootstrap snapshot_id does not match manifest")
    contract = manifest.get("bootstrap_contract")
    if isinstance(contract, dict):
        max_bytes = int(contract.get("max_bytes") or 0)
        if max_bytes <= 0:
            errors.append("bootstrap contract max_bytes is invalid")
    if not isinstance(artifact.get("indices"), list) or not isinstance(artifact.get("events"), dict):
        errors.append("bootstrap first-paint fields are missing")
    return sorted(set(errors))


def _validate_public_alert_target(
    loaded: dict[str, dict[str, Any]], manifest: dict[str, Any], *,
    public_url: str, notification_id: str, snapshot_id: str = "", observation_id: str = "",
    timeout: float = 15.0, deadline: float | None = None,
) -> list[str]:
    """Verify the exact immutable alert that a Telegram Deep Link will open."""
    requested = str(notification_id or "").strip()
    if not requested:
        return []
    index = loaded.get("alert-index.json")
    rows = index.get("alerts") if isinstance(index, dict) else None
    if not isinstance(rows, list):
        return ["click target alert index is unavailable"]
    release_id = str(manifest.get("release_id") or "")
    row = next(
        (item for item in rows if isinstance(item, dict)
         and str(item.get("notification_id") or "") == requested
         and str(item.get("release_id") or "") == release_id),
        None,
    )
    if not isinstance(row, dict):
        return ["click target alert is not indexed in the published release"]
    path = str(row.get("path") or "").strip()
    digest = str(row.get("sha256") or "").strip()
    if not (path.startswith("alerts/") or path.startswith("data/alerts/")) or ".." in path.split("/") or len(digest) != 64:
        return ["click target alert index row is invalid"]
    # Alert-index paths are relative to the immutable data root.  The Pages
    # site itself is rooted at ``site/``, so ``alerts/x.json`` is published at
    # ``data/alerts/x.json``.  Keep the index format backward compatible while
    # making the public URL resolution explicit and shared with the publisher.
    public_path = path if path.startswith("data/") else f"data/{path}"
    url = urljoin(public_url.rstrip("/") + "/", public_path)
    errors: list[str] = []
    try:
        response = requests.get(
            url,
            timeout=_request_timeout(timeout, deadline),
            headers={"Accept": "application/json", "Cache-Control": "no-cache", "User-Agent": "PRStK-release-gate"},
        )
        response.raise_for_status()
        body = bytes(response.content)
    except (requests.RequestException, TypeError, ValueError) as exc:
        if _is_retryable_http_error(exc):
            status = _http_status(exc)
            suffix = f" HTTP {status}" if status is not None else ""
            return [f"transient click target alert unavailable:{type(exc).__name__}{suffix}"]
        status = _http_status(exc)
        suffix = f" HTTP {status}" if status is not None else ""
        return [f"click target alert request rejected:{type(exc).__name__}{suffix}"]
    if hashlib.sha256(body).hexdigest() != digest:
        return ["click target alert hash mismatch"]
    try:
        alert = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return ["click target alert is invalid JSON"]
    if not isinstance(alert, dict):
        return ["click target alert is not an object"]
    if str(alert.get("notification_id") or "") != requested or str(alert.get("release_id") or "") != release_id:
        errors.append("click target alert identity mismatch")
    if snapshot_id and str(alert.get("snapshot_id") or "") != str(snapshot_id):
        errors.append("click target alert snapshot mismatch")
    if observation_id and str(alert.get("observation_id") or "") != str(observation_id):
        errors.append("click target alert observation mismatch")
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
    for name in ("market.json", "research-report.json", "event-ledger.json", "source-health.json", "creator-release.json", "creator-insights.json", "news.json", "bootstrap.json", "alert-index.json"):
        if name in {"source-health.json", "creator-release.json", "creator-insights.json", "news.json", "bootstrap.json", "alert-index.json"} and name not in paths:
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
    bootstrap = loaded.get("bootstrap.json")
    if bootstrap is not None:
        errors.extend(_validate_bootstrap_artifact(bootstrap, manifest))
    return loaded, errors


def _fetch_public_release_artifacts(
    manifest: dict[str, Any], *, public_url: str, timeout: float,
    require_production_research: bool = False,
    max_research_age_hours: float = 24.0,
    deadline: float | None = None,
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
    for name in ("market.json", "research-report.json", "event-ledger.json", "source-health.json", "creator-release.json", "creator-insights.json", "news.json", "bootstrap.json", "alert-index.json"):
        if name in {"source-health.json", "creator-release.json", "creator-insights.json", "news.json", "bootstrap.json", "alert-index.json"} and name not in paths:
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
            response = requests.get(
                url,
                timeout=_request_timeout(timeout, deadline),
                headers=headers,
            )
            response.raise_for_status()
            body = bytes(response.content)
        except (requests.RequestException, TypeError, ValueError) as exc:
            status = _http_status(exc)
            suffix = f" HTTP {status}" if status is not None else ""
            if _is_retryable_http_error(exc):
                errors.append(f"transient public artifact unavailable {name}: {type(exc).__name__}{suffix}")
            else:
                errors.append(f"public artifact request rejected {name}: {type(exc).__name__}{suffix}")
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
    bootstrap = loaded.get("bootstrap.json")
    if bootstrap is not None:
        errors.extend(_validate_bootstrap_artifact(bootstrap, manifest))
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


def _classify_gate_errors(errors: list[str]) -> str:
    joined = ";".join(errors).casefold()
    if "expected release_id" in joined:
        return "local_release_identity_mismatch"
    if "transient public" in joined or "transient click target" in joined:
        return "pages_unavailable"
    if "public manifest release_id" in joined:
        return "public_manifest_stale"
    if "public artifact hash mismatch" in joined or "identity mismatch" in joined:
        return "deployed_artifact_mismatch"
    if "public" in joined or "click target" in joined:
        return "public_content_mismatch"
    if "hash mismatch" in joined or "artifact" in joined:
        return "local_artifact_mismatch"
    return "contract_mismatch"


def verify_release_for_delivery(
    *,
    manifest_path: Path | str = Path("site/data/release-manifest.json"),
    expected_snapshot_id: str | None = None,
    expected_release_id: str | None = None,
    public_url: str | None = None,
    timeout: float = 15.0,
    public_attempts: int = 0,
    public_delay: float = 2.0,
    public_max_delay: float = 20.0,
    public_timeout_seconds: float = 180.0,
    require_production_research: bool = False,
    max_research_age_hours: float = 24.0,
    expected_notification_id: str | None = None,
    expected_alert_snapshot_id: str | None = None,
    expected_alert_observation_id: str | None = None,
    deployment_id: str | None = None,
) -> ReleaseGateResult:
    """Verify one immutable release locally and on Pages before delivery.

    Public verification retries only stale propagation reads and transient
    transport failures.  Permanent identity, schema, hash, and contract
    mismatches fail immediately.  The wall-clock deadline also bounds each
    HTTP request, so the complete gate cannot spend 180 seconds per artifact.
    """
    started = time.monotonic()
    path = Path(manifest_path)
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return ReleaseGateResult(
            False,
            errors=(f"manifest unreadable: {type(exc).__name__}",),
            gate_status="blocked",
            error_category="local_artifact_mismatch",
            deployment_id=str(deployment_id or ""),
            elapsed_seconds=max(0.0, time.monotonic() - started),
        )
    if not isinstance(manifest, dict):
        return ReleaseGateResult(
            False,
            errors=("manifest must be a JSON object",),
            gate_status="blocked",
            error_category="contract_mismatch",
            deployment_id=str(deployment_id or ""),
            elapsed_seconds=max(0.0, time.monotonic() - started),
        )

    errors: list[str] = []
    if manifest.get("status") not in PUBLISHABLE_RELEASE_STATUSES:
        errors.append("manifest status is not ready")
    release_id = str(manifest.get("release_id") or "")
    snapshot_id = str(manifest.get("market_snapshot_id") or "")
    expected_release = str(expected_release_id or release_id)
    expected_snapshot = str(expected_snapshot_id or snapshot_id)
    if not release_id:
        errors.append("release_id is missing")
    elif expected_release_id and release_id != str(expected_release_id):
        errors.append("local release_id does not match expected release_id")
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

    public_attempt_records: list[dict[str, Any]] = []
    public_error = ""
    error_category = _classify_gate_errors(errors) if errors else "none"
    final_retryable = False
    actual_release_id = ""
    actual_snapshot_id = ""
    http_status: int | None = None
    superseded = False
    manifest_url = public_url.rstrip("/") + "/data/release-manifest.json" if public_url else ""

    # Do not spend network time when the local release is already invalid.
    if public_url and not errors:
        deadline = started + max(0.0, float(public_timeout_seconds))
        max_attempts = max(1, int(public_attempts)) if int(public_attempts) > 0 else None
        attempt_number = 0
        while max_attempts is None or attempt_number < max_attempts:
            if attempt_number and time.monotonic() >= deadline:
                break
            attempt_number += 1
            # Per-attempt diagnostics must never inherit a previously served
            # manifest identity after a later timeout or malformed response.
            actual_release_id = ""
            actual_snapshot_id = ""
            request_url = _cache_busted_url(
                manifest_url,
                release_id=expected_release,
                attempt=attempt_number,
            )
            attempt_error = ""
            attempt_category = "none"
            attempt_retryable = False
            attempt_http_status: int | None = None
            attempt_superseded = False
            remote: dict[str, Any] | None = None
            try:
                response = requests.get(
                    request_url,
                    timeout=_request_timeout(timeout, deadline),
                    headers={
                        "Accept": "application/json",
                        "Cache-Control": "no-cache, no-store",
                        "Pragma": "no-cache",
                        "User-Agent": "PRStK-release-gate",
                    },
                )
                attempt_http_status = getattr(response, "status_code", None)
                response.raise_for_status()
                try:
                    candidate = response.json()
                except (ValueError, UnicodeError):
                    candidate = None
                    attempt_error = "public manifest is invalid JSON"
                    attempt_category = "public_content_mismatch"
                if not attempt_error and not isinstance(candidate, dict):
                    attempt_error = "public manifest is not an object"
                    attempt_category = "public_content_mismatch"
                elif not attempt_error:
                    remote = candidate
                    actual_release_id = str(remote.get("release_id") or "")
                    actual_snapshot_id = str(remote.get("market_snapshot_id") or "")
                    if remote.get("status") not in PUBLISHABLE_RELEASE_STATUSES:
                        attempt_error = "public manifest status is not ready"
                        attempt_category = "public_content_mismatch"
                    elif actual_release_id != expected_release:
                        if _is_newer_manifest(remote, manifest):
                            _, newer_errors = _fetch_public_release_artifacts(
                                remote,
                                public_url=public_url,
                                timeout=timeout,
                                require_production_research=require_production_research,
                                max_research_age_hours=max_research_age_hours,
                                deadline=deadline,
                            )
                            if newer_errors:
                                attempt_error = "; ".join(sorted(set(newer_errors)))
                                attempt_retryable = any(
                                    item.startswith("transient ") for item in newer_errors
                                )
                                attempt_category = (
                                    "pages_unavailable" if attempt_retryable
                                    else "public_content_mismatch"
                                )
                            else:
                                attempt_error = "public release was superseded by a newer valid release"
                                attempt_category = "parallel_publish_superseded"
                                attempt_superseded = True
                        elif _is_newer_manifest(manifest, remote):
                            attempt_error = "public manifest release_id does not match local release"
                            attempt_category = "public_manifest_stale"
                            attempt_retryable = True
                        else:
                            attempt_error = "public manifest release_id does not match expected release"
                            attempt_category = "deployed_artifact_mismatch"
                    elif actual_snapshot_id != expected_snapshot:
                        attempt_error = "public manifest market snapshot does not match prepared snapshot"
                        attempt_category = "public_content_mismatch"
                    else:
                        loaded, bundle_errors = _fetch_public_release_artifacts(
                            remote,
                            public_url=public_url,
                            timeout=timeout,
                            require_production_research=require_production_research,
                            max_research_age_hours=max_research_age_hours,
                            deadline=deadline,
                        )
                        if bundle_errors:
                            attempt_error = "; ".join(sorted(set(bundle_errors)))
                            attempt_retryable = any(
                                item.startswith("transient ") for item in bundle_errors
                            )
                            attempt_category = (
                                "pages_unavailable" if attempt_retryable
                                else "deployed_artifact_mismatch"
                            )
                        else:
                            target_errors = _validate_public_alert_target(
                                loaded,
                                remote,
                                public_url=public_url,
                                notification_id=str(expected_notification_id or ""),
                                snapshot_id=str(expected_alert_snapshot_id or ""),
                                observation_id=str(expected_alert_observation_id or ""),
                                timeout=timeout,
                                deadline=deadline,
                            )
                            if target_errors:
                                attempt_error = "; ".join(sorted(set(target_errors)))
                                attempt_retryable = any(
                                    item.startswith("transient ") for item in target_errors
                                )
                                attempt_category = (
                                    "pages_unavailable" if attempt_retryable
                                    else "deployed_artifact_mismatch"
                                )
            except (requests.RequestException, TypeError) as exc:
                attempt_http_status = _http_status(exc)
                suffix = f" HTTP {attempt_http_status}" if attempt_http_status is not None else ""
                if _is_retryable_http_error(exc):
                    attempt_error = f"transient public manifest unavailable: {type(exc).__name__}{suffix}"
                    attempt_category = "pages_unavailable"
                    attempt_retryable = True
                else:
                    attempt_error = f"public manifest request rejected: {type(exc).__name__}{suffix}"
                    attempt_category = "public_content_mismatch"

            http_status = attempt_http_status
            public_error = attempt_error
            error_category = attempt_category
            final_retryable = attempt_retryable
            public_attempt_records.append({
                "attempt": attempt_number,
                "at": datetime.now(UTC).isoformat(),
                "manifest_url": manifest_url,
                "http_status": attempt_http_status,
                "expected_release_id": expected_release,
                "actual_release_id": actual_release_id,
                "expected_snapshot_id": expected_snapshot,
                "actual_snapshot_id": actual_snapshot_id,
                "error_category": attempt_category,
                "error": attempt_error,
                "retryable": attempt_retryable,
                "superseded": attempt_superseded,
                "deployment_id": str(deployment_id or ""),
            })
            if not attempt_error:
                break
            if attempt_superseded:
                superseded = True
                break
            if not attempt_retryable:
                break
            if max_attempts is not None and attempt_number >= max_attempts:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            delay = min(
                max(0.0, float(public_max_delay)),
                max(0.0, float(public_delay)) * (2 ** min(attempt_number - 1, 8)),
                remaining,
            )
            if delay > 0:
                time.sleep(delay)
        if public_error:
            errors.append(public_error)
        elif public_attempt_records and public_attempt_records[-1].get("superseded"):
            errors.append("public release was superseded by a newer valid release")

    allowed = not errors
    gate_status = "allowed" if allowed else "superseded" if superseded else "blocked"
    if errors and error_category == "none":
        error_category = _classify_gate_errors(errors)
    return ReleaseGateResult(
        allowed=allowed,
        release_id=release_id,
        snapshot_id=snapshot_id,
        errors=tuple(sorted(set(errors))),
        manifest=manifest,
        gate_status=gate_status,
        error_category=error_category,
        expected_release_id=expected_release,
        actual_release_id=actual_release_id,
        expected_snapshot_id=expected_snapshot,
        actual_snapshot_id=actual_snapshot_id,
        deployment_id=str(deployment_id or ""),
        manifest_url=manifest_url,
        http_status=http_status,
        attempts=tuple(public_attempt_records),
        elapsed_seconds=max(0.0, time.monotonic() - started),
        retryable=final_retryable,
        superseded=superseded,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a public release before delivery")
    parser.add_argument("--manifest", type=Path, default=Path("site/data/release-manifest.json"))
    parser.add_argument("--expected-snapshot-id", default=None)
    parser.add_argument("--expected-release-id", default=None)
    parser.add_argument("--public-url", default=None)
    parser.add_argument("--public-attempts", type=int, default=0, help="optional attempt cap; deadline is authoritative")
    parser.add_argument("--public-delay", type=float, default=2.0, help="initial propagation retry delay")
    parser.add_argument("--public-max-delay", type=float, default=20.0)
    parser.add_argument("--public-timeout-seconds", type=float, default=180.0)
    parser.add_argument("--deployment-id", default=None)
    parser.add_argument(
        "--require-production-research",
        action="store_true",
        help="require a fresh production/full research artifact for delivery",
    )
    parser.add_argument("--max-research-age-hours", type=float, default=24.0)
    parser.add_argument("--expected-notification-id", default=None)
    parser.add_argument("--expected-alert-snapshot-id", default=None)
    parser.add_argument("--expected-alert-observation-id", default=None)
    args = parser.parse_args()
    result = verify_release_for_delivery(
        manifest_path=args.manifest,
        expected_snapshot_id=args.expected_snapshot_id,
        expected_release_id=args.expected_release_id,
        public_url=args.public_url,
        public_attempts=args.public_attempts,
        public_delay=args.public_delay,
        public_max_delay=args.public_max_delay,
        public_timeout_seconds=args.public_timeout_seconds,
        deployment_id=args.deployment_id,
        require_production_research=args.require_production_research,
        max_research_age_hours=args.max_research_age_hours,
        expected_notification_id=args.expected_notification_id,
        expected_alert_snapshot_id=args.expected_alert_snapshot_id,
        expected_alert_observation_id=args.expected_alert_observation_id,
    )
    values = {
        "allowed": result.allowed,
        "gate_status": result.gate_status,
        "error_category": result.error_category,
        "release_id": result.release_id,
        "snapshot_id": result.snapshot_id,
        "expected_release_id": result.expected_release_id,
        "actual_release_id": result.actual_release_id,
        "expected_snapshot_id": result.expected_snapshot_id,
        "actual_snapshot_id": result.actual_snapshot_id,
        "deployment_id": result.deployment_id,
        "manifest_url": result.manifest_url,
        "http_status": result.http_status if result.http_status is not None else "",
        "attempts": json.dumps(result.attempts, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        "elapsed_seconds": f"{result.elapsed_seconds:.3f}",
        "retryable": result.retryable,
        "superseded": result.superseded,
        "errors": ";".join(result.errors),
    }
    lines = [
        f"{key}={str(value).lower() if isinstance(value, bool) else str(value).replace(chr(10), ' ').replace(chr(13), ' ')}"
        for key, value in values.items()
    ]
    destination = os.getenv("GITHUB_OUTPUT")
    if destination:
        with Path(destination).open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    else:
        print("\n".join(lines))
    # A valid newer public release is an expected supersession race.  It must
    # never enable a sender, but it is not a failed workflow requiring repair.
    return 0 if result.allowed or result.superseded else 1


if __name__ == "__main__":
    raise SystemExit(main())
