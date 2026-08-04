import json

from src.refresh_market_data import write_snapshot


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
    assert not list(tmp_path.glob(".*.tmp"))


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
