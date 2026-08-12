from src.event_timeline import build_timeline


def test_timeline_filters_risk_and_source_without_breaking_cluster_key() -> None:
    events = [
        {"event_cluster_key": "e1", "market": "global", "category": "conflict", "crosscheck_status": "pending", "risk_level": "R2", "source_tier": "discovery", "published_at": "2026-08-12T01:00:00Z"},
        {"event_cluster_key": "e1", "market": "global", "category": "conflict", "crosscheck_status": "official_confirmed", "risk_level": "R4", "source_tier": "official", "published_at": "2026-08-12T02:00:00Z"},
    ]
    rows = build_timeline(events, risk_level="R4", source_tier="official")
    assert len(rows) == 1
    assert rows[0]["event_cluster_key"] == "e1"
