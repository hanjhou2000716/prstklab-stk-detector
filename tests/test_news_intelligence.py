from src.artifact_contract import validate_news_intelligence
from src.news_intelligence import (
    build_interest_graph,
    build_news_intelligence,
    canonicalize_url,
    deduplicate_and_rank,
    normalize_news_story,
    provider_for_url,
)


def test_provider_contract_and_url_normalization_are_canonical():
    url = "https://www.sec.gov/Archives/edgar/data/1/8-k?utm_source=x&oc=5"
    assert canonicalize_url(url) == "https://www.sec.gov/Archives/edgar/data/1/8-k"
    assert provider_for_url(url)["provider_id"] == "sec"
    assert normalize_news_story({"title": "Filing", "url": url}, "us")["public_safe"] is True


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


def test_dedup_prefers_official_and_retains_supporting_source():
    stories = [
        {"title": "Fed rates unchanged", "url": "https://news.google.com/rss/articles/1"},
        {"title": "Fed rates unchanged", "url": "https://www.federalreserve.gov/newsevents/pressreleases/a.htm"},
    ]
    ranked = deduplicate_and_rank(stories, limit=5)
    assert len(ranked) == 1
    assert ranked[0]["provider"] == "fed"
    assert ranked[0]["supporting_sources"][0]["provider"] == "google_news"


def test_news_intelligence_schema_rejects_provider_domain_mismatch():
    artifact = build_news_intelligence([{"title": "Fed", "url": "https://www.federalreserve.gov/a"}], market="us")
    assert validate_news_intelligence(artifact) == []
    artifact["stories"][0]["canonical_url"] = "https://evil.example/a"
    assert any("outside provider domains" in error for error in validate_news_intelligence(artifact))
