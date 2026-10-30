"""Verify the GitHub Pages build-version status created by this run."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import tarfile
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from src.scheduled_slot_audit import _open_artifact_url


class PagesDeploymentError(RuntimeError):
    """Raised when the completed Pages deployment cannot be identified safely."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        error_code: str = "pages_deployment_error",
        request_outcome: str = "not_started",
        deployment_id: str = "",
        status_url: str = "",
        page_url: str = "",
        artifact_id: str = "",
        artifact_digest: str = "",
        manifest_sha256: str = "",
        build_version: str = "",
        release_id: str = "",
        snapshot_id: str = "",
        phase: str = "",
        recoverable: bool = False,
        status_url_shape: str = "",
        artifact_manifest_sha256: str = "",
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.error_code = error_code
        self.request_outcome = request_outcome
        self.deployment_id = deployment_id
        self.status_url = status_url
        self.page_url = page_url
        self.artifact_id = artifact_id
        self.artifact_digest = artifact_digest
        self.manifest_sha256 = manifest_sha256
        self.build_version = build_version
        self.release_id = release_id
        self.snapshot_id = snapshot_id
        self.phase = phase
        self.recoverable = recoverable
        self.status_url_shape = status_url_shape
        self.artifact_manifest_sha256 = artifact_manifest_sha256


def _safe_error_detail(raw: bytes, secrets: tuple[str, ...] = ()) -> str:
    """Keep short, non-secret GitHub API error details for workflow diagnostics."""
    try:
        payload = json.loads(raw[:8192].decode("utf-8", errors="replace"))
    except (ValueError, UnicodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    parts: list[str] = []
    message = payload.get("message")
    if isinstance(message, str):
        parts.append(message)
    errors = payload.get("errors")
    if isinstance(errors, list):
        for item in errors[:3]:
            if not isinstance(item, dict):
                continue
            allowed = [item.get(key) for key in ("resource", "field", "code")]
            fields = [str(value) for value in allowed if isinstance(value, str) and value]
            if fields:
                parts.append("/".join(fields))
    detail = "; ".join(parts)
    for secret in secrets:
        if secret and len(secret) >= 6:
            detail = detail.replace(secret, "[redacted]")
    detail = re.sub(r"(?i)bearer\s+\S+", "[redacted]", detail)
    detail = re.sub(r"\b[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b", "[redacted]", detail)
    detail = re.sub(r"https?://\S+", "[url]", detail)
    detail = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email]", detail)
    detail = re.sub(r"\s+", " ", detail).strip()
    return detail[:240]


def _safe_status_url_shape(
    value: str, *, api_url: str, repository: str, deployment_id: str,
) -> str:
    """Describe a returned status URL without logging its value."""
    if not str(value or "").strip():
        return "missing"
    try:
        parsed = urlparse(str(value).strip())
        api = urlparse(api_url)
        route = _status_url_path_route(
            path=parsed.path,
            repository=repository,
            deployment_id=deployment_id,
        ) or "other"
        same_api_host = parsed.netloc.casefold() == api.netloc.casefold()
        has_userinfo = parsed.username is not None or parsed.password is not None
    except ValueError:
        return "scheme=invalid;host=other;route=other;userinfo=unknown;query=no;fragment=no"
    return ";".join((
        f"scheme={parsed.scheme.casefold() or 'missing'}",
        f"host={'api' if same_api_host else 'other'}",
        f"route={route}",
        f"userinfo={'yes' if has_userinfo else 'no'}",
        f"query={'yes' if parsed.query else 'no'}",
        f"fragment={'yes' if parsed.fragment else 'no'}",
    ))


def _status_url_path_route(*, path: str, repository: str, deployment_id: str) -> str | None:
    return {
        f"/repos/{repository}/pages/deployments/{deployment_id}": "deployment",
        f"/repos/{repository}/pages/deployments/{deployment_id}/status": "deployment_status",
        f"/repos/{repository}/pages/deployment/status/{deployment_id}": "legacy_deployment_status",
    }.get(path)


def _status_url_route(
    value: str, *, api_url: str, repository: str, deployment_id: str,
) -> str | None:
    """Return the name of a known GitHub Pages status URL shape, if trusted."""
    try:
        parsed_status = urlparse(str(value or "").strip())
        parsed_api = urlparse(str(api_url or "").strip())
        # Accessing parsed credentials validates malformed authority syntax.
        has_userinfo = parsed_status.username is not None or parsed_status.password is not None
    except ValueError:
        return None
    if (
        parsed_api.scheme.casefold() != "https"
        or not parsed_api.netloc
        or parsed_status.scheme.casefold() != "https"
        or parsed_status.netloc.casefold() != parsed_api.netloc.casefold()
        or has_userinfo
        or parsed_status.query
        or parsed_status.fragment
    ):
        return None
    return _status_url_path_route(
        path=parsed_status.path,
        repository=repository,
        deployment_id=deployment_id,
    )


@dataclass(frozen=True)
class PagesDeployment:
    deployment_id: str
    status: str
    build_version: str
    status_url: str = ""
    page_url: str = ""
    artifact_id: str = ""
    artifact_digest: str = ""
    manifest_sha256: str = ""
    release_id: str = ""
    snapshot_id: str = ""
    run_id: str = ""
    run_attempt: int = 0
    phase: str = ""
    artifact_manifest_sha256: str = ""


def derive_build_version(
    *, source_revision: str, release_id: str, snapshot_id: str,
    run_id: str, run_attempt: int, phase: str, manifest_sha256: str,
    artifact_id: str, artifact_digest: str,
) -> str:
    """Build a unique, bounded Pages identity from the exact deployed bundle."""
    revision = str(source_revision or "").strip().lower()
    release = str(release_id or "").strip()
    snapshot = str(snapshot_id or "").strip()
    run = str(run_id or "").strip()
    artifact = str(artifact_id or "").strip()
    digest = str(artifact_digest or "").strip().lower()
    manifest_hash = str(manifest_sha256 or "").strip().lower()
    normalized_phase = str(phase or "").strip()
    if (
        not re.fullmatch(r"[0-9a-f]{40,64}", revision)
        or not release
        or not snapshot
        or not re.fullmatch(r"[1-9][0-9]{0,19}", run)
        or not isinstance(run_attempt, int) or run_attempt <= 0
        or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", normalized_phase)
        or not re.fullmatch(r"[0-9a-f]{64}", manifest_hash)
        or not re.fullmatch(r"[1-9][0-9]{0,19}", artifact)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
    ):
        raise PagesDeploymentError("complete run, release, manifest, and Pages artifact identity are required")
    identity = {
        "schema_version": "pages-build-identity-v1",
        "source_revision": revision,
        "release_id": release,
        "snapshot_id": snapshot,
        "run_id": str(int(run)),
        "run_attempt": run_attempt,
        "phase": normalized_phase,
        "manifest_sha256": manifest_hash,
        "artifact_id": str(int(artifact)),
        "artifact_digest": digest,
    }
    digest = hashlib.sha256(json.dumps(
        identity, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    return f"prstk-v1-{digest[:48]}"


def _request_json(
    url: str,
    *,
    token: str,
    timeout: float = 15.0,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "PRStK-pages-deployment-verifier",
    }
    if payload is not None:
        headers["Content-Type"] = "application/json"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        status = int(exc.code)
        retryable = status in {404, 408, 425, 429} or status >= 500
        request_secrets = (token, *(str(value) for value in (payload or {}).values()))
        detail = _safe_error_detail(exc.read(8192), request_secrets)
        request_outcome = "rejected" if 400 <= status < 500 and status not in {408, 425, 429} else "unknown"
        error_code = f"pages_http_{status}"
        message = f"GitHub Pages request returned HTTP {status}"
        if detail:
            message = f"{message}: {detail}"
        raise PagesDeploymentError(
            message,
            retryable=retryable,
            error_code=error_code,
            request_outcome=request_outcome,
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise PagesDeploymentError(
            f"GitHub Pages request failed: {type(exc).__name__}",
            retryable=True,
            error_code="pages_network_error",
            request_outcome="unknown",
        ) from exc
    except ValueError as exc:
        raise PagesDeploymentError("GitHub Pages deployment response is invalid JSON") from exc


def verify_deployment(
    *,
    api_url: str,
    repository: str,
    token: str,
    expected_build_version: str,
    deployment_id: str,
    status_url: str,
    timeout_seconds: float = 180.0,
    poll_seconds: float = 2.0,
    request_json: Callable[..., Any] = _request_json,
    sleeper: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> PagesDeployment:
    """Poll a trusted deployment ID through GitHub's official status endpoint.

    The create response's ``status_url`` is checked as an identity assertion;
    GitHub's status API itself is addressed by deployment ID.
    """
    if (
        not repository
        or not token
        or not str(expected_build_version or "").strip()
        or not str(deployment_id or "").strip()
    ):
        raise PagesDeploymentError("repository, token, build version, and returned deployment ID are required")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", str(deployment_id)):
        raise PagesDeploymentError("returned Pages deployment ID is invalid")
    status_url = str(status_url or "").strip()
    if not _status_url_route(
        status_url,
        api_url=api_url,
        repository=repository,
        deployment_id=deployment_id,
    ):
        raise PagesDeploymentError("returned Pages status URL does not match the deployment ID")
    status_endpoint = f"{api_url.rstrip('/')}/repos/{repository}/pages/deployments/{deployment_id}"
    started = monotonic()
    deadline = started + max(0.0, timeout_seconds)
    delay = max(0.0, poll_seconds)
    while True:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise PagesDeploymentError(
                "successful Pages deployment status was not observed before timeout",
                retryable=True,
                error_code="pages_deployment_status_timeout",
                request_outcome="created",
                deployment_id=deployment_id,
                status_url=status_url,
                recoverable=True,
            )
        status_available = False
        try:
            status_payload = request_json(
                status_endpoint,
                token=token,
                timeout=min(15.0, remaining),
            )
            status_available = True
        except PagesDeploymentError as exc:
            if not exc.retryable:
                raise
            status_payload = None
        if status_available:
            if not isinstance(status_payload, dict):
                raise PagesDeploymentError("GitHub Pages deployment status is invalid")
            status = str(status_payload.get("status") or "").strip().casefold()
            if status == "succeed":
                return PagesDeployment(deployment_id, status, expected_build_version, status_url)
            if status in {
                "error", "failure", "inactive", "deployment_failed",
                "deployment_perms_error", "deployment_content_failed",
                "deployment_cancelled", "deployment_lost",
            }:
                raise PagesDeploymentError(f"GitHub Pages deployment ended with status {status}")
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise PagesDeploymentError(
                "successful Pages deployment status was not observed before timeout",
                retryable=True,
                error_code="pages_deployment_status_timeout",
                request_outcome="created",
                deployment_id=deployment_id,
                status_url=status_url,
                recoverable=True,
            )
        sleeper(min(delay, remaining))
        delay = min(15.0, max(1.0, delay * 2))


def _get_oidc_token(
    *,
    request_url: str,
    request_token: str,
    request_json: Callable[..., Any] = _request_json,
) -> str:
    if not request_url or not request_token:
        raise PagesDeploymentError("GitHub Actions OIDC request context is unavailable")
    payload = request_json(
        request_url,
        token=request_token,
    )
    token = str(payload.get("value") or "").strip() if isinstance(payload, dict) else ""
    if not token:
        raise PagesDeploymentError("GitHub Actions returned an empty OIDC token")
    return token


def _select_run_artifact(
    *,
    api_url: str,
    repository: str,
    token: str,
    run_id: str,
    artifact_name: str,
    request_json: Callable[..., Any],
) -> str:
    artifact_id, _digest = _select_run_artifact_binding(
        api_url=api_url, repository=repository, token=token, run_id=run_id,
        artifact_name=artifact_name, request_json=request_json,
    )
    return artifact_id


def _select_run_artifact_binding(
    *,
    api_url: str,
    repository: str,
    token: str,
    run_id: str,
    artifact_name: str,
    request_json: Callable[..., Any],
    expected_source_revision: str = "",
) -> tuple[str, str]:
    if not run_id or not artifact_name:
        raise PagesDeploymentError("workflow run ID and Pages artifact name are required")
    artifacts: list[dict[str, Any]] = []
    for page in range(1, 11):
        payload = request_json(
            f"{api_url.rstrip('/')}/repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100&page={page}",
            token=token,
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("artifacts"), list):
            raise PagesDeploymentError("workflow artifact listing response is invalid")
        batch = [row for row in payload["artifacts"] if isinstance(row, dict)]
        artifacts.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise PagesDeploymentError("workflow artifact listing exceeded the bounded page limit")
    matches = [row for row in artifacts if str(row.get("name") or "") == artifact_name]
    if len(matches) != 1:
        raise PagesDeploymentError("the current workflow run must contain exactly one matching Pages artifact")
    artifact = matches[0]
    artifact_id = str(artifact.get("id") or "").strip()
    if not artifact_id.isdigit() or artifact.get("expired") is True:
        raise PagesDeploymentError("the matching Pages artifact has no valid ID or has expired")
    artifact_digest = str(artifact.get("digest") or "").strip().lower()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", artifact_digest):
        raise PagesDeploymentError("the matching Pages artifact has no verified SHA-256 digest")
    workflow_run = artifact.get("workflow_run")
    artifact_run_id = str(workflow_run.get("id") or "").strip() if isinstance(workflow_run, dict) else ""
    artifact_revision = str(workflow_run.get("head_sha") or "").strip().lower() if isinstance(workflow_run, dict) else ""
    if (
        artifact_run_id != str(run_id)
        or (expected_source_revision and artifact_revision != expected_source_revision.lower())
    ):
        raise PagesDeploymentError("the matching Pages artifact belongs to a different run or source revision")
    return artifact_id, artifact_digest


MAX_PAGES_ARTIFACT_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_PAGES_ARTIFACT_TAR_BYTES = 128 * 1024 * 1024
MAX_PAGES_ARTIFACT_TAR_MEMBERS = 20_000
PAGES_MANIFEST_MEMBER = "data/release-manifest.json"


def _manifest_identity_from_bytes(raw: bytes) -> tuple[dict[str, Any], str]:
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PagesDeploymentError(f"release manifest invalid: {type(exc).__name__}") from exc
    if not isinstance(manifest, dict):
        raise PagesDeploymentError("release manifest identity is invalid")
    release_id = str(manifest.get("release_id") or "").strip()
    snapshot_id = str(manifest.get("market_snapshot_id") or "").strip()
    if not release_id or not snapshot_id:
        raise PagesDeploymentError("release manifest is missing release or market snapshot identity")
    return manifest, hashlib.sha256(raw).hexdigest()


def _read_manifest_identity(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PagesDeploymentError(f"release manifest unavailable: {type(exc).__name__}") from exc
    return _manifest_identity_from_bytes(raw)


def _manifest_from_pages_artifact_archive(archive_bytes: bytes, *, expected_digest: str) -> bytes:
    """Extract the exact manifest from a bounded GitHub Pages artifact archive."""
    if len(archive_bytes) > MAX_PAGES_ARTIFACT_ARCHIVE_BYTES:
        raise PagesDeploymentError("Pages artifact archive exceeds the verification size limit")
    actual_digest = "sha256:" + hashlib.sha256(archive_bytes).hexdigest()
    if actual_digest != expected_digest:
        raise PagesDeploymentError(
            "downloaded Pages artifact digest does not match GitHub metadata",
            error_code="pages_artifact_digest_mismatch",
        )
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            files = [item for item in archive.infolist() if not item.is_dir()]
            if len(files) != 1 or files[0].filename != "artifact.tar":
                raise PagesDeploymentError("Pages artifact ZIP does not contain exactly one artifact.tar")
            if files[0].file_size > MAX_PAGES_ARTIFACT_TAR_BYTES:
                raise PagesDeploymentError("Pages artifact tar exceeds the verification size limit")
            tar_bytes = archive.read(files[0])
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as packed:
            members = packed.getmembers()
            if len(members) > MAX_PAGES_ARTIFACT_TAR_MEMBERS:
                raise PagesDeploymentError("Pages artifact tar contains too many entries")
            matches = [
                item for item in members
                if item.name.replace("\\", "/") in {
                    PAGES_MANIFEST_MEMBER, f"./{PAGES_MANIFEST_MEMBER}",
                }
            ]
            if len(matches) != 1 or not matches[0].isfile() or matches[0].size > 1_000_000:
                raise PagesDeploymentError("Pages artifact manifest member is missing or ambiguous")
            member = packed.extractfile(matches[0])
            if member is None:
                raise PagesDeploymentError("Pages artifact manifest member cannot be read")
            raw = member.read(1_000_001)
            if len(raw) > 1_000_000:
                raise PagesDeploymentError("Pages artifact manifest exceeds the verification size limit")
            return raw
    except PagesDeploymentError:
        raise
    except (OSError, tarfile.TarError, zipfile.BadZipFile, EOFError) as exc:
        raise PagesDeploymentError(
            f"Pages artifact archive is invalid: {type(exc).__name__}",
            error_code="pages_artifact_archive_invalid",
        ) from exc


def _download_pages_artifact_manifest(
    *, api_url: str, repository: str, token: str, artifact_id: str,
    artifact_digest: str, timeout: float = 30.0,
) -> bytes:
    endpoint = f"{api_url.rstrip('/')}/repos/{repository}/actions/artifacts/{artifact_id}/zip"
    request = Request(endpoint, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "PRStK-pages-deployment-verifier",
    })
    try:
        with _open_artifact_url(request, timeout=max(1, int(timeout))) as response:
            archive_bytes = response.read(MAX_PAGES_ARTIFACT_ARCHIVE_BYTES + 1)
    except HTTPError as exc:
        raise PagesDeploymentError(
            f"Pages artifact download returned HTTP {int(exc.code)}",
            error_code=f"pages_artifact_download_http_{int(exc.code)}",
            request_outcome="not_started",
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise PagesDeploymentError(
            f"Pages artifact download failed: {type(exc).__name__}",
            error_code="pages_artifact_download_failed",
            request_outcome="not_started",
        ) from exc
    return _manifest_from_pages_artifact_archive(archive_bytes, expected_digest=artifact_digest)


def create_deployment(
    *,
    api_url: str,
    repository: str,
    token: str,
    run_id: str,
    artifact_name: str,
    source_revision: str,
    build_version: str = "",
    manifest_path: Path = Path("site/data/release-manifest.json"),
    run_attempt: int = 1,
    phase: str = "release",
    oidc_request_url: str,
    oidc_request_token: str,
    timeout_seconds: float = 180.0,
    poll_seconds: float = 2.0,
    request_json: Callable[..., Any] = _request_json,
    sleeper: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> PagesDeployment:
    """Create one Pages deployment using this run's artifact and real API response.

    The create request is never retried: a lost response is ambiguous and must
    fail closed rather than potentially creating a second deployment.
    """
    revision = str(source_revision or "").strip().lower()
    if not repository or not token or not re.fullmatch(r"[0-9a-f]{40,64}", revision):
        raise PagesDeploymentError("repository, GitHub token, and full source revision are required")
    artifact_id, artifact_digest = _select_run_artifact_binding(
        api_url=api_url,
        repository=repository,
        token=token,
        run_id=run_id,
        artifact_name=artifact_name,
        request_json=request_json,
        expected_source_revision=revision,
    )
    try:
        manifest, manifest_sha256 = _read_manifest_identity(manifest_path)
        deployed_manifest_bytes = _download_pages_artifact_manifest(
            api_url=api_url, repository=repository, token=token,
            artifact_id=artifact_id, artifact_digest=artifact_digest,
        )
        deployed_manifest, artifact_manifest_sha256 = _manifest_identity_from_bytes(deployed_manifest_bytes)
    except PagesDeploymentError as exc:
        raise PagesDeploymentError(
            str(exc), error_code=exc.error_code, request_outcome="not_started",
            artifact_id=artifact_id, artifact_digest=artifact_digest, phase=phase,
            manifest_sha256=locals().get("manifest_sha256", ""),
            artifact_manifest_sha256=locals().get("artifact_manifest_sha256", ""),
            release_id=str(locals().get("manifest", {}).get("release_id") or ""),
            snapshot_id=str(locals().get("manifest", {}).get("market_snapshot_id") or ""),
        ) from exc
    if artifact_manifest_sha256 != manifest_sha256:
        raise PagesDeploymentError(
            "selected Pages artifact manifest differs from the frozen local manifest",
            error_code="pages_artifact_manifest_mismatch",
            request_outcome="not_started", artifact_id=artifact_id,
            artifact_digest=artifact_digest, manifest_sha256=manifest_sha256,
            artifact_manifest_sha256=artifact_manifest_sha256,
            release_id=str(manifest.get("release_id") or ""),
            snapshot_id=str(manifest.get("market_snapshot_id") or ""), phase=phase,
        )
    if (
        str(deployed_manifest.get("release_id") or "") != str(manifest.get("release_id") or "")
        or str(deployed_manifest.get("market_snapshot_id") or "") != str(manifest.get("market_snapshot_id") or "")
    ):
        raise PagesDeploymentError(
            "selected Pages artifact release identity differs from the frozen manifest",
            error_code="pages_artifact_release_identity_mismatch",
            request_outcome="not_started", artifact_id=artifact_id,
            artifact_digest=artifact_digest, manifest_sha256=manifest_sha256,
            artifact_manifest_sha256=artifact_manifest_sha256,
            release_id=str(manifest.get("release_id") or ""),
            snapshot_id=str(manifest.get("market_snapshot_id") or ""), phase=phase,
        )
    release_id = str(manifest.get("release_id") or "")
    snapshot_id = str(manifest.get("market_snapshot_id") or "")
    bound_build_version = derive_build_version(
        source_revision=revision,
        release_id=release_id,
        snapshot_id=snapshot_id,
        run_id=run_id,
        run_attempt=run_attempt,
        phase=phase,
        manifest_sha256=manifest_sha256,
        artifact_id=artifact_id,
        artifact_digest=artifact_digest,
    )
    if build_version and build_version != bound_build_version:
        raise PagesDeploymentError("requested Pages build version does not match the frozen deployment identity")
    try:
        oidc = _get_oidc_token(
            request_url=oidc_request_url,
            request_token=oidc_request_token,
            request_json=request_json,
        )
    except PagesDeploymentError as exc:
        raise PagesDeploymentError(
            str(exc), retryable=exc.retryable, error_code=exc.error_code,
            request_outcome="not_started", artifact_id=artifact_id,
            artifact_digest=artifact_digest, manifest_sha256=manifest_sha256,
            artifact_manifest_sha256=artifact_manifest_sha256,
            build_version=bound_build_version, release_id=release_id,
            snapshot_id=snapshot_id, phase=phase,
        ) from exc
    deployment_url = f"{api_url.rstrip('/')}/repos/{repository}/pages/deployments"
    try:
        created = request_json(
            deployment_url,
            token=token,
            method="POST",
            payload={
                "artifact_id": int(artifact_id),
                "pages_build_version": bound_build_version,
                "oidc_token": oidc,
            },
        )
    except PagesDeploymentError as exc:
        if exc.request_outcome == "rejected":
            raise PagesDeploymentError(
                f"Pages deployment create was rejected ({exc.error_code}): {exc}",
                retryable=False,
                error_code=exc.error_code,
                request_outcome="rejected",
                artifact_id=artifact_id,
                artifact_digest=artifact_digest,
                manifest_sha256=manifest_sha256,
                artifact_manifest_sha256=artifact_manifest_sha256,
                build_version=bound_build_version,
                release_id=release_id,
                snapshot_id=snapshot_id,
                phase=phase,
            ) from exc
        raise PagesDeploymentError(
            f"Pages deployment create result is unknown; refusing a duplicate create ({exc})",
            error_code=exc.error_code,
            request_outcome="unknown",
            artifact_id=artifact_id,
            artifact_digest=artifact_digest,
            manifest_sha256=manifest_sha256,
            artifact_manifest_sha256=artifact_manifest_sha256,
            build_version=bound_build_version,
            release_id=release_id,
            snapshot_id=snapshot_id,
            phase=phase,
        ) from exc
    if not isinstance(created, dict):
        raise PagesDeploymentError("Pages deployment create response is invalid")
    deployment_id = str(created.get("id") or "").strip()
    status_url = str(created.get("status_url") or "").strip()
    page_url = str(created.get("page_url") or "").strip()
    if not deployment_id or not status_url or not page_url:
        raise PagesDeploymentError(
            "Pages deployment create response omitted its trusted identity",
            error_code="pages_create_identity_missing", request_outcome="unknown",
            artifact_id=artifact_id, artifact_digest=artifact_digest,
            manifest_sha256=manifest_sha256, artifact_manifest_sha256=artifact_manifest_sha256,
            build_version=bound_build_version,
            release_id=release_id, snapshot_id=snapshot_id, phase=phase,
        )
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", deployment_id):
        raise PagesDeploymentError(
            "Pages deployment create response returned an invalid deployment ID",
            error_code="pages_deployment_id_invalid", request_outcome="unknown",
            artifact_id=artifact_id, artifact_digest=artifact_digest,
            manifest_sha256=manifest_sha256, artifact_manifest_sha256=artifact_manifest_sha256,
            build_version=bound_build_version,
            release_id=release_id, snapshot_id=snapshot_id, phase=phase,
        )
    if not _status_url_route(
        status_url,
        api_url=api_url,
        repository=repository,
        deployment_id=deployment_id,
    ):
        shape = _safe_status_url_shape(
            status_url, api_url=api_url, repository=repository, deployment_id=deployment_id,
        )
        raise PagesDeploymentError(
            f"Pages deployment returned an unexpected status URL (shape: {shape})",
            error_code="pages_status_url_identity_mismatch",
            request_outcome="created",
            deployment_id=deployment_id,
            page_url=page_url,
            artifact_id=artifact_id,
            artifact_digest=artifact_digest,
            manifest_sha256=manifest_sha256,
            artifact_manifest_sha256=artifact_manifest_sha256,
            build_version=bound_build_version,
            release_id=release_id,
            snapshot_id=snapshot_id,
            phase=phase,
            status_url_shape=shape,
        )
    parsed_page = urlparse(page_url if "://" in page_url else f"https://{page_url}")
    if (
        parsed_page.scheme != "https"
        or not parsed_page.netloc
        or parsed_page.username is not None
        or parsed_page.password is not None
    ):
        raise PagesDeploymentError(
            "Pages deployment returned an invalid public page URL",
            error_code="pages_public_url_invalid", request_outcome="created",
            deployment_id=deployment_id, status_url=status_url,
            artifact_id=artifact_id, artifact_digest=artifact_digest,
            manifest_sha256=manifest_sha256, artifact_manifest_sha256=artifact_manifest_sha256,
            build_version=bound_build_version,
            release_id=release_id, snapshot_id=snapshot_id, phase=phase,
        )
    page_url = parsed_page.geturl()
    try:
        verified = verify_deployment(
            api_url=api_url,
            repository=repository,
            token=token,
            expected_build_version=bound_build_version,
            deployment_id=deployment_id,
            status_url=status_url,
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
            request_json=request_json,
            sleeper=sleeper,
            monotonic=monotonic,
        )
    except PagesDeploymentError as exc:
        raise PagesDeploymentError(
            str(exc),
            retryable=exc.retryable,
            error_code=exc.error_code,
            request_outcome="created",
            deployment_id=deployment_id,
            status_url=status_url,
            page_url=page_url,
            artifact_id=artifact_id,
            artifact_digest=artifact_digest,
            manifest_sha256=manifest_sha256,
            artifact_manifest_sha256=artifact_manifest_sha256,
            build_version=bound_build_version,
            release_id=release_id,
            snapshot_id=snapshot_id,
            phase=phase,
            recoverable=exc.recoverable or exc.retryable,
        ) from exc
    return PagesDeployment(
        verified.deployment_id,
        verified.status,
        verified.build_version,
        verified.status_url,
        page_url,
        artifact_id,
        artifact_digest,
        manifest_sha256,
        release_id,
        snapshot_id,
        run_id,
        run_attempt,
        phase,
        artifact_manifest_sha256,
    )


def _write_outputs(values: dict[str, Any]) -> None:
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


def _write_binding(path: Path | None, value: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def finalize_binding_public_observation(
    *, binding_path: Path, phase: str, gate_outcome: str, gate_allowed: bool,
    gate_status: str, expected_release_id: str = "", actual_release_id: str = "",
    expected_snapshot_id: str = "", actual_snapshot_id: str = "",
    http_status: str = "", attempts_json: str = "[]",
) -> dict[str, Any]:
    """Attach the public release-gate result to this exact deployment binding."""
    try:
        binding = json.loads(binding_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PagesDeploymentError(
            f"Pages deployment binding unavailable: {type(exc).__name__}",
            error_code="pages_deployment_binding_unavailable",
        ) from exc
    if (
        not isinstance(binding, dict)
        or binding.get("schema_version") != "pages-deployment-binding-v1"
        or not str(binding.get("repository") or "")
        or not re.fullmatch(r"[1-9][0-9]{0,19}", str(binding.get("workflow_run_id") or ""))
        or not isinstance(binding.get("workflow_run_attempt"), int)
        or binding.get("workflow_run_attempt", 0) <= 0
        or not re.fullmatch(r"[0-9a-f]{40,64}", str(binding.get("source_revision") or "").lower())
        or not str(binding.get("phase") or "")
        or str(binding.get("phase") or "") != str(phase or "")
    ):
        raise PagesDeploymentError(
            "Pages deployment binding identity is invalid",
            error_code="pages_deployment_binding_identity_invalid",
        )
    try:
        attempts = json.loads(attempts_json)
    except json.JSONDecodeError as exc:
        raise PagesDeploymentError(
            "Pages public observation attempts are invalid JSON",
            error_code="pages_public_observation_attempts_invalid",
        ) from exc
    if not isinstance(attempts, list) or len(attempts) > 24:
        raise PagesDeploymentError(
            "Pages public observation attempts exceed the contract",
            error_code="pages_public_observation_attempts_invalid",
        )
    safe_attempts: list[dict[str, Any]] = []
    allowed_attempt_fields = {
        "attempt", "at", "http_status", "expected_release_id", "actual_release_id",
        "expected_snapshot_id", "actual_snapshot_id", "error_category", "retryable",
        "superseded", "deployment_id",
    }
    for row in attempts:
        if not isinstance(row, dict):
            raise PagesDeploymentError(
                "Pages public observation attempt has an invalid shape",
                error_code="pages_public_observation_attempts_invalid",
            )
        safe_attempts.append({
            key: value if isinstance(value, (str, bool, int, float)) or value is None else "invalid"
            for key, value in row.items() if key in allowed_attempt_fields
        })
    outcome = str(gate_outcome or "not_run").casefold()
    status = str(gate_status or "not_run").casefold()
    allowed = bool(gate_allowed)
    if allowed and (
        outcome != "success"
        or not expected_release_id
        or not actual_release_id
        or not expected_snapshot_id
        or not actual_snapshot_id
        or actual_release_id != expected_release_id
        or actual_snapshot_id != expected_snapshot_id
    ):
        raise PagesDeploymentError(
            "Pages public release gate allowed a contradictory identity",
            error_code="pages_public_observation_identity_conflict",
        )
    observation_status = "verified" if allowed else "blocked" if outcome != "not_run" else "not_run"
    binding["public_observation"] = {
        "schema_version": "pages-public-observation-v1",
        "source": "release_gate",
        "status": observation_status,
        "gate_outcome": outcome,
        "gate_status": status,
        "allowed": allowed,
        "expected_release_id": str(expected_release_id or "")[:160],
        "actual_release_id": str(actual_release_id or "")[:160],
        "expected_snapshot_id": str(expected_snapshot_id or "")[:160],
        "actual_snapshot_id": str(actual_snapshot_id or "")[:160],
        "http_status": str(http_status or "")[:8],
        "attempts": safe_attempts,
        "observed_at": datetime.now(UTC).isoformat(),
    }
    _write_binding(binding_path, binding)
    return binding


def main() -> int:
    parser = argparse.ArgumentParser(description="Create and verify an identity-bound GitHub Pages deployment")
    parser.add_argument("--mode", choices=("derive-version", "deploy", "verify", "observe"), required=True)
    parser.add_argument("--repository", default=os.getenv("GITHUB_REPOSITORY", ""))
    parser.add_argument("--api-url", default=os.getenv("GITHUB_API_URL", "https://api.github.com"))
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN", ""))
    parser.add_argument("--source-revision", default=os.getenv("GITHUB_SHA", ""))
    parser.add_argument("--release-id", default=os.getenv("RELEASE_ID", ""))
    parser.add_argument("--manifest", type=Path, default=Path("site/data/release-manifest.json"))
    parser.add_argument("--phase", default=os.getenv("PAGES_DEPLOYMENT_PHASE", "release"))
    parser.add_argument("--run-attempt", type=int, default=int(os.getenv("GITHUB_RUN_ATTEMPT", "0") or "0"))
    parser.add_argument(
        "--binding-path",
        type=Path,
        default=Path(os.environ["PAGES_DEPLOYMENT_BINDING_PATH"]) if os.getenv("PAGES_DEPLOYMENT_BINDING_PATH") else None,
    )
    parser.add_argument(
        "--expected-build-version",
        default=os.getenv("PAGES_BUILD_VERSION", ""),
    )
    parser.add_argument("--deployment-id", default=os.getenv("PAGES_DEPLOYMENT_ID", ""))
    parser.add_argument("--status-url", default=os.getenv("PAGES_DEPLOYMENT_STATUS_URL", ""))
    parser.add_argument("--artifact-name", default=os.getenv("PAGES_ARTIFACT_NAME", "github-pages"))
    parser.add_argument("--run-id", default=os.getenv("GITHUB_RUN_ID", ""))
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--gate-outcome", default=os.getenv("PAGES_GATE_OUTCOME", "not_run"))
    parser.add_argument("--gate-allowed", default=os.getenv("PAGES_GATE_ALLOWED", "false"))
    parser.add_argument("--gate-status", default=os.getenv("PAGES_GATE_STATUS", "not_run"))
    parser.add_argument("--expected-release-id", default=os.getenv("PAGES_GATE_EXPECTED_RELEASE_ID", ""))
    parser.add_argument("--actual-release-id", default=os.getenv("PAGES_GATE_ACTUAL_RELEASE_ID", ""))
    parser.add_argument("--expected-snapshot-id", default=os.getenv("PAGES_GATE_EXPECTED_SNAPSHOT_ID", ""))
    parser.add_argument("--actual-snapshot-id", default=os.getenv("PAGES_GATE_ACTUAL_SNAPSHOT_ID", ""))
    parser.add_argument("--gate-http-status", default=os.getenv("PAGES_GATE_HTTP_STATUS", ""))
    parser.add_argument("--gate-attempts", default=os.getenv("PAGES_GATE_ATTEMPTS", "[]"))
    args = parser.parse_args()
    if args.mode == "observe":
        try:
            binding = finalize_binding_public_observation(
                binding_path=args.binding_path,
                phase=args.phase,
                gate_outcome=args.gate_outcome,
                gate_allowed=args.gate_allowed.casefold() == "true",
                gate_status=args.gate_status,
                expected_release_id=args.expected_release_id,
                actual_release_id=args.actual_release_id,
                expected_snapshot_id=args.expected_snapshot_id,
                actual_snapshot_id=args.actual_snapshot_id,
                http_status=args.gate_http_status,
                attempts_json=args.gate_attempts,
            )
        except PagesDeploymentError as exc:
            _write_outputs({"observed": False, "error_code": exc.error_code, "error": str(exc)})
            return 1
        _write_outputs({
            "observed": True,
            "binding_schema": binding["schema_version"],
            "public_observation_status": binding["public_observation"]["status"],
        })
        return 0
    if args.mode == "derive-version":
        try:
            manifest, manifest_sha256 = _read_manifest_identity(args.manifest)
            release_id = str(args.release_id or manifest.get("release_id") or "")
            artifact_id = os.getenv("PAGES_ARTIFACT_ID", "")
            artifact_digest = os.getenv("PAGES_ARTIFACT_DIGEST", "")
            build_version = derive_build_version(
                source_revision=args.source_revision,
                release_id=release_id,
                snapshot_id=str(manifest.get("market_snapshot_id") or ""),
                run_id=args.run_id,
                run_attempt=args.run_attempt,
                phase=args.phase,
                manifest_sha256=manifest_sha256,
                artifact_id=artifact_id,
                artifact_digest=artifact_digest,
            )
        except PagesDeploymentError as exc:
            _write_outputs({"derived": False, "error": str(exc)})
            return 1
        _write_outputs({
            "derived": True,
            "pages_build_version": build_version,
            "source_revision": args.source_revision.strip().lower(),
            "release_id": release_id,
            "snapshot_id": str(manifest.get("market_snapshot_id") or ""),
            "manifest_sha256": manifest_sha256,
            "artifact_id": artifact_id,
            "artifact_digest": artifact_digest,
            "phase": args.phase,
            "error": "",
        })
        return 0
    try:
        if args.mode == "deploy":
            deployment = create_deployment(
                api_url=args.api_url,
                repository=args.repository,
                token=args.token,
                run_id=args.run_id,
                artifact_name=args.artifact_name,
                source_revision=args.source_revision,
                build_version=args.expected_build_version,
                manifest_path=args.manifest,
                run_attempt=args.run_attempt,
                phase=args.phase,
                oidc_request_url=os.getenv("ACTIONS_ID_TOKEN_REQUEST_URL", ""),
                oidc_request_token=os.getenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN", ""),
                timeout_seconds=args.timeout_seconds,
            )
            _write_outputs({
                "available": True,
                "verified": True,
                "recoverable": False,
                "request_outcome": "created",
                "deployment_id": deployment.deployment_id,
                "deployment_status_url": deployment.status_url,
                "deployment_status_url_shape": _safe_status_url_shape(
                    deployment.status_url,
                    api_url=args.api_url,
                    repository=args.repository,
                    deployment_id=deployment.deployment_id,
                ),
                "deployment_status": deployment.status,
                "deployment_build_version": deployment.build_version,
                "artifact_id": deployment.artifact_id,
                "artifact_digest": deployment.artifact_digest,
                "manifest_sha256": deployment.manifest_sha256,
                "artifact_manifest_sha256": deployment.artifact_manifest_sha256,
                "artifact_manifest_matches_frozen": deployment.artifact_manifest_sha256 == deployment.manifest_sha256,
                "release_id": deployment.release_id,
                "snapshot_id": deployment.snapshot_id,
                "deployment_phase": deployment.phase,
                "source_revision": args.source_revision.strip().lower(),
                "page_url": deployment.page_url,
                "workflow_run_id": args.run_id,
                "workflow_run_attempt": args.run_attempt,
                "error": "",
            })
            _write_binding(args.binding_path, {
                "schema_version": "pages-deployment-binding-v1",
                "repository": args.repository,
                "workflow_run_id": args.run_id,
                "workflow_run_attempt": args.run_attempt,
                "source_revision": args.source_revision.strip().lower(),
                "phase": deployment.phase,
                "artifact_id": deployment.artifact_id,
                "artifact_digest": deployment.artifact_digest,
                "manifest_sha256": deployment.manifest_sha256,
                "artifact_manifest_sha256": deployment.artifact_manifest_sha256,
                "release_id": deployment.release_id,
                "snapshot_id": deployment.snapshot_id,
                "pages_build_version": deployment.build_version,
                "request_outcome": "created",
                "deployment_id": deployment.deployment_id,
                "deployment_status": deployment.status,
                "public_observation": "pages_deployment_status_succeeded; content_release_gate_pending",
            })
            return 0
        deployment = verify_deployment(
            api_url=args.api_url,
            repository=args.repository,
            token=args.token,
            expected_build_version=args.expected_build_version,
            deployment_id=args.deployment_id,
            status_url=args.status_url,
            timeout_seconds=args.timeout_seconds,
        )
        _write_outputs({
            "verified": True,
            "recoverable": False,
            "request_outcome": "created",
            "deployment_id": deployment.deployment_id,
            "deployment_status": deployment.status,
            "deployment_build_version": deployment.build_version,
            "deployment_status_url": deployment.status_url,
            "deployment_status_url_shape": _safe_status_url_shape(
                deployment.status_url,
                api_url=args.api_url,
                repository=args.repository,
                deployment_id=deployment.deployment_id,
            ),
            "workflow_run_id": os.getenv("GITHUB_RUN_ID", ""),
            "error": "",
        })
    except PagesDeploymentError as exc:
        candidate_id = exc.deployment_id or (args.deployment_id if args.mode == "verify" else "")
        deployment_id = candidate_id if re.fullmatch(r"[A-Za-z0-9._-]{1,128}", candidate_id) else ""
        status_url_for_shape = exc.status_url or (args.status_url if args.mode == "verify" else "")
        status_url_shape = exc.status_url_shape or _safe_status_url_shape(
            status_url_for_shape,
            api_url=args.api_url,
            repository=args.repository,
            deployment_id=deployment_id,
        )
        _write_outputs({
            "available": False,
            "verified": False,
            "recoverable": exc.recoverable,
            "request_outcome": exc.request_outcome,
            "deployment_id": deployment_id,
            "deployment_status_url": exc.status_url,
            "deployment_status_url_shape": status_url_shape,
            "page_url": exc.page_url,
            "artifact_id": exc.artifact_id,
            "deployment_status": "unknown",
            "deployment_build_version": exc.build_version,
            "artifact_digest": exc.artifact_digest,
            "manifest_sha256": exc.manifest_sha256,
            "artifact_manifest_sha256": exc.artifact_manifest_sha256,
            "release_id": exc.release_id,
            "snapshot_id": exc.snapshot_id,
            "deployment_phase": exc.phase or args.phase,
            "error": str(exc),
            "error_code": exc.error_code,
        })
        if args.mode == "deploy":
            try:
                manifest, manifest_sha256 = _read_manifest_identity(args.manifest)
                release_id = str(manifest.get("release_id") or "")
                snapshot_id = str(manifest.get("market_snapshot_id") or "")
            except PagesDeploymentError:
                manifest_sha256, release_id, snapshot_id = "", "", ""
            _write_binding(args.binding_path, {
                "schema_version": "pages-deployment-binding-v1",
                "repository": args.repository,
                "workflow_run_id": args.run_id,
                "workflow_run_attempt": args.run_attempt,
                "source_revision": args.source_revision.strip().lower(),
                "phase": exc.phase or args.phase,
                "artifact_id": exc.artifact_id,
                "artifact_digest": exc.artifact_digest,
                "manifest_sha256": exc.manifest_sha256 or manifest_sha256,
                "artifact_manifest_sha256": exc.artifact_manifest_sha256,
                "release_id": exc.release_id or release_id,
                "snapshot_id": exc.snapshot_id or snapshot_id,
                "pages_build_version": exc.build_version,
                "request_outcome": exc.request_outcome,
                "deployment_id": deployment_id,
                "deployment_status": "unknown",
                "public_observation": "not_observed",
                "error_code": exc.error_code,
            })
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
