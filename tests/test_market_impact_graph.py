from src.market_impact_graph import build_market_impact_graph


def test_market_impact_graph_keeps_event_path_conditional_without_sync():
    graph = build_market_impact_graph({
        "title": "Iran conflict may disrupt oil shipping",
        "source_url": "https://example.com/event",
        "published_at": "2026-08-05T01:00:00+00:00",
    })
    assert graph["paths"]
    assert graph["paths"][0]["market_sync"] is False
    assert graph["paths"][0]["confidence"] < 0.8
    assert graph["paths"][0]["invalidation_condition"]


def test_market_impact_graph_uses_only_fresh_market_observations_as_evidence():
    graph = build_market_impact_graph(
        {"title": "Fed interest rate policy", "source_url": "https://example.com/fed"},
        [{"ticker": "NASDAQ", "price": 100, "stale_used": False}, {"ticker": "SOX", "price": 50, "stale_used": True}],
    )
    path = graph["paths"][0]
    assert path["market_sync"] is True
    assert path["evidence"][1]["tickers"] == ["NASDAQ"]
