"""Fail-closed release verification immediately before notifications."""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from src.artifact_contract import validate_release
from src.production_acceptance import validate_production_bundle
from src.release_manifest import verify_release_files


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


def _load_release_artifacts(manifest: dict[str, Any], *, site_root: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Load the three contract artifacts referenced by a manifest."""
    paths = manifest.get("artifact_paths")
    if not isinstance(paths, dict):
        return {}, ["manifest artifact paths are missing"]
    loaded: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for name in ("market.json", "research-report.json", "event-ledger.json"):
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
    return loaded, errors


def verify_release_for_delivery(
    *,
    manifest_path: Path | str = Path("site/data/release-manifest.json"),
    expected_snapshot_id: str | None = None,
    public_url: str | None = None,
    timeout: float = 15.0,
    public_attempts: int = 12,
    public_delay: float = 5.0,
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
        acceptance = validate_production_bundle(
            manifest=manifest,
            market=artifacts["market.json"],
            research=artifacts["research-report.json"],
            events=artifacts["event-ledger.json"],
            require_production_research=True,
        )
        errors.extend(acceptance.errors)

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
    args = parser.parse_args()
    result = verify_release_for_delivery(
        manifest_path=args.manifest,
        expected_snapshot_id=args.expected_snapshot_id,
        public_url=args.public_url,
        public_attempts=args.public_attempts,
        public_delay=args.public_delay,
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
