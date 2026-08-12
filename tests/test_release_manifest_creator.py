import json

from src.release_manifest import build_release_manifest


def _artifacts(tmp_path):
    site_data = tmp_path / "site" / "data"
    site_data.mkdir(parents=True)
    (site_data / "market.json").write_text(json.dumps({"generated_at": "2026-08-04T10:00:00+08:00", "snapshot_id": "market-12345678", "indices": [], "quotes": [], "source_health": {}}), encoding="utf-8")
    (site_data / "research-report.json").write_text(json.dumps({"schema_version": "2.0", "generated_at": "2026-08-04T10:00:00+08:00", "snapshot_id": "research-12345678", "sources": [], "candidates": [], "health": {}}), encoding="utf-8")
    (site_data / "event-ledger.json").write_text(json.dumps({"schema_version": 1, "retention_days": 30, "events": {}}), encoding="utf-8")
    return {"market.json": site_data / "market.json", "research-report.json": site_data / "research-report.json", "event-ledger.json": site_data / "event-ledger.json"}


def test_creator_artifact_is_additive_and_fail_soft(tmp_path):
    artifacts = _artifacts(tmp_path)
    result = build_release_manifest(
        root=tmp_path,
        artifacts=artifacts,
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
    assert result["creator_validation_errors"]
