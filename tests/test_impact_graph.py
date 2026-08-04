import pytest

from src.impact_graph import ImpactEdge, MarketImpactGraph, default_market_graph


def test_graph_keeps_evidence_and_finds_short_path():
    graph = default_market_graph()
    path = graph.path("export_control", "SOX")
    assert len(path) == 2
    assert all(edge.evidence for edge in path)
    assert graph.as_dict()["edge_count"] >= 5


def test_event_paths_can_filter_affected_nodes():
    rows = default_market_graph().event_paths({"affected_instruments": ["WTI"]})
    assert rows
    assert all(row["source"] in {"WTI", "oil_supply_disruption"} for row in rows)


def test_invalid_edge_is_rejected():
    with pytest.raises(ValueError):
        MarketImpactGraph([ImpactEdge("x", "y", "up", 2, (), "", "")])