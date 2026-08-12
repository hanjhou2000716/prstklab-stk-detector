import json
import sys

from src.release_gate import _load_release_artifacts
from src import release_manifest
from src.release_manifest import build_release_manifest


def _artifacts(tmp_path):
    site_data = tmp_path / "site" / "data"
    site_data.mkdir(parents=True)
    (site_data / "market.json").write_text(json.dumps({"generated_at": "2026-08-04T10:00:00+08:00", "snapshot_id": "market-12345678", "indices": [], "quotes": [], "source_health": {}}), encoding="utf-8")
    (site_data / "research-report.json").write_text(json.dumps({"schema_version": "2.0", "generated_at": "2026-08-04T10:00:00+08:00", "snapshot_id": "research-12345678", "sources": [], "candidates": [], "health": {}}), encoding="utf-8")
    (site_data / "event-ledger.json").write_text(json.dumps({"schema_version": 1, "retention_days": 30, "events": {}}), encoding="utf-8")
    return {"market.json": site_data / "market.json", "research-report.json": site_data / "research-report.json", "event-ledger.json": site_data / "event-ledger.json"}


def test_creator_artifact_is_published_with_manifest_lineage(tmp_path):
    result = build_release_manifest(
        root=tmp_path,
        artifacts=_artifacts(tmp_path),
        creator_artifact={
            "schema_version": "1.0",
            "parent_release_id": "wrong",
            "market_snapshot_id": "market-12345678",
            "event_snapshot_id": "event-",
            "insights": [],
            "public_safe": True,
            "release_id": "creator-1",
        },
    )
    assert result["creator_status"] == "unavailable"
    assert result["artifact_paths"]["creator-release.json"] == "data/creator-release.json"
    assert result["artifact_hashes"]["creator-release.json"]
    assert (tmp_path / "site" / "data" / "creator-release.json").exists()


def test_release_gate_loads_creator_artifact_only_when_parent_release_matches(tmp_path):
    result = build_release_manifest(
        root=tmp_path,
        artifacts=_artifacts(tmp_path),
        creator_artifact={
            "schema_version": "1.0",
            "parent_release_id": "placeholder",
            "market_snapshot_id": "market-12345678",
            "event_snapshot_id": "event-",
            "insights": [],
            "public_safe": True,
            "release_id": "creator-1",
        },
    )
    # The fixture intentionally has an invalid creator parent, so the core
    # release remains readable but the optional artifact must fail closed.
    path = tmp_path / "site" / "data" / "release-manifest.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    loaded, errors = _load_release_artifacts(result, site_root=tmp_path / "site")
    assert "creator-release.json" in loaded
    assert any("parent release mismatch" in error for error in errors)


def test_manifest_can_build_creator_artifact_from_sanitized_records(tmp_path):
    result = build_release_manifest(
        root=tmp_path,
        artifacts=_artifacts(tmp_path),
        creator_records=[{
            "content_origin": "haojiao",
            "episode_key": "episode-1",
            "episode_title": "Public creator observation",
            "claims": ["A public claim"],
            "opinions": ["A clearly attributed opinion"],
            "verification_state": "unverified",
            "public_safe": True,
        }],
    )
    assert result["creator_status"] == "ready"
    assert result["creator_release_id"].startswith("creator-")
    creator = json.loads((tmp_path / "site" / "data" / "creator-release.json").read_text(encoding="utf-8"))
    assert creator["parent_release_id"] == result["release_id"]
    assert creator["market_snapshot_id"] == result["market_snapshot_id"]
    assert creator["event_snapshot_id"] == result["event_snapshot_id"]
    loaded, errors = _load_release_artifacts(result, site_root=tmp_path / "site")
    assert errors == []
    assert loaded["creator-release.json"]["status"] == "ready"


def test_manifest_cli_accepts_creator_records_file(tmp_path, monkeypatch):
    _artifacts(tmp_path)
    records_path = tmp_path / "creator-records.json"
    records_path.write_text(json.dumps({"records": [{
        "content_origin": "gooaye",
        "episode_key": "episode-cli",
        "episode_title": "CLI creator observation",
        "claims": ["A public claim"],
        "verification_state": "unverified",
        "public_safe": True,
    }]}), encoding="utf-8")
    output = tmp_path / "site" / "data" / "release-manifest-cli.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "release_manifest",
            "--root",
            str(tmp_path),
            "--output",
            str(output),
            "--creator-records",
            str(records_path),
        ],
    )
    assert release_manifest.main() == 0
    assert json.loads(output.read_text(encoding="utf-8"))["creator_status"] == "ready"
