from src.briefing_cards import build_briefing_snapshot


def test_briefing_forwards_complete_macro_observation_to_surprise_engine():
    briefing = build_briefing_snapshot({
        "indices": [], "quotes": [], "macro_quotes": [], "events": {"items": []},
        "macro": {
            "expected": 3.0, "actual": 3.4, "previous": 2.9,
            "historical_std": 0.2, "release_time": "2026-08-09T08:30:00+08:00",
            "source_url": "https://official.example/macro",
        },
    })
    surprise = briefing["intelligence"]["macro_surprise"]
    assert surprise["status"] == "above_expectation"
    assert surprise["surprise"] == 0.4
    assert surprise["market_direction"] == "not_determined"
    assert briefing["paper_portfolio"]["tracking"]["status"] == "pending"
    assert briefing["event_feedback"]["enabled"] is True
    assert briefing["event_feedback"]["policy_update_allowed"] is False


def test_incomplete_macro_summary_is_explicitly_insufficient():
    briefing = build_briefing_snapshot({
        "indices": [], "quotes": [], "macro_quotes": [], "events": {"items": []},
        "macro": {"items": []},
    })
    assert briefing["intelligence"]["macro_surprise"]["status"] == "insufficient_evidence"


def test_missing_historical_std_does_not_invent_surprise_z():
    briefing = build_briefing_snapshot({
        "indices": [], "quotes": [], "macro_quotes": [], "events": {"items": []},
        "macro": {"expected": 3.0, "actual": 3.4},
    })
    surprise = briefing["intelligence"]["macro_surprise"]
    assert surprise["status"] == "above_expectation"
    assert surprise["surprise"] == 0.4
    assert surprise["surprise_z"] is None


def test_briefing_forwards_external_observations_to_conservative_risk_engine():
    briefing = build_briefing_snapshot({
        "indices": [], "quotes": [], "macro_quotes": [], "events": {"items": []},
        "external_observations": [{
            "event_type": "energy",
            "title": "Iran oil supply risk",
            "summary": "discovery signal",
            "source": "financialjuice",
            "source_tier": "discovery",
            "source_url": "https://discovery.example/event",
        }],
    })
    risk = briefing["intelligence"]["external_event_risk"]
    assert risk["status"] == "pending"
    assert risk["score"]["prstk_risk_level"] == "R2"
    assert risk["unified_events"][0]["lifecycle_state"] == "pending_confirmation"
    assert risk["unified_events"][0]["notification"]["allowed"] is False
    assert risk["pending_reasons"]


def test_briefing_uses_financialjuice_subset_when_release_contains_creator_rows():
    briefing = build_briefing_snapshot({
        "indices": [], "quotes": [], "macro_quotes": [], "events": {"items": []},
        "external_observations": [
            {"event_type": "energy", "title": "FJ oil risk", "source": "financialjuice"},
            {"event_type": "technology", "title": "Creator view", "source": "jenny"},
        ],
        "financialjuice_observations": [
            {"event_type": "energy", "title": "FJ oil risk", "source": "financialjuice"},
        ],
    })
    risk = briefing["intelligence"]["external_event_risk"]
    assert risk["cluster"]["observations"][0]["title"] == "FJ oil risk"
    assert all(item.get("title") != "Creator view" for item in risk["cluster"]["observations"])
