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


def test_financialjuice_observation_uses_vendor_contract_in_pipeline() -> None:
    context = build_intelligence_context(
        {"event_type": "energy"},
        external_observations=[
            {
                "source": "financialjuice",
                "event_type": "energy",
                "title": "Oil supply",
                "vendor_importance": 10,
                "source_url": "https://financialjuice.com/item/1",
            }
        ],
    )
    contract = context["external_event_risk"]["financialjuice"]
    assert contract["vendor_importance"] == 10
    assert contract["prstk_risk"]["prstk_risk_level"] == "R2"
    assert "等待官方核對" in contract["pending_reasons"]


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


def test_pipeline_keeps_all_financialjuice_items_and_clusters() -> None:
    context = build_intelligence_context(
        {"event_type": "energy"},
        external_observations=[{
            "source": "financialjuice",
            "items": [
                {"item_id": "fj-item-1", "event_cluster_key": "fj-cluster-1", "original_headline": "Oil supply", "event_type": "energy", "vendor_importance": 8},
                {"item_id": "fj-item-2", "event_cluster_key": "fj-cluster-2", "original_headline": "Chip controls", "event_type": "policy", "vendor_importance": 7},
            ],
        }],
    )
    assert len(context["external_event_risk"]["unified_events"]) == 2
    assert {row["item_id"] for row in context["external_event_risk"]["financialjuice_items"]} == {"fj-item-1", "fj-item-2"}
    assert len(context["external_event_risk"]["clusters"]) == 2


def test_direct_compound_input_does_not_propagate_transport_or_raw_fields() -> None:
    context = build_intelligence_context(
        {"event_type": "energy"},
        external_observations=[{
            "parse_status": "parsed",
            "content_origin": "financialjuice",
            "message_id": "private-envelope-id",
            "items": [{
                "item_id": "fj-item-safe", "event_cluster_key": "fj-cluster-safe",
                "candidate_event_type": "energy", "original_headline": "Oil supply risk",
                "body": "private raw mail must not cross this boundary",
            }],
        }],
    )
    observations = context["external_event_risk"]["cluster"]["observations"]
    assert observations
    assert all("message_id" not in item and "body" not in item for item in observations)
