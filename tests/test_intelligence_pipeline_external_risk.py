from src.intelligence_pipeline import build_intelligence_context


def test_pipeline_exposes_pending_external_event_reason() -> None:
    context = build_intelligence_context(
        {"event_type": "conflict", "vendor_importance": 10},
        external_observations=[
            {"source": "financialjuice", "event_type": "conflict", "actor": "Trump", "action": "talks", "location": "Iran", "published_at": "2026-08-12T01:00:00Z"}
        ],
    )
    assert context["external_event_risk"]["status"] == "pending"
    assert context["external_event_risk"]["score"]["prstk_risk_level"] == "R2"
    assert "risk_threshold_not_reached" in context["external_event_risk"]["notification"]["reasons"]


def test_pipeline_allows_confirmed_cross_source_event_but_keeps_advice_gate() -> None:
    context = build_intelligence_context(
        {"event_type": "black_swan", "official_confirmed": True},
        external_observations=[
            {"source": "gdelt", "event_type": "black_swan", "actor": "Trump", "action": "attack", "location": "Iran", "published_at": "2026-08-12T01:00:00Z"},
            {"source": "reuters", "event_type": "black_swan", "actor": "Trump", "action": "attack", "location": "Iran", "published_at": "2026-08-12T01:30:00Z"},
        ],
    )
    assert context["external_event_risk"]["score"]["prstk_risk_level"] == "R3"
    assert context["external_event_risk"]["status"] == "eligible"
    assert context["advice_gate"] == "observation_only"
