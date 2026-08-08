"""Build, validate and publish one canonical public release.

The individual data producers may run in different workflows, but Pages and
notification jobs must consume one coherent release.  This command is the
small publisher boundary: it refuses to publish an invalid manifest and only
returns success after the local artifact hashes and cross-file invariants pass.
It does not deploy Pages or send Telegram; those actions remain downstream
gates.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from src.data_release import DataReleaseError
from src.data_release import publish as publish_data_release
from src.release_gate import verify_release_for_delivery
from src.release_manifest import build_release_manifest, write_release_manifest


def publish_canonical_release(
    *,
    root: Path | str = Path("."),
    branch: str = "data-release",
    manifest_path: Path | str = Path("site/data/release-manifest.json"),
    includes: list[str] | None = None,
    message: str = "chore: publish canonical data release",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Publish only a release that passes its manifest and local release gate."""
    root = Path(root)
    manifest_path = Path(manifest_path)
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    manifest = build_release_manifest(root=root, output=manifest_path)
    write_release_manifest(manifest, manifest_path)
    result: dict[str, Any] = {
        "published": False,
        "dry_run": dry_run,
        "status": manifest.get("status"),
        "release_id": manifest.get("release_id", ""),
        "snapshot_id": manifest.get("market_snapshot_id", ""),
        "validation_errors": list(manifest.get("validation_errors") or []),
    }
    if manifest.get("status") != "ready":
        result["reason"] = "manifest_invalid"
        return result

    gate = verify_release_for_delivery(manifest_path=manifest_path)
    if not gate.allowed:
        result["reason"] = "local_release_gate_failed"
        result["validation_errors"] = list(gate.errors)
        return result
    if dry_run:
        result["reason"] = "dry_run"
        return result

    try:
        published = publish_data_release(
            root=root,
            branch=branch,
            includes=includes,
            message=message,
        )
    except DataReleaseError as exc:
        result["reason"] = "data_release_publish_failed"
        result["validation_errors"] = [str(exc)]
        return result
    result.update(published)
    # Verify again after the data-only branch update.  A concurrent writer or
    # partial push must not be reported as a successful canonical release.
    final_gate = verify_release_for_delivery(manifest_path=manifest_path)
    if not final_gate.allowed:
        result["published"] = False
        result["reason"] = "post_publish_gate_failed"
        result["validation_errors"] = list(final_gate.errors)
        return result
    result["published"] = bool(published.get("published") or published.get("unchanged"))
    result["reason"] = "published" if published.get("published") else "unchanged"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish one validated canonical data release")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--branch", default=os.getenv("DATA_RELEASE_BRANCH", "data-release"))
    parser.add_argument("--manifest", type=Path, default=Path("site/data/release-manifest.json"))
    parser.add_argument("--include", action="append", default=[])
    parser.add_argument("--message", default="chore: publish canonical data release")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = publish_canonical_release(
        root=args.root,
        branch=args.branch,
        manifest_path=args.manifest,
        includes=args.include,
        message=args.message,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("published") or result.get("dry_run") else 1


if __name__ == "__main__":
    raise SystemExit(main())
