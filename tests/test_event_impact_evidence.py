from src.event_alerts import _detail_event


def test_event_record_carries_conditional_impact_graph_without_fresh_sync():
    event = _detail_event(
        {
            "title": "Iran conflict may disrupt oil shipping",
            "summary": "Public event report",
            "source_url": "https://example.com/event",
            "published_at": "2026-08-08T01:00:00+00:00",
            "source_tier": "discovery",
        },
        [],
    )
    assert event["market_impact_graph"]["paths"]
    assert event["market_sync_confirmed"] is False
    assert event["market_impact_graph"]["paths"][0]["confidence"] < 0.8


def test_event_record_marks_only_relevant_fresh_market_sync():
    event = _detail_event(
        {
            "title": "Fed interest rate policy",
            "source_url": "https://example.com/fed",
            "published_at": "2026-08-08T01:00:00+00:00",
            "source_tier": "official",
        },
        [
            {"ticker": "NASDAQ", "price": 100, "stale_used": False},
            {"ticker": "SOX", "price": 50, "stale_used": True},
        ],
    )
    assert event["market_sync_confirmed"] is True
    evidence = event["market_impact_graph"]["paths"][0]["evidence"]
    assert evidence[1]["tickers"] == ["NASDAQ"]
