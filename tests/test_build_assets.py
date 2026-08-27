import hashlib
import json
from pathlib import Path

import pytest

from src.build_assets import ASSETS, PLACEHOLDER, build_assets


def _fixture(tmp_path: Path) -> Path:
    root = tmp_path / "site"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(
        '<link href="styles.css?v=__ASSET_VERSION__"><script src="app.js?v=__ASSET_VERSION__"></script>'
        '<img src="assets/hero-prism-cover.png?v=__ASSET_VERSION__">'
        '<meta name="prstk-api-base" content="__PUBLIC_API_BASE_URL__">',
        encoding="utf-8",
    )
    (root / "app.js").write_bytes(b"app")
    (root / "styles.css").write_bytes(b"css")
    (root / "report-client.js").write_bytes(b"client")
    (root / "assets" / "hero-prism-cover.png").write_bytes(b"png")
    return root


def test_build_assets_replaces_all_placeholders_and_writes_manifest(tmp_path, monkeypatch):
    root = _fixture(tmp_path)
    monkeypatch.setenv("PUBLIC_API_BASE_URL", "https://worker.example.test/")
    manifest = build_assets(root, build_sha="abc123")
    html = (root / "index.html").read_text(encoding="utf-8")
    assert PLACEHOLDER not in html
    assert html.count(manifest["asset_version"]) == 3
    assert "https://worker.example.test" in html
    assert "__PUBLIC_API_BASE_URL__" not in html
    assert manifest["build_sha"] == "abc123"
    saved = json.loads((root / "asset-manifest.json").read_text(encoding="utf-8"))
    assert saved == manifest
    for relative in ASSETS:
        expected = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        assert manifest["entries"][relative] == expected


def test_build_assets_fails_when_an_asset_is_missing(tmp_path):
    root = _fixture(tmp_path)
    (root / "styles.css").unlink()
    with pytest.raises(FileNotFoundError):
        build_assets(root)


def test_build_assets_requires_source_placeholder(tmp_path):
    root = _fixture(tmp_path)
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    with pytest.raises(ValueError, match="placeholder"):
        build_assets(root)


def test_build_assets_retries_transient_windows_replace_lock(tmp_path, monkeypatch):
    root = _fixture(tmp_path)
    original_replace = Path.replace
    attempts = {"count": 0}

    def flaky_replace(self: Path, target: Path):
        if self.name.startswith(".index.html.") and attempts["count"] == 0:
            attempts["count"] += 1
            raise PermissionError(13, "temporarily locked")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)
    manifest = build_assets(root, build_sha="retry")
    assert manifest["build_sha"] == "retry"
    assert attempts["count"] == 1
