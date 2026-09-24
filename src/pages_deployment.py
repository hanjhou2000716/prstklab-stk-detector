"""Verify the GitHub Pages build-version status created by this run."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class PagesDeploymentError(RuntimeError):
    """Raised when the completed Pages deployment cannot be identified safely."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        error_code: str = "pages_deployment_error",
        request_outcome: str = "not_started",
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.error_code = error_code
        self.request_outcome = request_outcome


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


@dataclass(frozen=True)
class PagesDeployment:
    deployment_id: str
    status: str
    build_version: str
    status_url: str = ""
    page_url: str = ""
    artifact_id: str = ""


def derive_build_version(*, source_revision: str, release_id: str) -> str:
    """Return the build identity used by the pinned official Pages action.

    ``actions/deploy-pages`` reads the runner's reserved ``GITHUB_SHA`` and
    uses that value as ``pages_build_version``.  An environment override does
    not change GitHub's reserved value, so a locally derived content hash is
    not a deployment identity.  Public release identity is verified
    independently by the release gate.
    """
    revision = str(source_revision or "").strip().lower()
    release = str(release_id or "").strip()
    if not re.fullmatch(r"[0-9a-f]{40,64}", revision) or not release:
        raise PagesDeploymentError("a full source revision and release identity are required")
    return revision


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
    """Poll only the deployment identity and status URL returned by GitHub."""
    if (
        not repository
        or not token
        or not str(expected_build_version or "").strip()
        or not str(deployment_id or "").strip()
    ):
        raise PagesDeploymentError("repository, token, build version, and returned deployment ID are required")
    expected_status_url = f"{api_url.rstrip('/')}/repos/{repository}/pages/deployments/{deployment_id}/status"
    if str(status_url or "").rstrip("/") != expected_status_url:
        raise PagesDeploymentError("returned Pages status URL does not match the deployment ID")
    started = monotonic()
    deadline = started + max(0.0, timeout_seconds)
    delay = max(0.0, poll_seconds)
    while True:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise PagesDeploymentError("successful Pages deployment status was not observed before timeout")
        status_available = False
        try:
            status_payload = request_json(
                expected_status_url,
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
                return PagesDeployment(deployment_id, status, expected_build_version, expected_status_url)
            if status in {
                "error", "failure", "inactive", "deployment_failed",
                "deployment_perms_error", "deployment_content_failed",
                "deployment_cancelled", "deployment_lost",
            }:
                raise PagesDeploymentError(f"GitHub Pages deployment ended with status {status}")
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise PagesDeploymentError("successful Pages deployment status was not observed before timeout")
        sleeper(min(delay, remaining))
        delay = min(15.0, max(1.0, delay * 2))


def _pages_status_url(api_url: str, repository: str, deployment_id: str) -> str:
    return f"{api_url.rstrip('/')}/repos/{repository}/pages/deployments/{deployment_id}/status"


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
    return artifact_id


def create_deployment(
    *,
    api_url: str,
    repository: str,
    token: str,
    run_id: str,
    artifact_name: str,
    source_revision: str,
    build_version: str,
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
    if not build_version or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", build_version):
        raise PagesDeploymentError("a bounded, unique Pages build version is required")
    artifact_id = _select_run_artifact(
        api_url=api_url,
        repository=repository,
        token=token,
        run_id=run_id,
        artifact_name=artifact_name,
        request_json=request_json,
    )
    oidc = _get_oidc_token(
        request_url=oidc_request_url,
        request_token=oidc_request_token,
        request_json=request_json,
    )
    deployment_url = f"{api_url.rstrip('/')}/repos/{repository}/pages/deployments"
    try:
        created = request_json(
            deployment_url,
            token=token,
            method="POST",
            payload={
                "artifact_id": int(artifact_id),
                "pages_build_version": build_version,
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
            ) from exc
        raise PagesDeploymentError(
            f"Pages deployment create result is unknown; refusing a duplicate create ({exc})",
            error_code=exc.error_code,
            request_outcome="unknown",
        ) from exc
    if not isinstance(created, dict):
        raise PagesDeploymentError("Pages deployment create response is invalid")
    deployment_id = str(created.get("id") or "").strip()
    status_url = str(created.get("status_url") or "").strip().rstrip("/")
    page_url = str(created.get("page_url") or "").strip()
    if not deployment_id or not status_url or not page_url:
        raise PagesDeploymentError("Pages deployment create response omitted its trusted identity")
    parsed_status = urlparse(status_url)
    parsed_api = urlparse(api_url)
    if (
        parsed_status.scheme != "https"
        or parsed_status.netloc.casefold() != parsed_api.netloc.casefold()
        or status_url != _pages_status_url(api_url, repository, deployment_id)
    ):
        raise PagesDeploymentError("Pages deployment returned an unexpected status URL")
    parsed_page = urlparse(page_url if "://" in page_url else f"https://{page_url}")
    if (
        parsed_page.scheme != "https"
        or not parsed_page.netloc
        or parsed_page.username is not None
        or parsed_page.password is not None
    ):
        raise PagesDeploymentError("Pages deployment returned an invalid public page URL")
    page_url = parsed_page.geturl()
    verified = verify_deployment(
        api_url=api_url,
        repository=repository,
        token=token,
        expected_build_version=build_version,
        deployment_id=deployment_id,
        status_url=status_url,
        timeout_seconds=timeout_seconds,
        poll_seconds=poll_seconds,
        request_json=request_json,
        sleeper=sleeper,
        monotonic=monotonic,
    )
    return PagesDeployment(
        verified.deployment_id,
        verified.status,
        verified.build_version,
        verified.status_url,
        page_url,
        artifact_id,
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Create and verify an identity-bound GitHub Pages deployment")
    parser.add_argument("--mode", choices=("derive-version", "deploy", "verify"), required=True)
    parser.add_argument("--repository", default=os.getenv("GITHUB_REPOSITORY", ""))
    parser.add_argument("--api-url", default=os.getenv("GITHUB_API_URL", "https://api.github.com"))
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN", ""))
    parser.add_argument("--source-revision", default=os.getenv("GITHUB_SHA", ""))
    parser.add_argument("--release-id", default=os.getenv("RELEASE_ID", ""))
    parser.add_argument("--manifest", type=Path, default=Path("site/data/release-manifest.json"))
    parser.add_argument(
        "--expected-build-version",
        default=os.getenv("PAGES_BUILD_VERSION", os.getenv("GITHUB_SHA", "")),
    )
    parser.add_argument("--deployment-id", default=os.getenv("PAGES_DEPLOYMENT_ID", ""))
    parser.add_argument("--status-url", default=os.getenv("PAGES_DEPLOYMENT_STATUS_URL", ""))
    parser.add_argument("--artifact-name", default=os.getenv("PAGES_ARTIFACT_NAME", "github-pages"))
    parser.add_argument("--run-id", default=os.getenv("GITHUB_RUN_ID", ""))
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    args = parser.parse_args()
    if args.mode == "derive-version":
        release_id = str(args.release_id or "").strip()
        if not release_id:
            try:
                manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                _write_outputs({"derived": False, "error": f"release manifest unavailable: {type(exc).__name__}"})
                return 1
            release_id = str(manifest.get("release_id") or "") if isinstance(manifest, dict) else ""
        try:
            build_version = derive_build_version(
                source_revision=args.source_revision,
                release_id=release_id,
            )
        except PagesDeploymentError as exc:
            _write_outputs({"derived": False, "error": str(exc)})
            return 1
        _write_outputs({
            "derived": True,
            "pages_build_version": build_version,
            "source_revision": args.source_revision.strip().lower(),
            "release_id": release_id,
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
                oidc_request_url=os.getenv("ACTIONS_ID_TOKEN_REQUEST_URL", ""),
                oidc_request_token=os.getenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN", ""),
                timeout_seconds=args.timeout_seconds,
            )
            _write_outputs({
                "available": True,
                "verified": True,
                "deployment_id": deployment.deployment_id,
                "deployment_status_url": deployment.status_url,
                "deployment_status": deployment.status,
                "deployment_build_version": deployment.build_version,
                "artifact_id": deployment.artifact_id,
                "source_revision": args.source_revision.strip().lower(),
                "page_url": deployment.page_url,
                "workflow_run_id": args.run_id,
                "error": "",
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
            "deployment_id": deployment.deployment_id,
            "deployment_status": deployment.status,
            "deployment_build_version": deployment.build_version,
            "deployment_status_url": deployment.status_url,
            "workflow_run_id": os.getenv("GITHUB_RUN_ID", ""),
            "error": "",
        })
    except PagesDeploymentError as exc:
        _write_outputs({
            "available": False,
            "verified": False,
            "deployment_status": "unknown",
            "error": str(exc),
            "error_code": exc.error_code,
        })
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
