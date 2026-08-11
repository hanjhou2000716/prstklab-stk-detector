from src.intelligence_pipeline import build_intelligence_context


def test_intelligence_pipeline_is_conditional_without_market_sync():
    result = build_intelligence_context({"title": "戰爭與原油供應風險", "source_url": "https://official.test"}, [])
    assert result["evidence_status"] == "insufficient_evidence"
    assert result["advice_gate"] == "observation_only"

def test_intelligence_pipeline_marks_sync_from_fresh_observation():
    result = build_intelligence_context({"title": "Fed interest rate policy", "source_url": "https://official.test"}, [{"ticker": "NASDAQ", "price": 100, "change_percent": -2}])
    assert "market_impact_graph" in result
    assert "disclaimer" in result
    reaction = result["macro_surprise"]["market_reaction"]
    assert reaction["status"] == "observed_only"
    assert reaction["direction_confirmed"] is False
    assert reaction["quotes"][0]["ticker"] == "NASDAQ"


def test_macro_reaction_is_explicitly_unavailable_without_quotes():
    result = build_intelligence_context(
        {"title": "CPI release", "source_url": "https://official.test"},
        [],
        macro={"expected": 2.0, "actual": 2.1},
    )
    reaction = result["macro_surprise"]["market_reaction"]
    assert reaction["status"] == "not_available"
    assert reaction["direction_confirmed"] is False


def test_intelligence_pipeline_publishes_risk_context_without_unlocking_advice():
    result = build_intelligence_context(
        {"title": "Oil supply risk", "source_url": "https://official.test"},
        [{"ticker": "NASDAQ", "price": 100, "change_percent": -3}],
        regime_factors={"trend": -1.0, "volatility": -2.0},
        stress_exposures={"NASDAQ": 1.0},
        advice_context={"general_research": True},
    )
    assert result["market_regime"]["regime"] == "Stress"
    assert result["stress_scenarios"][0]["non_predictive"] is True
    assert result["advice_gate"] == "observation_only"
    assert result["explainability"] is None
