"""Build a deterministic cache-busted manifest for the static Mini App.

The source tree keeps ``__ASSET_VERSION__`` as a placeholder.  The Pages
workflow runs this module after restoring the immutable data release and
before uploading the site, so browsers never retain an older JS/CSS bundle
after a release.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

ASSETS = ("app.js", "styles.css", "assets/hero-prism-cover.png")
PLACEHOLDER = "__ASSET_VERSION__"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        Path(name).replace(path)
    except Exception:
        Path(name).unlink(missing_ok=True)
        raise


def build_assets(root: Path, *, build_sha: str | None = None) -> dict[str, Any]:
    root = root.resolve()
    entries: dict[str, str] = {}
    for relative in ASSETS:
        path = root / relative
        if not path.is_file():
            raise FileNotFoundError(f"static asset missing: {relative}")
        entries[relative] = _sha256(path)

    combined = hashlib.sha256("\n".join(f"{key}:{entries[key]}" for key in ASSETS).encode()).hexdigest()
    version = (os.getenv("ASSET_VERSION") or combined)[:16]
    index = root / "index.html"
    html = index.read_text(encoding="utf-8")
    if PLACEHOLDER not in html:
        raise ValueError("site/index.html is missing __ASSET_VERSION__ placeholders")
    _atomic_write(index, html.replace(PLACEHOLDER, version))

    manifest: dict[str, Any] = {
        "asset_version": version,
        "build_sha": build_sha or os.getenv("GITHUB_SHA"),
        "entries": entries,
    }
    _atomic_write(root / "asset-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("site"))
    parser.add_argument("--build-sha", default=None)
    args = parser.parse_args()
    manifest = build_assets(args.root, build_sha=args.build_sha)
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
