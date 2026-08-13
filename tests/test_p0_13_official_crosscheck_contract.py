from src.event_crosscheck import cross_check_event_records


def test_official_and_independent_domain_are_confirmed_with_provenance():
    records = [
        {
            "source_tier": "official",
            "classification": "macro",
            "title": "ECB monetary policy rate decision",
            "source_url": "https://www.ecb.europa.eu/press/rate-decision",
        },
        {
            "source_tier": "discovery",
            "classification": "macro",
            "title": "Reuters ECB interest rate decision and liquidity",
            "source_url": "https://www.reuters.com/markets/ecb-rate-decision",
        },
    ]
    result = cross_check_event_records(records)
    assert result[0]["crosscheck_status"] == "official_confirmed"
    assert result[0]["cross_checked"] is True
    assert set(result[0]["crosscheck_domains"]) == {"ecb.europa.eu", "reuters.com"}
    assert result[0]["crosscheck_sources"]


def test_same_domain_reports_never_become_independent_confirmation():
    records = [
        {
            "source_tier": "discovery",
            "classification": "conflict",
            "title": "Iran talks focus on shipping security",
            "source_url": "https://www.reuters.com/world/iran-a",
        },
        {
            "source_tier": "discovery",
            "classification": "conflict",
            "title": "Reuters Iran talks focus on shipping security",
            "source_url": "https://www.reuters.com/world/iran-b",
        },
    ]
    result = cross_check_event_records(records)
    assert all(item["cross_checked"] is False for item in result)
    assert all(item["crosscheck_status"] == "pending_second_source" for item in result)


def test_missing_provenance_remains_unverified_and_visible():
    result = cross_check_event_records(
        [{"source_tier": "discovery", "classification": "conflict", "title": "Iran talks"}]
    )
    assert result[0]["cross_checked"] is False
    assert result[0]["crosscheck_status"] == "pending_second_source"
