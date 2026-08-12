from src.creator_intelligence_pipeline import build_creator_intelligence_release

PARENT = {"release_id": "release-1", "market_snapshot_id": "market-1", "event_snapshot_id": "event-1"}


def test_pipeline_accepts_sanitized_creator_insight_and_dedupes_episode():
    result = build_creator_intelligence_release(
        [
            {"content_origin": "haojiao", "episode_key": "ep-1", "public_safe": True, "verification_state": "unverified"},
            {"content_origin": "haojiao", "episode_key": "ep-1", "public_safe": True, "verification_state": "unverified"},
        ],
        parent_manifest=PARENT,
    )
    assert result["accepted_count"] == 1
    assert result["dropped_reasons"] == ["1:duplicate_episode"]
    assert result["artifact"]["status"] == "ready"


def test_pipeline_drops_private_or_unknown_records_fail_closed():
    result = build_creator_intelligence_release(
        [
            {"content_origin": "gooaye", "episode_key": "ep-1", "raw_body": "secret"},
            {"content_origin": "unknown", "episode_key": "ep-2"},
        ],
        parent_manifest=PARENT,
    )
    assert result["accepted_count"] == 0
    assert result["source_state"] == "no_creator_insights"
    assert result["artifact"]["status"] == "ready"
