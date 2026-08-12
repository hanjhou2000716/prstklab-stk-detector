import json
from pathlib import Path

from src.asset_contract import validate_assets


def test_asset_contract_is_checked_when_a_release_emits_asset_manifest(tmp_path: Path):
    site = tmp_path / "site"
    data = site / "data"
    data.mkdir(parents=True)
    # The release gate's artifact checks are covered elsewhere; this fixture
    # isolates the static-shell invariant and makes the failure actionable.
    (site / "index.html").write_text("asset-v1 asset-v1 asset-v1", encoding="utf-8")
    (site / "app.js").write_text("console.log('v1')", encoding="utf-8")
    (site / "styles.css").write_text("body{}", encoding="utf-8")
    (site / "assets").mkdir()
    (site / "assets" / "hero-prism-cover.png").write_bytes(b"png")
    (site / "asset-manifest.json").write_text(json.dumps({
        "asset_version": "asset-v1",
        "entries": {"app.js": "wrong", "styles.css": "wrong", "assets/hero-prism-cover.png": "wrong"},
    }), encoding="utf-8")
    assert any("hash mismatch" in item for item in validate_assets(site))
