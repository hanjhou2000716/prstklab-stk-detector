from src.external_event_risk import (
    cluster_external_events,
    event_cluster_key,
    event_fingerprint,
    notification_decision,
    score_prstk_risk,
)


def test_same_event_from_two_sources_forms_one_cluster() -> None:
    events = cluster_external_events([
        {"source": "financialjuice", "event_type": "conflict", "actor": "Trump", "action": "talks", "location": "Iran", "published_at": "2026-08-12T01:00:00Z"},
        {"source": "reuters", "event_type": "conflict", "actor": "Trump", "action": "talks", "location": "Iran", "published_at": "2026-08-12T01:30:00Z"},
    ])
    assert len(events) == 1
    assert events[0]["cross_source_count"] == 2
    assert "financialjuice" in events[0]["evidence_sources"]


def test_creator_is_not_event_evidence() -> None:
    clusters = cluster_external_events([{"source": "gooaye", "event_type": "conflict", "actor": "Trump", "location": "Iran"}])
    assert clusters[0]["cross_source_count"] == 0
    assert clusters[0]["editorial_sources"] == ["gooaye"]


def test_vendor_importance_cannot_become_critical_alone() -> None:
    cluster = {"event_type": "conflict", "cross_source_count": 1, "editorial_sources": [], "evidence_sources": ["financialjuice"]}
    result = score_prstk_risk(cluster, vendor_importance=10)
    assert result["prstk_risk_level"] == "R2"
    assert result["high_priority"] is False


def test_r4_requires_official_and_market_sync() -> None:
    cluster = {"event_type": "black_swan", "cross_source_count": 2, "editorial_sources": [], "evidence_sources": ["gdelt", "reuters"]}
    pending = score_prstk_risk(cluster, official_confirmed=True, market_sync_confirmed=False)
    assert pending["prstk_risk_level"] == "R3"
    assert notification_decision(pending)["allowed"] is True
    critical = score_prstk_risk(cluster, official_confirmed=True, market_sync_confirmed=True)
    assert critical["prstk_risk_level"] == "R4"
    assert notification_decision(critical)["allowed"] is True


def test_stale_evidence_cannot_escalate_even_with_confirmation_flags() -> None:
    cluster = {
        "event_type": "black_swan",
        "cross_source_count": 2,
        "editorial_sources": [],
        "evidence_sources": ["official", "reuters"],
        "observations": [{"freshness": "stale"}],
    }
    score = score_prstk_risk(cluster, official_confirmed=True, market_sync_confirmed=True)
    assert score["freshness_blocked"] is True
    assert score["prstk_risk_level"] == "R2"
    decision = notification_decision(score)
    assert decision["allowed"] is False
    assert "stale_or_delayed_evidence_blocked" in decision["reasons"]


def test_quote_delayed_marker_is_inherited_by_cluster() -> None:
    clusters = cluster_external_events([
        {
            "source": "official",
            "event_type": "energy",
            "actor": "supply",
            "action": "disruption",
            "location": "Hormuz",
            "quote_delayed": True,
        }
    ])
    assert clusters[0]["freshness_blocked"] is True
    score = score_prstk_risk(clusters[0], official_confirmed=True, market_sync_confirmed=True)
    assert score["notification_eligible"] is False


def test_cluster_key_is_stable() -> None:
    event = {"event_type": "policy", "actor": "Trump", "action": "tariff", "location": "US", "published_at": "2026-08-12T01:00:00Z"}
    assert event_cluster_key(event) == event_cluster_key(dict(event))


def test_multilingual_aliases_share_identity() -> None:
    traditional = {"event_type": "衝突", "actor": "川普", "action": "談判", "location": "伊朗", "published_at": "2026-08-12T01:00:00Z"}
    english = {"event_type": "conflict", "actor": "Trump", "action": "negotiation", "location": "Iran", "published_at": "2026-08-12T01:00:00Z"}
    assert event_cluster_key(traditional) == event_cluster_key(english)
    assert event_fingerprint(traditional) == {"entity": "trump", "action": "talk", "location": "iran"}
