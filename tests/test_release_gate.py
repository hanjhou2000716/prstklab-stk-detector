import json

from src.release_gate import verify_release_for_delivery
from src.release_manifest import build_release_manifest, write_release_manifest


def _ready_release(tmp_path):
    data = tmp_path / "site" / "data"
    data.mkdir(parents=True)
    (data / "market.json").write_text(json.dumps({
        "generated_at": "2026-08-04T10:00:00+08:00",
        "snapshot_id": "market-12345678",
        "indices": [], "quotes": [], "source_health": {},
    }), encoding="utf-8")
    (data / "research-report.json").write_text(json.dumps({
        "schema_version": "2.0", "generated_at": "2026-08-04T10:00:00+08:00",
        "snapshot_id": "research-12345678", "sources": [], "candidates": [], "health": {},
    }), encoding="utf-8")
    (data / "event-ledger.json").write_text(json.dumps({"schema_version": 1, "retention_days": 30, "events": {}}), encoding="utf-8")
    manifest = build_release_manifest(root=tmp_path)
    write_release_manifest(manifest, data / "release-manifest.json")
    return data / "release-manifest.json", manifest


def test_release_gate_accepts_ready_matching_snapshot(tmp_path):
    path, manifest = _ready_release(tmp_path)
    result = verify_release_for_delivery(manifest_path=path, expected_snapshot_id="market-12345678")
    assert result.allowed is True
    assert result.release_id == manifest["release_id"]


def test_release_gate_blocks_snapshot_mismatch(tmp_path):
    path, _ = _ready_release(tmp_path)
    result = verify_release_for_delivery(manifest_path=path, expected_snapshot_id="market-other")
    assert result.allowed is False
    assert "does not match prepared snapshot" in ";".join(result.errors)


def test_release_gate_blocks_tampered_artifact(tmp_path):
    path, _ = _ready_release(tmp_path)
    (tmp_path / "site" / "data" / "market.json").write_text("{}", encoding="utf-8")
    result = verify_release_for_delivery(manifest_path=path, expected_snapshot_id="market-12345678")
    assert result.allowed is False
    assert any("hash mismatch" in error for error in result.errors)
