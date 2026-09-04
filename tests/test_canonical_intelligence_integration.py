"""Regression tests for the single Creator/FJ/News evidence architecture."""

from src.creator_intelligence_pipeline import build_creator_intelligence_release
from src.external_event_pipeline import build_external_event
from src.news_intelligence import normalize_news_story, provider_for_url


def test_corroboration_providers_are_known_but_not_official_feeds():
    reuters = provider_for_url("https://www.reuters.com/world/middle-east/example")
    gdelt = provider_for_url("https://api.gdeltproject.org/api/v2/doc/doc")
    assert reuters["provider_id"] == "reuters"
    assert gdelt["provider_id"] == "gdelt"
    assert reuters["authority_tier"] == "trusted_media"
    assert gdelt["authority_tier"] == "discovery"
    assert reuters["enabled"] is False
    assert gdelt["enabled"] is False


def test_news_and_live_event_use_the_same_classifier_input_boundary():
    record = {
        "title": "Talks on Iran oil shipping risk",
        "summary": "Officials begin negotiations over Hormuz supply.",
        "what_happened": "Talks resume while officials seek confirmation.",
        "impact": "Oil supply uncertainty",
        "market_impact": "WTI +5.2%",
        "related_quotes": {"WTI": {"change_percent": 5.2}},
    }
    story = normalize_news_story(
        {**record, "url": "https://www.reuters.com/world/middle-east/example"},
        "global",
    )
    live = build_external_event(
        {**record, "source": "reuters", "event_type": "energy", "market_evidence": [{"symbol": "WTI", "change_pct": 5.2}]},
    )
    assert story["public_safe"] is True
    assert story["event_classification"]["category"] == live["classification"]["category"]
    assert story["event_classification"]["matched_terms"] == live["classification"]["matched_terms"]
    assert {"summary", "what_happened", "impact", "market_impact", "related_quotes"}.issubset(
        story["event_classification"]["input_fields"]
    )
    assert live["notification"]["allowed"] is False


def test_creator_editorial_lane_cannot_become_event_evidence_or_signal():
    creator = build_creator_intelligence_release(
        [{
            "content_origin": "haojiao",
            "episode_key": "creator-episode-1",
            "episode_title": "Morning market view",
            "topics": ["oil", "semiconductor"],
            "creator_market_view": "Observe supply risk.",
            "verification_state": "unverified",
            "public_safe": True,
        }],
        parent_manifest={
            "release_id": "release-canonical-1",
            "market_snapshot_id": "market-canonical-1",
            "event_snapshot_id": "event-canonical-1",
        },
    )
    assert creator["artifact"]["status"] == "ready"
    assert creator["artifact"]["creator_consensus"]["is_investment_signal"] is False
    assert creator["accepted_count"] == 0
    assert creator["dropped_reasons"] == ["0:retired_source_suppressed"]
    assert creator["artifact"]["insights"] == []
