import json

from src.refresh_market_data import merge_published_metadata, write_snapshot


def _snapshot(started_at: str, generated_at: str) -> dict:
    return {
        "generated_at": generated_at,
        "scan": {"started_at": started_at},
        "quotes": [],
        "indices": [],
    }


def test_write_snapshot_publishes_metadata_atomically(tmp_path):
    destination = tmp_path / "market.json"
    assert write_snapshot(
        _snapshot("2026-08-04T10:00:00+08:00", "2026-08-04T10:01:00+08:00"),
        destination,
    ) is True
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["snapshot_schema_version"] == "3.0"
    assert len(payload["snapshot_id"]) == 16
    assert payload["snapshot_published_at"]
    assert payload["raw_observation"] == {
        "enabled": False,
        "required": False,
        "recorded": False,
        "state": "disabled",
        "reason": "not_configured",
    }
    assert not list(tmp_path.glob(".*.tmp"))


def test_write_snapshot_records_normalized_artifact_when_store_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("RAW_OBSERVATION_ROOT", str(tmp_path / "raw"))
    destination = tmp_path / "market.json"
    snapshot = _snapshot("2026-08-09T10:00:00+08:00", "2026-08-09T10:01:00+08:00")
    assert write_snapshot(snapshot, destination) is True
    payload = json.loads(destination.read_text(encoding="utf-8"))
    metadata = payload["raw_observation"]
    assert metadata["enabled"] is True
    assert metadata["state"] == "recorded"
    assert metadata["recorded"] is True
    assert len(metadata["observation_id"]) == 32
    assert list((tmp_path / "raw").rglob("*.json"))


def test_write_snapshot_binds_quotes_and_events_to_snapshot(tmp_path):
    destination = tmp_path / "market.json"
    snapshot = _snapshot("2026-08-04T10:00:00+08:00", "2026-08-04T10:01:00+08:00")
    snapshot["quotes"] = [{
        "ticker": "^TWII",
        "name": "TAIEX",
        "price": 43119.75,
        "change_percent": 0.5,
        "quote_time": "2026-08-04T10:00:00+08:00",
        "source_url": "https://mis.twse.com.tw/stock/api/getStockInfo.jsp",
    }]
    snapshot["events"] = {"items": [{
        "kind": "market_signal",
        "title": "TAIEX price signal",
        "instrument": snapshot["quotes"][0],
        "source_trace": {"source_domain": "mis.twse.com.tw"},
    }]}

    assert write_snapshot(snapshot, destination) is True
    payload = json.loads(destination.read_text(encoding="utf-8"))
    quote = payload["quotes"][0]
    event = payload["events"]["items"][0]
    assert event["snapshot_id"] == payload["snapshot_id"]
    assert event["observation_id"] == quote["observation_id"]
    assert event["source_trace"]["snapshot_id"] == payload["snapshot_id"]
    assert event["source_trace"]["observation_id"] == quote["observation_id"]


def test_older_slow_run_cannot_overwrite_newer_snapshot(tmp_path):
    destination = tmp_path / "market.json"
    write_snapshot(
        _snapshot("2026-08-04T10:00:00+08:00", "2026-08-04T10:05:00+08:00"),
        destination,
    )
    before = destination.read_text(encoding="utf-8")
    assert write_snapshot(
        _snapshot("2026-08-04T09:00:00+08:00", "2026-08-04T09:30:00+08:00"),
        destination,
    ) is False
    assert destination.read_text(encoding="utf-8") == before


def test_merge_published_metadata_is_guarded_by_snapshot_id(tmp_path):
    destination = tmp_path / "market.json"
    snapshot = _snapshot("2026-08-04T10:00:00+08:00", "2026-08-04T10:01:00+08:00")
    assert write_snapshot(snapshot, destination) is True
    snapshot_id = snapshot["snapshot_id"]
    assert merge_published_metadata(
        {"trace_id": "brief-test", "observation_id": "obs-test"},
        destination,
        expected_snapshot_id=snapshot_id,
    ) is True
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["briefing"]["trace_id"] == "brief-test"
    assert payload["briefing"]["observation_id"] == "obs-test"
    assert merge_published_metadata(
        {"trace_id": "stale"}, destination, expected_snapshot_id="wrong-id"
    ) is False
    assert json.loads(destination.read_text(encoding="utf-8"))["briefing"]["trace_id"] == "brief-test"
