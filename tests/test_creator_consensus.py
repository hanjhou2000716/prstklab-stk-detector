from src.creator_consensus import build_creator_consensus


def test_consensus_needs_two_independent_sources():
    result = build_creator_consensus([{"content_origin": "haojiao", "topics": ["oil"]}])
    assert result["consensus_state"] == "insufficient_sources"
    assert result["is_investment_signal"] is False


def test_consensus_does_not_infer_from_opinion_prose():
    result = build_creator_consensus([
        {"creator_id": "a", "topics": ["oil"], "creator_market_view": "risk is rising"},
        {"creator_id": "b", "topics": ["oil"], "creator_market_view": "risk is rising"},
    ])
    assert result["consensus_state"] == "pending_verification"


def test_consensus_explicit_aligned_stance_is_descriptive_only():
    result = build_creator_consensus([
        {"creator_id": "a", "topics": ["oil"], "consensus_stance": "risk_off"},
        {"creator_id": "b", "topics": ["oil"], "consensus_stance": "risk_off"},
    ])
    assert result["consensus_state"] == "aligned"
    assert result["consensus_topics"][0]["evidence_state"] == "comparable"
    assert result["is_investment_signal"] is False
