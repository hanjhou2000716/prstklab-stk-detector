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
    assert [story["title"] for story in payload["stories"]] == ["safe"]
    assert payload["status"] == "ready"


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


def test_news_intelligence_exposes_release_interest_context():
    artifact = build_news_intelligence(
        [{"title": "NVIDIA outlook", "url": "https://www.nasdaq.com/articles/nvda"}],
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


def test_dedup_prefers_official_and_retains_supporting_source():
    stories = [
        {"title": "Fed rates unchanged", "url": "https://news.google.com/rss/articles/1"},
        {"title": "Fed rates unchanged", "url": "https://www.federalreserve.gov/newsevents/pressreleases/a.htm"},
    ]
    ranked = deduplicate_and_rank(stories, limit=5)
    assert len(ranked) == 1
    assert ranked[0]["provider"] == "fed"
    assert ranked[0]["supporting_sources"][0]["provider"] == "google_news"


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
