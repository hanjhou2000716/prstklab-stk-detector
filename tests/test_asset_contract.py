import hashlib
import json

from src.asset_contract import ASSETS, validate_assets


def _write_bundle(root, *, version="1234567890abcdef"):
    root.mkdir(parents=True, exist_ok=True)
    (root / "assets").mkdir()
    for relative in ASSETS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(relative.encode())
    entries = {
        relative: hashlib.sha256((root / relative).read_bytes()).hexdigest()
        for relative in ASSETS
    }
    (root / "index.html").write_text(
        " ".join([f"styles.css?v={version}", f"app.js?v={version}", f"hero?v={version}"]),
        encoding="utf-8",
    )
    (root / "asset-manifest.json").write_text(
        json.dumps({"asset_version": version, "entries": entries}), encoding="utf-8"
    )


def test_asset_contract_accepts_hash_verified_bundle(tmp_path):
    _write_bundle(tmp_path)
    assert validate_assets(tmp_path) == []


def test_asset_contract_rejects_changed_asset(tmp_path):
    _write_bundle(tmp_path)
    (tmp_path / "app.js").write_bytes(b"changed")
    assert any("hash mismatch" in issue for issue in validate_assets(tmp_path))


def test_asset_contract_rejects_unfingerprinted_html(tmp_path):
    _write_bundle(tmp_path)
    (tmp_path / "index.html").write_text("app.js?v=__ASSET_VERSION__", encoding="utf-8")
    assert any("__ASSET_VERSION__" in issue for issue in validate_assets(tmp_path))
