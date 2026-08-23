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


def test_consensus_uses_latest_valid_episode_per_creator_and_normalizes_aliases():
    result = build_creator_consensus([
        {"creator_id": "a", "episode_key": "a-old", "published_at": "2026-08-10T00:00:00Z", "topics": ["nvidia"], "consensus_stance": "risk_off"},
        {"creator_id": "a", "episode_key": "a-new", "published_at": "2026-08-14T00:00:00Z", "topics": ["輝達"], "consensus_stance": "risk_on"},
        {"creator_id": "b", "episode_key": "b-new", "published_at": "2026-08-14T01:00:00Z", "topics": ["NVDA"], "consensus_stance": "risk_on"},
    ])
    assert result["consensus_state"] == "aligned"
    assert result["contributors"] == ["a", "b"]
    assert result["coverage"] == "2/2"
    assert result["topic_consensus"][0]["topic"] == "NVDA"
    assert result["topic_consensus"][0]["episode_count"] == 2


def test_consensus_keeps_divergent_views_visible():
    result = build_creator_consensus([
        {"creator_id": "a", "episode_key": "a-1", "topics": ["原油"], "consensus_stance": "risk_on"},
        {"creator_id": "b", "episode_key": "b-1", "topics": ["oil"], "consensus_stance": "risk_off"},
    ])
    assert result["consensus_state"] == "mixed"
    assert result["divergent_views"][0]["topic"] == "oil"
    assert result["topic_consensus"][0]["stance"] == "mixed"


def test_consensus_marks_stale_market_evidence_without_turning_it_into_signal():
    result = build_creator_consensus([
        {"creator_id": "a", "episode_key": "a-1", "published_at": "2026-08-14T00:00:00Z", "topics": ["半導體"], "prstk_correlation": {"evidence_alignment": "stale"}},
        {"creator_id": "b", "episode_key": "b-1", "published_at": "2026-08-14T00:10:00Z", "topics": ["semiconductor"], "prstk_correlation": {"evidence_alignment": "aligned"}},
    ])
    assert result["evidence_alignment"] == "stale"
    assert result["is_investment_signal"] is False
    assert "confidence" not in result
