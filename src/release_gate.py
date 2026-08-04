"""Fail-closed release verification immediately before notifications."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

from src.release_manifest import verify_release_files


@dataclass(frozen=True)
class ReleaseGateResult:
    allowed: bool
    release_id: str = ""
    snapshot_id: str = ""
    errors: tuple[str, ...] = field(default_factory=tuple)
    manifest: dict[str, Any] = field(default_factory=dict)


def verify_release_for_delivery(
    *,
    manifest_path: Path | str = Path("site/data/release-manifest.json"),
    expected_snapshot_id: str | None = None,
    public_url: str | None = None,
    timeout: float = 15.0,
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

    if public_url:
        remote_url = public_url.rstrip("/") + "/data/release-manifest.json"
        try:
            response = requests.get(
                remote_url,
                timeout=timeout,
                headers={"Accept": "application/json", "User-Agent": "PRStK-release-gate"},
            )
            response.raise_for_status()
            remote = response.json()
            if not isinstance(remote, dict):
                errors.append("public manifest is not an object")
            elif remote.get("status") != "ready":
                errors.append("public manifest status is not ready")
            elif str(remote.get("release_id") or "") != release_id:
                errors.append("public manifest release_id does not match local release")
        except (requests.RequestException, ValueError) as exc:
            errors.append(f"public manifest unavailable: {type(exc).__name__}")

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
    args = parser.parse_args()
    result = verify_release_for_delivery(
        manifest_path=args.manifest,
        expected_snapshot_id=args.expected_snapshot_id,
        public_url=args.public_url,
    )
    print(json.dumps({
        "allowed": result.allowed,
        "release_id": result.release_id,
        "snapshot_id": result.snapshot_id,
        "errors": list(result.errors),
    }, ensure_ascii=False))
    return 0 if result.allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())
