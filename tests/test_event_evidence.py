from src.event_evidence import attach_evidence_state, evidence_state, summarize_evidence


def test_discovery_is_visible_but_waits_for_second_source():
    item = attach_evidence_state({"source_tier": "discovery"})
    assert item["evidence_state"] == "discovery"
    assert item["evidence_reason"] == "等待第二來源"
    assert item["evidence_sufficient"] is False


def test_two_domains_without_crosscheck_are_pending():
    item = attach_evidence_state({
        "source_tier": "official",
        "crosscheck_status": "corroborated",
        "crosscheck_domains": ["fed.gov", "reuters.com"],
    })
    assert evidence_state(item) == "corroborated"
    assert item["evidence_reason"] == "等待市場同步"


def test_official_confirmed_still_waits_for_market_sync():
    item = attach_evidence_state({
        "source_tier": "official",
        "crosscheck_status": "official_confirmed",
        "cross_checked": True,
    })
    assert item["evidence_state"] == "official_confirmed"
    assert item["evidence_reason"] == "等待市場同步"
    assert item["evidence_sufficient"] is True


def test_summary_keeps_states_separate():
    counts = summarize_evidence([
        {"source_tier": "discovery"},
        {"source_tier": "official", "crosscheck_domains": ["a.example", "b.example"]},
    ])
    assert counts["discovery"] == 1
    assert counts["pending_crosscheck"] == 1
    assert counts["single_source"] == 0
