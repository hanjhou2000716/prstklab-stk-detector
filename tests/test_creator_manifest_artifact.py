import json
import sys
from datetime import UTC, datetime, timedelta

from src import release_manifest
from src.release_gate import _load_release_artifacts
from src.release_manifest import build_release_manifest


def _artifacts(tmp_path):
    site_data = tmp_path / "site" / "data"
    site_data.mkdir(parents=True)
    (site_data / "market.json").write_text(json.dumps({"generated_at": "2026-08-04T10:00:00+08:00", "snapshot_id": "market-12345678", "indices": [], "quotes": [], "source_health": {}}), encoding="utf-8")
    (site_data / "research-report.json").write_text(json.dumps({"schema_version": "2.0", "generated_at": "2026-08-04T10:00:00+08:00", "snapshot_id": "research-12345678", "sources": [], "candidates": [], "health": {}}), encoding="utf-8")
    (site_data / "event-ledger.json").write_text(json.dumps({"schema_version": 1, "retention_days": 30, "events": {}}), encoding="utf-8")
    return {"market.json": site_data / "market.json", "research-report.json": site_data / "research-report.json", "event-ledger.json": site_data / "event-ledger.json"}


def _enable_test_creator_lane(monkeypatch):
    """Exercise artifact mechanics with an explicit synthetic active lane."""
    monkeypatch.setattr(
        "src.creator_provider_registry.creator_ids",
        lambda *, enabled_only=False: ("haojiao", "jenny", "gooaye"),
    )


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


def test_manifest_can_build_creator_artifact_from_sanitized_records(tmp_path, monkeypatch):
    _enable_test_creator_lane(monkeypatch)
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


def test_manifest_drops_retired_creator_records_before_public_release_hashing(tmp_path):
    result = build_release_manifest(
        root=tmp_path,
        artifacts=_artifacts(tmp_path),
        creator_records=[
            {"content_origin": "haojiao", "episode_key": "retired-hao", "public_safe": True},
            {"content_origin": "jenny", "episode_key": "retired-jenny", "public_safe": True},
            {"content_origin": "gooaye", "episode_key": "retired-gooaye", "public_safe": True},
        ],
    )
    assert result["creator_status"] == "not_available"
    assert result["creator_public_status"] == "not_available"
    assert "creator-release.json" not in result["artifact_paths"]
    assert "creator-insights.json" not in result["artifact_paths"]
    assert not (tmp_path / "site" / "data" / "creator-release.json").exists()
    assert not (tmp_path / "site" / "data" / "creator-insights.json").exists()


def test_manifest_creator_correlation_uses_release_bound_snapshots(tmp_path, monkeypatch):
    _enable_test_creator_lane(monkeypatch)
    artifacts = _artifacts(tmp_path)
    # Keep the fixture inside the correlation freshness window so this test
    # remains valid as the calendar advances; the production stale gate stays
    # strict at 36 hours.
    fixture_time = (datetime.now(UTC) - timedelta(hours=1)).replace(microsecond=0).isoformat()
    market_path = artifacts["market.json"]
    market = json.loads(market_path.read_text(encoding="utf-8"))
    market.update(
        {
            "generated_at": fixture_time,
            "quotes": [{"ticker": "2330.TW", "symbol": "2330.TW"}],
        }
    )
    market_path.write_text(json.dumps(market), encoding="utf-8")
    research_path = artifacts["research-report.json"]
    research = json.loads(research_path.read_text(encoding="utf-8"))
    research["generated_at"] = fixture_time
    research_path.write_text(json.dumps(research), encoding="utf-8")
    result = build_release_manifest(
        root=tmp_path,
        artifacts=artifacts,
        creator_records=[
            {
                "content_origin": "haojiao",
                "episode_key": "episode-correlated",
                "episode_title": "Public market observation",
                "published_at": "2026-08-21T03:00:00+00:00",
                "tickers": ["2330.TW"],
                "claims": ["safe claim"],
                "verification_state": "unverified",
                "public_safe": True,
            }
        ],
    )
    public = json.loads(
        (tmp_path / "site" / "data" / "creator-insights.json").read_text(encoding="utf-8")
    )
    assert result["creator_status"] == "ready"
    episode = public["creators"]["haojiao"]["episodes"][0]
    correlation = episode["prstk_correlation"]
    assert correlation["correlation_state"] == "aligned"
    assert correlation["matched_tickers"] == ["2330.tw"]
    assert correlation["market_snapshot_id"] == result["market_snapshot_id"]


def test_manifest_binds_morning_batch_to_market_snapshot_when_requested(tmp_path, monkeypatch):
    _enable_test_creator_lane(monkeypatch)
    artifacts = _artifacts(tmp_path)
    result = build_release_manifest(
        root=tmp_path,
        artifacts=artifacts,
        creator_records=[{
            "creator_id": "haojiao",
            "content_origin": "haojiao",
            "episode_key": "episode-morning",
            "episode_title": "Morning public creator observation",
            # The release snapshot is 10:00 Taipei (02:00 UTC); keep the
            # fixture point-in-time valid by publishing before that boundary
            # rather than allowing a future row into the batch.
            "published_at": "2026-08-04T09:30:00+08:00",
            "claims": ["safe claim"],
            "verification_state": "unverified",
            "public_safe": True,
        }],
        creator_morning_batch=True,
    )
    creator = json.loads((tmp_path / "site" / "data" / "creator-release.json").read_text(encoding="utf-8"))
    batch = creator.get("morning_batch")
    assert result["creator_status"] == "ready"
    assert isinstance(batch, dict)
    assert batch["batch_date"] == "2026-08-04"
    assert batch["as_of"].endswith("02:00:00+00:00")
    assert batch["received_count"] == 0
    assert batch["expected_count"] == 0
    assert batch["records"] == []


def test_manifest_also_publishes_bounded_creator_insights_artifact(tmp_path, monkeypatch):
    _enable_test_creator_lane(monkeypatch)
    result = build_release_manifest(
        root=tmp_path,
        artifacts=_artifacts(tmp_path),
        creator_records=[{
            "content_origin": "gooaye",
            "episode_key": "episode-public",
            "episode_title": "Public episode",
            "claims": ["safe claim"],
            "verification_state": "unverified",
            "public_safe": True,
        }],
    )
    assert result["creator_public_status"] == "ready"
    assert result["artifact_paths"]["creator-insights.json"] == "data/creator-insights.json"
    public_path = tmp_path / "site" / "data" / "creator-insights.json"
    public = json.loads(public_path.read_text(encoding="utf-8"))
    assert public["parent_release_id"] == result["release_id"]
    assert public["research_snapshot_id"] == result["research_snapshot_id"]
    assert result["artifact_hashes"]["creator-insights.json"]
    loaded, errors = _load_release_artifacts(result, site_root=tmp_path / "site")
    assert errors == []
    assert loaded["creator-insights.json"]["status"] == "ready"


def test_invalid_public_creator_artifact_does_not_block_core_release(tmp_path):
    result = build_release_manifest(
        root=tmp_path,
        artifacts=_artifacts(tmp_path),
        creator_public_artifact={
            "schema_version": "1.0",
            "status": "ready",
            "parent_release_id": "wrong-parent",
            "market_snapshot_id": "wrong-market",
            "research_snapshot_id": "wrong-research",
            "event_snapshot_id": "wrong-event",
            "snapshot_id": "creator-snapshot",
            "insights": [],
            "public_safe": True,
        },
    )
    assert result["status"] == "ready"
    assert result["creator_public_status"] == "unavailable"
    assert result["creator_public_validation_errors"]
    _, errors = _load_release_artifacts(result, site_root=tmp_path / "site")
    assert errors == []


def test_creator_input_changes_release_identity(tmp_path, monkeypatch):
    _enable_test_creator_lane(monkeypatch)
    artifacts = _artifacts(tmp_path)
    first = build_release_manifest(
        root=tmp_path,
        artifacts=artifacts,
        creator_records=[{"content_origin": "haojiao", "episode_key": "one", "public_safe": True}],
    )
    second = build_release_manifest(
        root=tmp_path,
        artifacts=artifacts,
        creator_records=[{"content_origin": "haojiao", "episode_key": "two", "public_safe": True}],
    )
    assert first["creator_input_hash"] != second["creator_input_hash"]
    assert first["release_id"] != second["release_id"]


def test_derived_creator_timestamps_do_not_change_release_identity(tmp_path):
    artifacts = _artifacts(tmp_path)
    first_artifact = {
        "schema_version": "1.0",
        "parent_release_id": "wrong",
        "market_snapshot_id": "market-12345678",
        "event_snapshot_id": "event-",
        "generated_at": datetime.now(UTC).isoformat(),
        "insights": [],
        "public_safe": True,
        "release_id": "creator-1",
        "status": "unavailable",
        "validation_errors": ["placeholder"],
    }
    first = build_release_manifest(root=tmp_path, artifacts=artifacts, creator_artifact=first_artifact)
    second_artifact = dict(first_artifact)
    second_artifact["generated_at"] = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    second_artifact["validation_errors"] = ["different-placeholder"]
    second = build_release_manifest(root=tmp_path, artifacts=artifacts, creator_artifact=second_artifact)
    assert first["creator_input_hash"] == second["creator_input_hash"]
    assert first["release_id"] == second["release_id"]


def test_manifest_cli_accepts_creator_records_file(tmp_path, monkeypatch):
    _enable_test_creator_lane(monkeypatch)
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


def test_manifest_cli_rejects_creator_records_inside_public_site(tmp_path, monkeypatch):
    _artifacts(tmp_path)
    records_path = tmp_path / "site" / "data" / "creator-records.json"
    records_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "release_manifest",
            "--root",
            str(tmp_path),
            "--creator-records",
            str(records_path),
        ],
    )
    try:
        release_manifest.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("public creator records path should be rejected")
