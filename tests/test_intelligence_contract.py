from src.artifact_contract import validate_market
from src.intelligence_contract import validate_intelligence
from src.intelligence_pipeline import build_intelligence_context


def test_intelligence_contract_accepts_conditional_graph_without_sync():
    result = build_intelligence_context({"title": "Iran oil supply risk", "source_url": "https://official.test"}, [])
    assert validate_intelligence(result) == []
    assert result["evidence_status"] == "insufficient_evidence"


def test_intelligence_contract_rejects_confirmed_without_market_evidence():
    result = build_intelligence_context({"title": "Fed policy", "source_url": "https://official.test"}, [])
    result["market_sync_confirmed"] = True
    result["evidence_status"] = "confirmed"
    assert "synchronized graph path" in " ".join(validate_intelligence(result))


def test_intelligence_contract_rejects_high_confidence_path_without_sync():
    result = build_intelligence_context({"title": "Iran war oil risk", "source_url": "https://official.test"}, [])
    result["market_impact_graph"]["paths"][0]["confidence"] = 0.9
    errors = validate_intelligence(result)
    assert "high confidence requires synchronized market evidence" in " ".join(errors)


def test_market_contract_validates_embedded_intelligence():
    intelligence = build_intelligence_context({"title": "Briefing", "source_url": "https://official.test"}, [])
    market = {
        "generated_at": "2026-08-11T00:00:00+00:00",
        "snapshot_id": "snapshot-12345678",
        "indices": [],
        "quotes": [],
        "source_health": {},
        "briefing": {"intelligence": intelligence},
    }
    assert validate_market(market) == []


def test_intelligence_contract_rejects_unsuppressed_event_without_notification_id():
    intelligence = build_intelligence_context(
        {"title": "Iran oil supply risk", "source_url": "https://official.test"},
        external_observations=[
            {"source": "reuters", "event_type": "energy", "title": "Oil supply"}
        ],
    )
    intelligence["external_event_risk"]["unified_events"][0]["notification_id"] = None
    errors = validate_intelligence(intelligence)
    assert "notification_id is required" in " ".join(errors)


def test_intelligence_contract_allows_suppressed_event_without_notification_id():
    intelligence = build_intelligence_context(
        {"title": "Iran oil supply risk", "source_url": "https://official.test"},
        external_observations=[
            {"parse_status": "compound_unresolved", "message_id": "msg-1"}
        ],
    )
    assert validate_intelligence(intelligence) == []

