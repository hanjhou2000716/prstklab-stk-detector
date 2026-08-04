import json

from src.release_manifest import build_release_manifest, verify_release_files, write_release_manifest


def _artifacts(tmp_path):
    site_data = tmp_path / "site" / "data"
    site_data.mkdir(parents=True)
    (site_data / "market.json").write_text(json.dumps({
        "generated_at": "2026-08-04T10:00:00+08:00",
        "snapshot_id": "market-12345678",
        "indices": [], "quotes": [], "source_health": {},
    }), encoding="utf-8")
    (site_data / "research-report.json").write_text(json.dumps({
        "schema_version": "2.0", "generated_at": "2026-08-04T10:00:00+08:00",
        "snapshot_id": "research-12345678", "sources": [], "candidates": [], "health": {},
    }), encoding="utf-8")
    (site_data / "event-ledger.json").write_text(json.dumps({"schema_version": 1, "events": {}}), encoding="utf-8")


def test_manifest_is_ready_and_hashes_are_verifiable(tmp_path):
    _artifacts(tmp_path)
    manifest = build_release_manifest(root=tmp_path)
    assert manifest["status"] == "ready"
    assert manifest["artifact_paths"]["market.json"] == "data/market.json"
    assert verify_release_files(manifest, root=tmp_path / "site") == []


def test_manifest_fails_closed_for_missing_artifact(tmp_path):
    _artifacts(tmp_path)
    (tmp_path / "site" / "data" / "event-ledger.json").unlink()
    manifest = build_release_manifest(root=tmp_path)
    assert manifest["status"] == "invalid"
    assert any("missing artifact" in item for item in manifest["validation_errors"])


def test_manifest_detects_hash_tampering(tmp_path):
    _artifacts(tmp_path)
    manifest = build_release_manifest(root=tmp_path)
    write_release_manifest(manifest, tmp_path / "site" / "data" / "release-manifest.json")
    (tmp_path / "site" / "data" / "market.json").write_text("{}", encoding="utf-8")
    assert any("hash mismatch" in item for item in verify_release_files(manifest, root=tmp_path / "site"))
