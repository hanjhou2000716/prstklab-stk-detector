from src.briefing_cards import build_briefing_snapshot


def test_briefing_binds_sanitized_creator_insights_to_parent_release():
    snapshot = {
        "release_id": "release-briefing",
        "market_snapshot_id": "market-briefing",
        "event_snapshot_id": "event-briefing",
        "indices": [{"ticker": "TAIEX", "price": 100, "change_percent": 0.2}],
        "quotes": [],
        "macro_quotes": [],
        "events": {"items": [{"title": "Market briefing", "summary": "Observed data", "market_impact": "Observed only"}]},
        "creator_insights": [{
            "content_origin": "haojiao",
            "episode_key": "briefing-creator-1",
            "public_safe": True,
            "verification_state": "partially_verified",
        }],
    }
    briefing = build_briefing_snapshot(snapshot, "midday")
    assert briefing["creator_release"]["status"] == "ready"
    assert briefing["creator_release"]["parent_release_id"] == "release-briefing"
