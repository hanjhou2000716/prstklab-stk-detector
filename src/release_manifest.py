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
        try:
            hashes[name] = sha256_file(path)
        except OSError as exc:
            errors.append(f"cannot hash artifact {path.as_posix()}: {type(exc).__name__}")

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
        "status": "invalid",
    }
    if not market_id or not research_id or not event_id:
        errors.append("all three snapshot IDs are required")
    if market and research:
        errors.extend(validate_release(market=market, research=research, manifest={**manifest, "status": "ready"}))
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
