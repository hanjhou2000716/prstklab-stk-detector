"""Validate the cache-busted static asset bundle before Pages upload."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ASSETS = ("app.js", "styles.css", "assets/hero-prism-cover.png")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_assets(root: Path = Path("site")) -> list[str]:
    """Return deterministic contract errors; never silently serve mixed assets."""
    issues: list[str] = []
    manifest_path = root / "asset-manifest.json"
    index_path = root / "index.html"
    if not manifest_path.is_file():
        return [f"asset manifest missing: {manifest_path.as_posix()}"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"asset manifest invalid: {type(exc).__name__}"]
    if not isinstance(manifest, dict):
        return ["asset manifest must be an object"]
    version = str(manifest.get("asset_version") or "")
    if len(version) < 8:
        issues.append("asset_version is missing or too short")
    entries = manifest.get("entries")
    if not isinstance(entries, dict):
        return [*issues, "asset manifest entries must be an object"]
    for relative in ASSETS:
        path = root / relative
        expected = str(entries.get(relative) or "")
        if not path.is_file():
            issues.append(f"asset missing: {relative}")
        elif not expected:
            issues.append(f"asset hash missing: {relative}")
        elif _sha256(path) != expected:
            issues.append(f"asset hash mismatch: {relative}")
    if not index_path.is_file():
        issues.append("index.html missing")
    else:
        html = index_path.read_text(encoding="utf-8")
        if "__ASSET_VERSION__" in html:
            issues.append("index.html still contains __ASSET_VERSION__")
        if version and html.count(version) < 3:
            issues.append("index.html does not reference the complete asset version")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("site"))
    args = parser.parse_args()
    issues = validate_assets(args.root)
    print(json.dumps({"ok": not issues, "issues": issues}, ensure_ascii=False, indent=2))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
