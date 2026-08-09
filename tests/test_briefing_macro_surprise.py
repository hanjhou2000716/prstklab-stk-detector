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


def test_incomplete_macro_summary_stays_not_provided():
    briefing = build_briefing_snapshot({
        "indices": [], "quotes": [], "macro_quotes": [], "events": {"items": []},
        "macro": {"items": []},
    })
    assert briefing["intelligence"]["macro_surprise"]["status"] == "not_provided"
