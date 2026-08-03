from src.event_crosscheck import cross_check_event_records, event_evidence


def test_event_evidence_requires_entity_and_action_anchors():
    evidence = event_evidence({"title": "Iran talks may resume", "event_type": "conflict"})
    assert "conflict" == evidence["category"]
    assert evidence["entities"] or evidence["places"]
    assert evidence["actions"]


def test_official_and_reuters_records_collapse_into_one_verified_event():
    records = [
        {
            "kind": "official_event",
            "source_tier": "official",
            "classification": "conflict",
            "title": "Iran talks and shipping security statement",
            "source_url": "https://www.whitehouse.gov/news/iran-talks",
        },
        {
            "kind": "major_event",
            "source_tier": "discovery",
            "classification": "conflict",
            "title": "Reuters: Iran talks focus on shipping security",
            "source_url": "https://www.reuters.com/world/iran-talks",
        },
    ]
    merged = cross_check_event_records(records)
    assert len(merged) == 1
    assert merged[0]["crosscheck_status"] == "official_confirmed"
    assert set(merged[0]["crosscheck_domains"]) == {"whitehouse.gov", "reuters.com"}
    assert merged[0]["cross_checked"] is True


def test_ecb_and_reuters_rate_story_uses_central_bank_anchors():
    records = [
        {
            "kind": "official_event",
            "source_tier": "official",
            "classification": "macro",
            "title": "ECB monetary policy rate decision",
            "source_url": "https://www.ecb.europa.eu/press/rate-decision",
        },
        {
            "kind": "major_event",
            "source_tier": "discovery",
            "classification": "macro",
            "title": "Reuters: ECB interest rate decision keeps markets focused on liquidity",
            "source_url": "https://www.reuters.com/markets/ecb-rate-decision",
        },
    ]
    merged = cross_check_event_records(records)
    assert len(merged) == 1
    assert merged[0]["crosscheck_status"] == "official_confirmed"


def test_single_discovery_event_remains_visible_as_pending():
    records = [{
        "kind": "major_event",
        "source_tier": "discovery",
        "classification": "conflict",
        "title": "GDELT Iran talks could resume",
        "source_url": "https://www.reuters.com/world/iran-talks",
    }]
    result = cross_check_event_records(records)
    assert len(result) == 1
    assert result[0]["crosscheck_status"] == "pending_second_source"
    assert result[0]["cross_checked"] is False


def test_same_domain_duplicate_is_not_claimed_as_independent_confirmation():
    records = [
        {
            "kind": "major_event",
            "source_tier": "discovery",
            "classification": "conflict",
            "title": "Iran talks focus on shipping security",
            "source_url": "https://www.reuters.com/a",
        },
        {
            "kind": "major_event",
            "source_tier": "discovery",
            "classification": "conflict",
            "title": "Iran talks focus on shipping security",
            "source_url": "https://www.reuters.com/b",
        },
    ]
    result = cross_check_event_records(records)
    assert len(result) == 2
    assert all(item["crosscheck_status"] == "pending_second_source" for item in result)
