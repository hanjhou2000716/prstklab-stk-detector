from src.event_alerts import _impact_confirmation
from src.market_impact_graph import build_market_impact_graph


def test_market_sync_requires_fresh_material_move_and_time_alignment():
    related = [{"ticker": "NASDAQ", "change_percent": 1.2, "quote_time": "2026-08-14T10:10:00+00:00"}]
    confirmed = _impact_confirmation({}, related, "2026-08-14T10:00:00+00:00")
    assert confirmed["confirmed"] is True
    assert confirmed["markets"] == ["NASDAQ"]

    stale = _impact_confirmation(
        {}, [{**related[0], "quote_time": "2026-08-14T12:00:00+00:00"}], "2026-08-14T10:00:00+00:00"
    )
    assert stale["confirmed"] is False


def test_oil_requires_five_percent_move_and_timestamps():
    event_time = "2026-08-14T10:00:00+00:00"
    assert _impact_confirmation(
        {}, [{"ticker": "WTI", "change_percent": 5.1, "quote_time": "2026-08-14T10:05:00+00:00"}], event_time
    )["confirmed"] is True
    assert _impact_confirmation({}, [{"ticker": "WTI", "change_percent": 5.1}], event_time)["confirmed"] is False
    assert _impact_confirmation(
        {}, [{"ticker": "WTI", "change_percent": 4.99, "quote_time": "2026-08-14T10:05:00+00:00"}], event_time
    )["confirmed"] is False


def test_impact_graph_does_not_promote_conditional_path_without_sync():
    graph = build_market_impact_graph({"title": "Iran conflict may disrupt oil shipping"})
    path = graph["paths"][0]
    assert path["market_sync"] is False
    assert path["confidence"] < 0.8
    assert all(edge["direction"] == "conditional_risk" for edge in path["edges"])
