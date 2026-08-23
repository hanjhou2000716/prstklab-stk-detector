from datetime import UTC, datetime

from src.creator_intelligence_pipeline import build_creator_intelligence_release
from src.creator_morning_batch import build_creator_morning_batch

AS_OF = datetime(2026, 8, 14, 3, 0, tzinfo=UTC)  # 11:00 Asia/Taipei


def _record(creator: str, episode: str, published: str, received: str | None = None) -> dict:
    return {
        "creator_id": creator,
        "content_origin": creator,
        "episode_key": episode,
        "episode_title": episode,
        "published_at": published,
        "received_at": received or published,
        "parse_status": "parsed",
        "public_safe": True,
    }


def test_morning_batch_selects_latest_per_creator_and_is_idempotent() -> None:
    records = [
        _record("haojiao", "old", "2026-08-14T01:00:00Z"),
        _record("haojiao", "latest", "2026-08-14T02:00:00Z"),
        _record("jenny", "j-1", "2026-08-14T02:20:00Z"),
    ]
    first = build_creator_morning_batch(records, as_of=AS_OF, expected_creators=("haojiao", "jenny"))
    second = build_creator_morning_batch(list(reversed(records)), as_of=AS_OF, expected_creators=("haojiao", "jenny"))
    assert first["state"] == "complete"
    assert [item["episode_key"] for item in first["records"]] == ["latest", "j-1"]
    assert first["idempotency_key"] == second["idempotency_key"]
    assert first["batch_key"] == second["batch_key"]


def test_default_morning_lane_excludes_optional_creator() -> None:
    result = build_creator_morning_batch(
        [
            _record("haojiao", "h-1", "2026-08-14T02:00:00Z"),
            _record("jenny", "j-1", "2026-08-14T02:05:00Z"),
            _record("gooaye", "g-1", "2026-08-14T02:10:00Z"),
        ],
        as_of=AS_OF,
    )
    assert result["state"] == "complete"
    assert result["expected_count"] == 2
    assert {item["creator_id"] for item in result["records"]} == {"haojiao", "jenny"}


def test_partial_batch_exposes_missing_creator_without_inventing_content() -> None:
    result = build_creator_morning_batch(
        [_record("haojiao", "h-1", "2026-08-14T02:00:00Z")],
        as_of=AS_OF,
        expected_creators=("haojiao", "jenny"),
    )
    assert result["state"] == "partial"
    assert result["expected_count"] == 2
    assert result["received_count"] == 1
    assert result["missing_creators"] == ["jenny"]


def test_late_arrival_is_kept_and_previous_day_is_rejected() -> None:
    result = build_creator_morning_batch(
        [
            _record("haojiao", "late", "2026-08-14T02:00:00Z", "2026-08-14T03:00:00Z"),
            _record("jenny", "yesterday", "2026-08-13T02:00:00Z"),
        ],
        as_of=AS_OF,
        expected_creators=("haojiao", "jenny"),
    )
    assert result["state"] == "partial"
    assert result["late_arrivals"] == ["haojiao"]
    assert result["missing_creators"] == ["jenny"]
    assert result["rejected_count"] == 1


def test_no_content_is_distinct_from_parse_failure() -> None:
    result = build_creator_morning_batch(
        [_record("haojiao", "bad", "2026-08-14T02:00:00Z") | {"parse_status": "unsupported_template"}],
        as_of=AS_OF,
        expected_creators=("haojiao",),
    )
    assert result["state"] == "no_new_content"
    assert result["rejected_count"] == 1


def test_morning_batch_rejects_future_rows_relative_to_snapshot_boundary() -> None:
    result = build_creator_morning_batch(
        [_record("haojiao", "future", "2026-08-14T04:00:00Z")],
        as_of=AS_OF,
        expected_creators=("haojiao",),
    )
    assert result["state"] == "no_new_content"
    assert result["missing_creators"] == ["haojiao"]
    assert result["rejected_count"] == 1


def test_morning_batch_is_bound_into_creator_release_hash() -> None:
    parent = {
        "release_id": "release-parent",
        "market_snapshot_id": "market-1",
        "event_snapshot_id": "event-1",
    }
    record = _record("haojiao", "h-1", "2026-08-14T02:00:00Z")
    result = build_creator_intelligence_release([record], parent_manifest=parent, batch_as_of=AS_OF)
    artifact = result["artifact"]
    assert artifact["morning_batch"]["state"] == "partial"
    assert artifact["morning_batch"]["batch_key"].startswith("creator-morning:2026-08-14:")
    assert artifact["artifact_hash"]
