from src.artifact_contract import validate_news_intelligence
from src.news_intelligence import (
    build_interest_graph,
    build_news_intelligence,
    canonicalize_url,
    deduplicate_and_rank,
    normalize_news_story,
    provider_for_url,
    provider_supports_market,
    summarize_source_diversity,
)


def test_provider_contract_and_url_normalization_are_canonical():
    url = "https://www.sec.gov/Archives/edgar/data/1/8-k?utm_source=x&oc=5"
    assert canonicalize_url(url) == "https://www.sec.gov/Archives/edgar/data/1/8-k"
    assert provider_for_url(url)["provider_id"] == "sec"
    assert normalize_news_story({"title": "Filing", "url": url}, "us")["public_safe"] is True


def test_provider_scope_prevents_us_official_news_from_entering_taiwan_feed():
    fed = provider_for_url("https://www.federalreserve.gov/newsevents/pressreleases/a.htm")
    assert provider_supports_market(fed, "us") is True
    assert provider_supports_market(fed, "taiwan") is False
    payload = build_news_intelligence(
        [{"title": "Fed policy update", "url": "https://www.federalreserve.gov/newsevents/pressreleases/a.htm"}],
        market="taiwan",
    )
    assert payload["stories"] == []
    assert payload["status"] == "no_event"
    assert payload["excluded_count"] == 1
    assert payload["exclusion_reasons"] == {"market_scope_mismatch": 1}


def test_cross_market_provider_remains_available_in_each_market_feed():
    google = provider_for_url("https://news.google.com/rss/articles/abc")
    assert provider_supports_market(google, "taiwan") is True
    assert provider_supports_market(google, "us") is True


def test_unknown_domain_is_not_public_safe():
    story = normalize_news_story({"title": "Injected", "url": "https://evil.example/story"}, "us")
    assert story["public_safe"] is False
    assert story["provider"] == "unknown"


def test_unknown_domain_is_excluded_from_public_ranking():
    payload = build_news_intelligence(
        [
            {"title": "unsafe", "url": "https://evil.example/story"},
            {"title": "safe", "url": "https://www.sec.gov/Archives/edgar/data/story"},
        ],
        market="us",
    )
    assert payload["stories"] == []
    assert payload["status"] == "no_event"
    assert payload["exclusion_reasons"]["generic_official_filing"] == 1


def test_generic_sec_filing_is_diagnostic_only_but_tracked_nvidia_filing_is_public():
    payload = build_news_intelligence(
        [
            {"title": "8-K current report", "url": "https://www.sec.gov/Archives/edgar/data/generic"},
            {"title": "NVDA announces quarterly results", "url": "https://www.sec.gov/Archives/edgar/data/nvda"},
        ], market="us", tracked_tickers=["NVDA"], research_tickers=["NVDA"],
    )
    assert [item["title"] for item in payload["stories"]] == ["NVDA announces quarterly results"]
    assert payload["exclusion_reasons"]["generic_official_filing"] == 1


def test_interest_graph_explains_tracked_ticker_and_market():
    story = normalize_news_story({"title": "NVIDIA outlook", "url": "https://www.nasdaq.com/articles/nvda", "tickers": ["NVDA"], "sectors": ["semiconductor"]}, "us")
    graph = build_interest_graph([story], tracked_tickers=["NVDA"], tracked_sectors=["semiconductor"])
    assert graph["ticker_interest"] == {"NVDA": 1}
    assert "tracked_ticker:NVDA" in story["relevance_reasons"]


def test_interest_graph_matches_release_context_in_title_without_entity_tags():
    story = normalize_news_story(
        {
            "title": "Federal Reserve policy lifts NVIDIA semiconductor outlook",
            "url": "https://www.federalreserve.gov/newsevents/pressreleases/a.htm",
        },
        "us",
    )
    graph = build_interest_graph(
        [story],
        tracked_tickers=["NVDA"],
        research_tickers=["NVDA"],
        tracked_sectors=["semiconductor"],
        active_event_topics=["Federal Reserve"],
        creator_mentions=["NVIDIA"],
    )
    assert "tracked_ticker:NVDA" in story["relevance_reasons"]
    assert "research_candidate:NVDA" in story["relevance_reasons"]
    assert "tracked_sector:semiconductor" in story["relevance_reasons"]
    assert "active_event:federal reserve" in story["relevance_reasons"]
    assert "creator_mentioned:nvidia" in story["relevance_reasons"]
    assert graph["source_interest"]["research_candidate"] == {"NVDA": 1}
    assert graph["source_interest"]["creator_mentioned"] == {"nvidia": 1}


def test_interest_graph_uses_token_boundaries_for_short_research_tickers():
    story = normalize_news_story(
        {
            "title": "8-K - RIVERVIEW BANCORP INC (0001041368) (Filer)",
            "url": "https://www.sec.gov/Archives/edgar/data/riverview/8-k.htm",
        },
        "us",
    )
    build_interest_graph([story], research_tickers=["EW", "ADI", "EL"])
    assert not any(reason.startswith("research_candidate:") for reason in story["relevance_reasons"])


def test_public_news_gate_rejects_sec_form_and_stock_selection_headlines():
    payload = build_news_intelligence(
        [
            {
                "title": "8-K - RIVERVIEW BANCORP INC (0001041368) (Filer)",
                "url": "https://www.sec.gov/Archives/edgar/data/riverview/8-k.htm",
            },
            {
                "title": "US Stocks In Focus: Top Pick after PPI data",
                "url": "https://news.google.com/rss/articles/listicle",
                "published_at": "2026-08-25T01:00:00+00:00",
            },
        ],
        market="us",
        research_tickers=["EW"],
    )
    assert payload["stories"] == []
    assert payload["exclusion_reasons"] == {
        "generic_official_filing": 1,
        "listicle_or_selection": 1,
    }


def test_market_and_discovery_news_without_publish_time_are_excluded():
    payload = build_news_intelligence(
        [{
            "title": "Nasdaq futures rise on semiconductor earnings",
            "url": "https://news.google.com/rss/articles/no-time",
        }],
        market="us",
    )
    assert payload["stories"] == []
    assert payload["exclusion_reasons"] == {"missing_published_at": 1}
    assert payload["scan_summary"]["fetched_story_count"] == 1
    assert payload["scan_summary"]["eligible_story_count"] == 0
    assert payload["scan_summary"]["ranked_story_count"] == 0


def test_public_news_ranking_is_capped_at_five_and_funnel_matches_output():
    stories = [
        {
            "title": f"Nasdaq futures rise on semiconductor earnings {index}",
            "url": f"https://news.google.com/rss/articles/quality-{index}",
            "published_at": f"2026-08-25T0{index}:00:00+00:00",
        }
        for index in range(1, 7)
    ]
    payload = build_news_intelligence(stories, market="us", limit=5)
    assert len(payload["stories"]) == 5
    assert payload["scan_summary"]["fetched_story_count"] == 6
    assert payload["scan_summary"]["eligible_story_count"] == 6
    assert payload["scan_summary"]["deduped_story_count"] == 6
    assert payload["scan_summary"]["ranked_story_count"] == len(payload["stories"]) == 5
    assert payload["scan_summary"]["publicly_ranked"] == len(payload["stories"]) == 5


def _inventory_story(index: int, title: str) -> dict[str, object]:
    return {
        "title": title,
        "url": f"https://news.google.com/rss/articles/inventory-{index}",
        "published_at": "2026-09-04T12:00:00+00:00",
        "inventory_age_trading_sessions": 1,
    }


def test_current_news_is_followed_by_qualified_inventory_until_five():
    payload = build_news_intelligence(
        [{
            "title": "Fed keeps rates unchanged as inflation cools",
            "url": "https://www.federalreserve.gov/newsevents/pressreleases/current.htm",
            "published_at": "2026-09-05T01:00:00+00:00",
        }],
        market="us",
        inventory_stories=[
            _inventory_story(1, "Nasdaq falls after jobs data"),
            _inventory_story(2, "NVIDIA earnings outlook supports semiconductor shares"),
            _inventory_story(3, "Oil jumps after sanctions disrupt supply"),
            _inventory_story(4, "US Treasury yields rise after payrolls data"),
        ],
    )
    assert len(payload["stories"]) == 5
    assert payload["stories"][0]["selection_lane"] == "current"
    assert all(item["selection_lane"] == "inventory" for item in payload["stories"][1:])
    assert payload["scan_summary"]["current_eligible"] == 1
    assert payload["scan_summary"]["inventory_selected"] == 4
    assert payload["scan_summary"]["final_public_count"] == 5
    assert payload["scan_summary"]["publicly_ranked"] == payload["scan_summary"]["ranked_story_count"] == 5
    assert validate_news_intelligence(payload) == []


def test_five_current_stories_do_not_add_inventory():
    current = [
        {
            "title": f"Nasdaq falls after jobs data {index}",
            "url": f"https://news.google.com/rss/articles/current-{index}",
            "published_at": f"2026-09-05T0{index}:00:00+00:00",
        }
        for index in range(1, 6)
    ]
    payload = build_news_intelligence(
        current, market="us", inventory_stories=[_inventory_story(9, "Oil jumps after sanctions disrupt supply")],
    )
    assert len(payload["stories"]) == 5
    assert payload["scan_summary"]["inventory_selected"] == 0
    assert all(item["selection_lane"] == "current" for item in payload["stories"])


def test_current_story_wins_when_inventory_repeats_same_article():
    current = {
        "title": "Fed keeps rates unchanged as inflation cools",
        "url": "https://news.google.com/rss/articles/shared",
        "published_at": "2026-09-05T01:00:00+00:00",
    }
    inventory = dict(current, inventory_age_trading_sessions=1)
    payload = build_news_intelligence([current], market="us", inventory_stories=[inventory])
    assert len(payload["stories"]) == 1
    assert payload["stories"][0]["selection_lane"] == "current"
    assert payload["scan_summary"]["inventory_selected"] == 0


def test_inventory_gate_does_not_fill_with_low_quality_stories():
    payload = build_news_intelligence(
        [], market="us", inventory_stories=[
            _inventory_story(1, "8-K - RIVERVIEW BANCORP INC (0001041368) (Filer)"),
            _inventory_story(2, "US Stocks In Focus: Top Pick after PPI data"),
            _inventory_story(3, "Ticker list: NVDA AMD TSM"),
            _inventory_story(4, "Government appoints a new official"),
        ],
    )
    assert payload["stories"] == []
    assert payload["scan_summary"]["final_public_count"] == 0
    assert payload["scan_summary"]["inventory_eligible"] == 0


def test_short_macro_token_does_not_classify_top_pick_as_ppi():
    from src.event_classifier import classify_event_fields

    result = classify_event_fields({"title": "Top Pick stocks to buy"})
    assert result["category"] is None


def test_new_public_news_fields_are_schema_valid():
    artifact = build_news_intelligence(
        [{
            "title": "Fed keeps rates unchanged as inflation cools",
            "url": "https://www.federalreserve.gov/newsevents/pressreleases/a.htm",
            "published_at": "2026-08-25T01:00:00+00:00",
        }],
        market="us",
    )
    assert validate_news_intelligence(artifact) == []
    story = artifact["stories"][0]
    assert story["public_news_eligible"] is True
    assert story["decision_value_class"] == "macro"
    assert "public_market_news_gate" in story["eligibility_reasons"]


def test_news_intelligence_exposes_release_interest_context():
    artifact = build_news_intelligence(
        [{
            "title": "NVIDIA outlook",
            "url": "https://www.nasdaq.com/articles/nvda",
            "published_at": "2026-08-25T01:00:00+00:00",
        }],
        market="us",
        tracked_tickers=["NVDA"],
        research_tickers=["NVDA"],
    )
    assert artifact["interest_graph"]["context"]["research_tickers"] == ["NVDA"]
    assert artifact["stories"][0]["relevance_reasons"] == [
        "tracked_ticker:NVDA",
        "research_candidate:NVDA",
        "market:us",
    ]


def test_news_intelligence_distinguishes_no_event_from_source_failure():
    empty = build_news_intelligence(
        [],
        market="us",
        source_health=[{"provider": "fed", "status": "no_event", "item_count": 0}],
    )
    failed = build_news_intelligence(
        [],
        market="us",
        source_health=[{
            "provider": "sec", "status": "failed", "item_count": 0,
            "error": "RequestsException must not be published",
        }],
    )
    assert empty["collection_state"] == "no_event"
    assert empty["source_failure_count"] == 0
    assert failed["collection_state"] == "source_failed"
    assert failed["source_failure_count"] == 1
    assert "error" not in failed["source_health"][0]


def test_news_intelligence_exposes_provider_observability_counts_and_timestamps():
    artifact = build_news_intelligence(
        [
            {
                "title": "Fed rates unchanged",
                "url": "https://www.federalreserve.gov/newsevents/pressreleases/a.htm",
                "published_at": "2026-08-25T01:00:00+00:00",
            },
            {
                "title": "Fed rates unchanged",
                "url": "https://news.google.com/rss/articles/fed-1",
                "published_at": "2026-08-25T01:01:00+00:00",
            },
        ],
        market="us",
        source_health=[
            {
                "provider": "fed",
                "status": "healthy",
                "checked_at": "2026-08-25T01:02:00+00:00",
                "item_count": 1,
            },
            {
                "provider": "sec",
                "status": "rate_limited",
                "checked_at": "2026-08-25T01:02:00+00:00",
                "item_count": 0,
            },
        ],
    )
    fed = next(item for item in artifact["observability"]["providers"] if item["provider"] == "fed")
    sec = next(item for item in artifact["observability"]["providers"] if item["provider"] == "sec")
    assert artifact["observability"]["stories_ingested"] == 2
    assert artifact["observability"]["stories_deduped"] == 1
    assert artifact["observability"]["ranked_count"] == 1
    assert fed["stories_ingested"] == 1
    assert fed["stories_deduped"] == 1
    assert fed["ranked_count"] == 1
    assert fed["last_success_at"] == "2026-08-25T01:02:00+00:00"
    assert sec["last_failure_at"] == "2026-08-25T01:02:00+00:00"
    assert artifact["source_health"][0]["stories_ingested"] == 1


def test_provider_funnel_explains_fetched_to_ranked_counts():
    artifact = build_news_intelligence(
        [
            {"title": "Fed rates unchanged", "url": "https://www.federalreserve.gov/newsevents/pressreleases/a.htm"},
            {"title": "Unrelated filing", "url": "https://www.sec.gov/Archives/edgar/data/example/8-k.htm"},
        ],
        market="us",
        source_health=[
            {"provider": "fed", "status": "healthy", "item_count": 4, "checked_at": "2026-08-25T01:02:00+00:00"},
            {"provider": "sec", "status": "healthy", "item_count": 2, "checked_at": "2026-08-25T01:02:00+00:00"},
        ],
    )

    fed = next(item for item in artifact["observability"]["providers"] if item["provider"] == "fed")
    sec = next(item for item in artifact["observability"]["providers"] if item["provider"] == "sec")
    assert fed["funnel"] == {
        "fetched_count": 4,
        "normalized_count": 1,
        "market_compatible_count": 1,
        "eligible_count": 1,
        "excluded_count": 0,
        "deduped_count": 1,
        "ranked_count": 1,
    }
    assert sec["funnel"]["fetched_count"] == 2
    assert sec["funnel"]["eligible_count"] == 0
    assert sec["funnel"]["excluded_count"] == 1
    health_fed = next(item for item in artifact["source_health"] if item["provider"] == "fed")
    assert health_fed["funnel"]["ranked_count"] == 1


def test_news_intelligence_observability_is_schema_valid_for_empty_and_failed_scan():
    artifact = build_news_intelligence(
        [],
        market="us",
        source_health=[{"provider": "sec", "status": "failed", "checked_at": "2026-08-25T01:02:00+00:00"}],
    )
    assert artifact["observability"]["stories_ingested"] == 0
    assert artifact["observability"]["ranked_count"] == 0
    assert validate_news_intelligence(artifact) == []


def test_dedup_prefers_official_and_retains_supporting_source():
    stories = [
        {"title": "Fed rates unchanged", "url": "https://news.google.com/rss/articles/1"},
        {"title": "Fed rates unchanged", "url": "https://www.federalreserve.gov/newsevents/pressreleases/a.htm"},
    ]
    ranked = deduplicate_and_rank(stories, limit=5)
    assert len(ranked) == 1
    assert ranked[0]["provider"] == "fed"
    assert ranked[0]["supporting_sources"][0]["provider"] == "google_news"


def test_rank_uses_diversity_first_then_fills_to_limit():
    stories = [
        {"title": f"NVIDIA update {index}", "url": f"https://news.google.com/rss/articles/{index}", "published_at": f"2026-08-30T0{index}:00:00+00:00"}
        for index in range(1, 6)
    ] + [
        {"title": "台積電供應鏈觀察", "url": "https://www.cnyes.com/news/tsmc-1", "market": "taiwan"},
    ]
    ranked = deduplicate_and_rank(stories, limit=5)
    assert len(ranked) == 5
    assert ranked[0]["provider"] != ranked[1]["provider"]


def test_rank_returns_only_available_safe_rows_when_fewer_than_limit():
    ranked = deduplicate_and_rank([
        {"title": "only one", "url": "https://www.sec.gov/Archives/edgar/data/one"},
        {"title": "only two", "url": "https://www.sec.gov/Archives/edgar/data/two"},
        {"title": "only three", "url": "https://www.sec.gov/Archives/edgar/data/three"},
    ], limit=5)
    assert len(ranked) == 3


def test_source_diversity_counts_independent_domains_after_dedup():
    ranked = deduplicate_and_rank([
        {"title": "Fed rates unchanged", "url": "https://news.google.com/rss/articles/1"},
        {"title": "Fed rates unchanged", "url": "https://www.federalreserve.gov/newsevents/pressreleases/a.htm"},
    ])
    summary = summarize_source_diversity(ranked)
    assert summary["status"] == "multi_source"
    assert summary["cross_checked"] is True
    assert summary["independent_source_count"] == 2
    assert summary["source_domains"] == ["federalreserve.gov", "news.google.com"]


def test_source_diversity_marks_single_source_without_inventing_confirmation():
    artifact = build_news_intelligence(
        [{"title": "Fed rates unchanged", "url": "https://www.federalreserve.gov/newsevents/pressreleases/a.htm"}],
        market="us",
    )
    assert artifact["source_diversity"]["status"] == "single_source"
    assert artifact["source_diversity"]["cross_checked"] is False


def test_source_diversity_contract_rejects_inconsistent_confirmation():
    artifact = build_news_intelligence(
        [{"title": "Fed rates unchanged", "url": "https://www.federalreserve.gov/newsevents/pressreleases/a.htm"}],
        market="us",
    )
    artifact["source_diversity"]["cross_checked"] = True
    errors = validate_news_intelligence(artifact)
    assert any("cross_checked disagrees" in error for error in errors)


def test_dedup_merges_cross_provider_event_with_different_headlines():
    ranked = deduplicate_and_rank([
        {
            "title": "NVIDIA earnings beat estimates",
            "url": "https://news.google.com/rss/articles/nvda-1",
            "published_at": "2026-08-21T02:10:00+00:00",
        },
        {
            "title": "Nvidia reports stronger quarterly revenue",
            "url": "https://www.sec.gov/Archives/edgar/data/nvda-8k",
            "published_at": "2026-08-21T02:35:00+00:00",
        },
    ])
    assert len(ranked) == 1
    assert ranked[0]["provider"] == "sec"
    assert ranked[0]["event_cluster_key"].startswith("event-")
    assert ranked[0]["supporting_sources"] == [{"provider": "google_news", "url": "https://news.google.com/rss/articles/nvda-1"}]


def test_dedup_keeps_same_ticker_different_topic_separate():
    ranked = deduplicate_and_rank([
        {
            "title": "NVIDIA earnings beat estimates",
            "url": "https://news.google.com/rss/articles/nvda-earnings",
            "published_at": "2026-08-21T02:10:00+00:00",
        },
        {
            "title": "NVIDIA faces new export control review",
            "url": "https://www.sec.gov/Archives/edgar/data/nvda-review",
            "published_at": "2026-08-21T02:35:00+00:00",
        },
    ])
    assert len(ranked) == 2


def test_normalized_story_exposes_bounded_event_identity():
    story = normalize_news_story({
        "title": "聯準會利率決策影響 Nasdaq",
        "url": "https://www.federalreserve.gov/newsevents/pressreleases/a.htm",
        "published_at": "2026-08-21T04:01:00+00:00",
    }, "us")
    assert "NASDAQ" in story["entities"]
    assert "rates" in story["topics"]
    assert story["published_time_bucket"] == "2026-08-21T04:00:00+00:00"
    assert story["event_cluster_key"].startswith("event-")


def test_news_story_uses_shared_classifier_with_full_evidence_fields():
    story = normalize_news_story({
        "title": "White House Iran talks update",
        "summary": "Officials discuss shipping and oil supply risks.",
        "what_happened": "Negotiations continue while the market waits for confirmation.",
        "market_impact": "WTI +5.2%; Nasdaq -0.4%.",
        "related_quotes": {"WTI": {"change_percent": 5.2}, "Nasdaq": {"change_percent": -0.4}},
        "url": "https://news.google.com/rss/articles/iran-1",
        "published_at": "2026-08-21T04:01:00+00:00",
    }, "us")
    classification = story["event_classification"]
    assert classification["classifier"] == "src.event_classifier.classify_event_fields"
    assert classification["category"] == "conflict"
    assert "summary" in classification["input_fields"]
    assert "what_happened" in classification["input_fields"]
    assert "market_impact" in classification["input_fields"]
    assert "related_quotes" in classification["input_fields"]
    assert "text" not in classification


def test_news_and_live_event_share_category_and_matched_term():
    from src.event_classifier import classify_event_fields

    record = {
        "title": "Fed rate decision affects Nasdaq",
        "summary": "US rates and bond yields are being repriced.",
        "market_data": {"Nasdaq": {"change_percent": -0.4}},
    }
    story = normalize_news_story({**record, "url": "https://www.federalreserve.gov/a"}, "us")
    live = classify_event_fields(record)
    assert story["event_classification"]["category"] == live["category"]
    assert story["event_classification"]["matched_terms"] == live["matched_terms"]


def test_news_intelligence_schema_rejects_provider_domain_mismatch():
    artifact = build_news_intelligence([{"title": "Fed", "url": "https://www.federalreserve.gov/a"}], market="us")
    assert validate_news_intelligence(artifact) == []
    artifact["stories"][0]["canonical_url"] = "https://evil.example/a"
    assert any("outside provider domains" in error for error in validate_news_intelligence(artifact))


def test_news_intelligence_rejects_missing_provider_registry():
    artifact = build_news_intelligence([])
    artifact["provider_registry"] = None
    assert any("provider_registry must be an array" in error for error in validate_news_intelligence(artifact))


def test_news_intelligence_rejects_malformed_provider_entries():
    artifact = build_news_intelligence([])
    artifact["provider_registry"] = [None, {"provider_id": "dup", "domains": []}, {"provider_id": "dup", "domains": []}]
    errors = validate_news_intelligence(artifact)
    assert any("must be an object" in error for error in errors)
    assert any("duplicates dup" in error for error in errors)


def test_news_intelligence_rejects_feed_endpoint_outside_provider_domain():
    artifact = build_news_intelligence([])
    artifact["provider_registry"][0]["feed_url"] = "https://evil.example/news"
    assert any("feed_url is outside provider domains" in error for error in validate_news_intelligence(artifact))


def test_news_intelligence_allows_explicit_disabled_provider_without_endpoint():
    artifact = build_news_intelligence([])
    nasdaq = next(item for item in artifact["provider_registry"] if item["provider_id"] == "nasdaq")
    nasdaq["feed_url"] = ""
    nasdaq["enabled"] = False
    assert not any("feed_url" in error for error in validate_news_intelligence(artifact))
