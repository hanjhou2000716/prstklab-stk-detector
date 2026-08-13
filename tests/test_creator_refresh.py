from src.creator_refresh import refresh_creator_snapshot

PARENT = {
    "status": "ready",
    "release_id": "release-1",
    "market_snapshot_id": "market-1",
    "research_snapshot_id": "research-1",
    "event_snapshot_id": "event-1",
}


def test_creator_refresh_reuses_parent_core_lineage():
    result = refresh_creator_snapshot(
        [{"content_origin": "gooaye", "episode_key": "ep-1", "episode_title": "觀察", "public_safe": True}],
        parent_release=PARENT,
        refreshed_at="2026-08-13T00:00:00Z",
    )
    assert result["status"] == "ready"
    assert result["refresh_mode"] == "creator_only"
    assert result["market_snapshot_id"] == "market-1"
    assert result["artifact"]["parent_release_id"] == "release-1"


def test_creator_refresh_fails_closed_when_parent_is_not_ready():
    result = refresh_creator_snapshot([], parent_release={**PARENT, "status": "invalid"})
    assert result["status"] == "unavailable"
    assert result["source_state"] == "parent_release_unavailable"
    assert result["artifact"] is None


def test_creator_refresh_marks_old_last_success_stale():
    result = refresh_creator_snapshot(
        [],
        parent_release=PARENT,
        refreshed_at="2026-08-13T00:00:00Z",
        last_success_at="2026-08-01T00:00:00Z",
        max_age_days=7,
    )
    assert result["source_state"] == "stale"
    assert result["freshness"] == "stale"
