from src.intelligence_pipeline import build_intelligence_context


def test_intelligence_pipeline_is_conditional_without_market_sync():
    result = build_intelligence_context({"title": "戰爭與原油供應風險", "source_url": "https://official.test"}, [])
    assert result["evidence_status"] == "insufficient_evidence"
    assert result["advice_gate"] == "observation_only"

def test_intelligence_pipeline_marks_sync_from_fresh_observation():
    result = build_intelligence_context({"title": "Fed interest rate policy", "source_url": "https://official.test"}, [{"ticker": "NASDAQ", "price": 100, "change_percent": -2}])
    assert "market_impact_graph" in result
    assert "disclaimer" in result
