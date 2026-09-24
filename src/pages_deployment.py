"""Verify the GitHub Pages build-version status created by this run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class PagesDeploymentError(RuntimeError):
    """Raised when the completed Pages deployment cannot be identified safely."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class PagesDeployment:
    deployment_id: str
    status: str
    build_version: str


def derive_build_version(*, source_revision: str, release_id: str) -> str:
    """Derive one stable Pages identity from both code and public data."""
    revision = str(source_revision or "").strip().lower()
    release = str(release_id or "").strip()
    if not re.fullmatch(r"[0-9a-f]{40,64}", revision) or not release:
        raise PagesDeploymentError("a full source revision and release identity are required")
    material = f"prstk-pages-release-v1\n{revision}\n{release}".encode()
    return hashlib.sha256(material).hexdigest()


def _request_json(url: str, *, token: str, timeout: float = 15.0) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "PRStK-pages-deployment-verifier",
    }
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        status = int(exc.code)
        retryable = status in {404, 408, 425, 429} or status >= 500
        raise PagesDeploymentError(
            f"GitHub Pages deployment lookup failed: HTTP {status}", retryable=retryable,
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise PagesDeploymentError(
            f"GitHub Pages deployment lookup failed: {type(exc).__name__}", retryable=True,
        ) from exc
    except ValueError as exc:
        raise PagesDeploymentError("GitHub Pages deployment response is invalid JSON") from exc


def verify_deployment(
    *,
    api_url: str,
    repository: str,
    token: str,
    expected_build_version: str,
    timeout_seconds: float = 45.0,
    poll_seconds: float = 2.0,
    request_json: Callable[..., Any] = _request_json,
    sleeper: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> PagesDeployment:
    """Confirm the Pages deployment for this action's build version succeeded.

    The Pages status endpoint accepts ``pages_build_version`` directly; the
    general Deployments API's numeric IDs are a different identifier and must
    not be substituted.
    """
    if (
        not repository
        or not token
        or not re.fullmatch(r"[0-9a-fA-F]{40,64}", expected_build_version)
    ):
        raise PagesDeploymentError("repository, token, and full build-version SHA are required")
    started = monotonic()
    deadline = started + max(0.0, timeout_seconds)
    delay = max(0.0, poll_seconds)
    status_url = f"{api_url.rstrip('/')}/repos/{repository}/pages/deployments/{expected_build_version}"
    while True:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise PagesDeploymentError("successful Pages deployment status was not observed before timeout")
        status_available = False
        try:
            status_payload = request_json(
                status_url,
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
                return PagesDeployment(expected_build_version, status, expected_build_version)
            if status in {"error", "failure", "inactive"}:
                raise PagesDeploymentError(f"GitHub Pages deployment ended with status {status}")
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise PagesDeploymentError("successful Pages deployment status was not observed before timeout")
        sleeper(min(delay, remaining))
        delay = min(15.0, max(1.0, delay * 2))


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
    parser = argparse.ArgumentParser(description="Verify a GitHub Pages build-version deployment")
    parser.add_argument("--mode", choices=("derive-version", "verify"), required=True)
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
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
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
        deployment = verify_deployment(
            api_url=args.api_url,
            repository=args.repository,
            token=args.token,
            expected_build_version=args.expected_build_version,
            timeout_seconds=args.timeout_seconds,
        )
        _write_outputs({
            "verified": True,
            "deployment_id": deployment.deployment_id,
            "deployment_status": deployment.status,
            "deployment_build_version": deployment.build_version,
            "workflow_run_id": os.getenv("GITHUB_RUN_ID", ""),
            "error": "",
        })
    except PagesDeploymentError as exc:
        _write_outputs({"verified": False, "deployment_status": "unknown", "error": str(exc)})
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
