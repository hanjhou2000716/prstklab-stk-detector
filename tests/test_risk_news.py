import pytest

from src.news_intelligence import build_news_intelligence
from src.risk_news import (
    _filter_market_news,
    _market_news_rss_url,
    _market_risk,
    _news_from_html,
    _news_from_rss,
    _news_lists_collide,
    _parse_taifex_vix_file,
    build_news_snapshot,
    build_risk_snapshot,
    classify_news_market,
    fetch_taifex_vix_quote,
    sentiment_label,
    vix_stage,
)


def test_sentiment_labels_cover_fixed_thresholds():
    assert sentiment_label(None) == "資料暫時無法取得"
    assert sentiment_label(9.9) == "極度恐慌"
    assert sentiment_label(10) == "恐慌"
    assert sentiment_label(25) == "中立／偏恐慌"
    assert sentiment_label(51) == "貪婪"
    assert sentiment_label(76) == "極度貪婪"


def test_news_extraction_prioritizes_relevant_unique_article_links():
    html = """
    <a href="/news/id/1">台積電供應鏈新訊</a>
    <a href="/news/id/1">台積電供應鏈新訊</a>
    <a href="/news/id/2">一般生活新聞</a>
    <a href="/news/id/3">2330 法說會</a>
    """
    stories = _news_from_html(html, "taiwan")
    assert [story["url"] for story in stories] == [
        "https://news.cnyes.com/news/id/1",
        "https://news.cnyes.com/news/id/3",
        "https://news.cnyes.com/news/id/2",
    ]
    assert [story["relevance"] for story in stories] == ["holding", "holding", "market"]


def test_news_extraction_falls_back_to_disclosed_market_focus():
    html = """
    <a href="/news/id/1">法人解讀今日大盤表現</a>
    <a href="/news/id/2">市場關注資金輪動</a>
    """

    stories = _news_from_html(html, "taiwan")

    assert [story["url"] for story in stories] == [
        "https://news.cnyes.com/news/id/1",
        "https://news.cnyes.com/news/id/2",
    ]
    assert {story["source"] for story in stories} == {"鉅亨網｜市場焦點"}


def test_taifex_vix_parser_uses_the_final_intraday_observation():
    content = b"header\r\n20260723\t9000000\t\t\t35.77\r\n20260723\t13450000\t\t\t36.21\r\n"

    parsed = _parse_taifex_vix_file(content)

    assert parsed["value"] == 36.21
    assert parsed["date"] == "2026-07-23"
    assert parsed["percentile_status"] == "unavailable"
    assert parsed["stage_basis"] == "absolute_level_fallback"
    assert parsed["freshness_state"] == "daily_close"
    assert parsed["source_label"] == "臺灣期貨交易所"
    assert parsed["percentile"] is None
    assert parsed["stage"] == "極度恐慌"


def test_taifex_vix_parser_rejects_zero_placeholder():
    content = b"header\r\n20260831\t000000\t\t\t0.00\r\n"

    with pytest.raises(ValueError, match="沒有可用數值"):
        _parse_taifex_vix_file(content)


def test_vix_stage_uses_the_confirmed_10_30_70_90_percentile_bands():
    assert vix_stage(18, 10) == "極度樂觀"
    assert vix_stage(18, 30) == "樂觀"
    assert vix_stage(18, 70) == "中立"
    assert vix_stage(18, 90) == "恐慌"
    assert vix_stage(18, 90.1) == "極度恐慌"


def test_taifex_fallback_keeps_taiwan_vix_available(monkeypatch):
    monkeypatch.setattr("src.risk_news._latest_close", lambda symbol: (_ for _ in ()).throw(ValueError("unavailable")))
    result = _market_risk("台股", "^VIXTWN", fallback=lambda: {
        "value": 36.21, "date": "2026-07-23", "change_percent": 1.2, "source_label": "臺灣期貨交易所",
    })

    assert result["vix"]["source_label"] == "臺灣期貨交易所"
    assert result["errors"] == []


def test_taifex_quote_fallback_uses_official_mis_endpoint(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "RtData": {
                    "QuoteList": [{
                        "SymbolID": "TAIWANVIX",
                        "CLastPrice": "40.77",
                        "CRefPrice": "44.31",
                        "CDate": "20260731",
                    }]
                }
            }

    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr("src.risk_news.requests.post", fake_post)

    result = fetch_taifex_vix_quote()

    assert captured["url"] == "https://mis.taifex.com.tw/futures/api/getQuoteListVIX"
    assert result["value"] == 40.77
    assert result["change_percent"] == -7.99
    assert result["date"] == "2026-07-31"
    assert result["source_label"] == "TAIFEX"


def test_taifex_zero_placeholder_uses_explicit_recent_reference(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"RtData": {"QuoteList": [{
                "SymbolID": "TAIWANVIX",
                "CLastPrice": "0.00",
                "CRefPrice": "24.99",
                "CDate": "20260831",
                "CTime": "000000",
            }]}}

    monkeypatch.setattr("src.risk_news.requests.post", lambda *args, **kwargs: Response())

    result = fetch_taifex_vix_quote()

    assert result["value"] == 24.99
    assert result["change_percent"] is None
    assert result["freshness_state"] == "recent_reference"
    assert result["value_status"] == "recent_reference"
    assert result["live_value"] == 0.0
    assert result["reference_value"] == 24.99


def test_taifex_invalid_live_and_reference_is_unavailable(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"RtData": {"QuoteList": [{
                "SymbolID": "TAIWANVIX", "CLastPrice": "", "CRefPrice": "0",
                "CDate": "20260831",
            }]}}

    monkeypatch.setattr("src.risk_news.requests.post", lambda *args, **kwargs: Response())

    with pytest.raises(ValueError, match="unavailable"):
        fetch_taifex_vix_quote()


def test_market_news_rss_parser_keeps_market_specific_links():
    xml = """
    <rss><channel>
      <item><title>US Nasdaq outlook</title><link>https://news.google.com/rss/articles/us1</link><pubDate>Mon, 24 Aug 2026 01:30:00 GMT</pubDate></item>
      <item><title>Taiwan semiconductor outlook</title><link>https://news.google.com/rss/articles/tw1</link></item>
    </channel></rss>
    """
    stories = _news_from_rss(xml, "us")
    assert stories[0]["url"].endswith("/us1")
    assert stories[0]["source"] == "Google News｜美股線索"
    assert stories[0]["published_at"] == "2026-08-24T01:30:00+00:00"


def test_market_news_rss_parser_accepts_atom_timestamp_and_marks_invalid_as_unknown():
    xml = """
    <rss xmlns:atom="http://www.w3.org/2005/Atom"><channel>
      <item><title>Nasdaq outlook</title><link>https://news.google.com/rss/articles/us2</link>
        <atom:updated>2026-08-24T02:00:00+02:00</atom:updated></item>
      <item><title>Federal Reserve outlook</title><link>https://news.google.com/rss/articles/us3</link>
        <pubDate>not-a-date</pubDate></item>
    </channel></rss>
    """
    stories = _news_from_rss(xml, "us")
    assert stories[0]["published_at"] == "2026-08-24T00:00:00+00:00"
    assert stories[1]["published_at"] is None


def test_duplicate_market_payload_uses_separate_fallback_feeds(monkeypatch):
    duplicate = [{"title": "same", "url": "https://news.cnyes.com/news/id/1"}]
    monkeypatch.setattr("src.risk_news.fetch_market_news", lambda market: duplicate.copy())
    monkeypatch.setattr(
        "src.risk_news.fetch_market_news_fallback",
            lambda market: [{"title": "Taiwan market" if market == "taiwan" else "US stocks", "url": f"https://news.google.com/rss/articles/{market}"}],
    )

    snapshot = build_news_snapshot()

    assert snapshot["taiwan"][0]["title"] == "Taiwan market"
    assert snapshot["us"][0]["title"] == "US stocks"
    assert all(item.get("fallback_used") for item in snapshot["source_health"])


def test_news_cache_prevents_empty_us_panel_after_transient_outage(monkeypatch, tmp_path):
    cache_path = tmp_path / "news-cache.json"
    monkeypatch.setenv("NEWS_CACHE_PATH", str(cache_path))
    fresh = {
        "taiwan": [{"title": "Taiwan market", "url": "https://example.test/tw"}],
        "us": [{"title": "US stocks", "url": "https://example.test/us"}],
    }
    monkeypatch.setattr("src.risk_news.fetch_market_news", lambda market: fresh[market])
    monkeypatch.setattr("src.risk_news.fetch_market_news_fallback", lambda market: [])
    first = build_news_snapshot()
    assert first["us"][0]["title"] == "US stocks"
    assert cache_path.exists()

    def unavailable(_market):
        raise RuntimeError("temporary outage")

    monkeypatch.setattr("src.risk_news.fetch_market_news", unavailable)
    second = build_news_snapshot()

    assert second["us"][0]["title"] == "US stocks"
    assert second["us"][0]["stale_used"] is True
    us_health = next(item for item in second["source_health"] if item["key"] == "news_us")
    assert us_health["status"] == "stale"


def test_taiwan_macro_fgi_is_used_as_taiwan_sentiment(monkeypatch):
    macro = {
        "score": 52.5,
        "label": "中立",
        "source_label": "TAIEX Macro FGI",
        "date": "2026-07-24",
        "index_level": 24000.0,
        "sub_scores": {"動能": 50.0},
    }
    monkeypatch.setattr("src.risk_news.calculate_taiwan_macro_fgi", lambda: macro)
    monkeypatch.setattr("src.risk_news.fetch_cnn_fear_greed", lambda: {
        "score": 50.0, "label": "中立", "source_label": "CNN Fear & Greed"
    })
    monkeypatch.setattr("src.risk_news._market_risk", lambda label, *_args, **kwargs: {
        "label": label, "sentiment": _args[1] if len(_args) > 1 else None, "vix": None, "errors": []
    })

    snapshot = build_risk_snapshot()

    assert snapshot["taiwan"]["sentiment"] == macro


def test_us_news_filter_rejects_taiwan_headlines_but_keeps_us_headlines():
    stories = [
        {"title": "\u53f0\u80a1 \u53f0\u7a4d\u96fb\u76e4\u52e2", "url": "https://news.cnyes.com/news/id/tw"},
        {"title": "Nasdaq futures and Federal Reserve outlook", "url": "https://news.google.com/rss/articles/us"},
    ]
    filtered = _filter_market_news(stories, "us")
    assert [item["title"] for item in filtered] == ["Nasdaq futures and Federal Reserve outlook"]


def test_us_news_filter_preserves_later_eligible_providers_before_ranking():
    """Generic SEC rows must not starve valid stories that arrive later."""
    generic_sec = [
        {
            "title": "8-K - ALLIANCE ENTERTAINMENT HOLDING CORP (Filer)" if index == 5 else f"8-K current report {index}",
            "url": f"https://www.sec.gov/Archives/edgar/data/generic-{index}",
        }
        for index in range(6)
    ]
    later = [
        {
            "title": "NVIDIA earnings outlook supports Nasdaq",
            "url": "https://news.cnyes.com/news/id/us-nvda",
            "provider": "anue",
            "tickers": ["NVDA"],
            "published_at": "2026-08-25T01:00:00+00:00",
        },
        {
            "title": "NVIDIA outlook lifts US semiconductor shares",
            "url": "https://finance.yahoo.com/news/us-nvda-outlook",
            "provider": "yahoo_finance",
            "tickers": ["NVDA"],
            "published_at": "2026-08-25T01:01:00+00:00",
        },
        {
            "title": "Nasdaq and NVIDIA earnings outlook",
            "url": "https://news.google.com/rss/articles/us-nvda",
            "provider": "google_news",
            "tickers": ["NVDA"],
            "published_at": "2026-08-25T01:02:00+00:00",
        },
    ]

    filtered = _filter_market_news(generic_sec + later, "us")
    assert len(filtered) == 9

    payload = build_news_intelligence(filtered, market="us", tracked_tickers=["NVDA"])
    assert 0 < len(payload["stories"]) <= 5
    assert all(item["provider"] != "sec" for item in payload["stories"])
    assert payload["exclusion_reasons"]["generic_official_filing"] == 6


def test_market_classifier_routes_fed_and_lai_to_their_own_tabs():
    fed = {"title": "Federal Reserve keeps rates unchanged", "url": "https://example.test/fed"}
    lai = {"title": "Taiwan President Lai Ching-te addresses parliament", "url": "https://example.test/lai"}

    assert classify_news_market(fed)["market_scope"] == "us"
    assert classify_news_market(lai)["market_scope"] == "taiwan"
    assert _filter_market_news([fed, lai], "taiwan")[0]["title"].startswith("Taiwan")
    assert _filter_market_news([fed, lai], "us")[0]["title"].startswith("Federal")


def test_market_classifier_retains_routing_evidence_on_story():
    story = {"title": "Federal Reserve outlook", "summary": "US rates", "url": "https://example.test/fed"}
    classification = classify_news_market(story)
    assert classification["routing_evidence"]["title_summary_scanned"] is True
    assert classification["routing_evidence"]["matched_term_count"] >= 1


def test_market_filter_rejects_unclassified_headline_instead_of_copying_to_both_tabs():
    story = {"title": "Company announces quarterly update", "url": "https://example.test/neutral"}
    assert classify_news_market(story)["market_scope"] == "unclassified"
    assert _filter_market_news([story], "taiwan") == []
    assert _filter_market_news([story], "us") == []


def test_us_discovery_success_with_official_failure_is_degraded_not_source_failed(monkeypatch, tmp_path):
    monkeypatch.setenv("NEWS_CACHE_PATH", str(tmp_path / "news-cache.json"))
    story = {
        "title": "Nasdaq and Nvidia earnings outlook",
        "url": "https://news.google.com/rss/articles/us-observation",
        "published_at": "2026-08-25T01:00:00+00:00",
    }
    monkeypatch.setattr("src.risk_news.fetch_market_news", lambda market: [story] if market == "us" else [])
    monkeypatch.setattr("src.risk_news.fetch_market_news_fallback", lambda market: [])
    monkeypatch.setattr(
        "src.risk_news._LAST_OFFICIAL_NEWS_HEALTH",
        {
            "taiwan": {"source_health": []},
            "us": {"source_health": [
                {"provider": "sec", "status": "failed", "item_count": 0},
                {"provider": "fed", "status": "failed", "item_count": 0},
                {"provider": "google_news", "status": "healthy", "item_count": 1, "source_tier": "discovery"},
            ]},
        },
    )

    snapshot = build_news_snapshot()
    us = snapshot["intelligence"]["us"]

    assert us["stories"][0]["evidence_state"] == "observation"
    assert us["collection_state"] == "degraded"
    assert us["scan_summary"]["successful_provider_count"] == 1
    assert us["scan_summary"]["failed_provider_count"] == 2


def test_provider_funnel_counts_only_market_scoped_stories(monkeypatch, tmp_path):
    """Raw feed hits rejected by routing must not block a valid no-event release."""
    monkeypatch.setenv("NEWS_CACHE_PATH", str(tmp_path / "news-cache.json"))
    monkeypatch.setattr(
        "src.risk_news.fetch_market_news",
        lambda market: ([{"title": "Company announces quarterly update", "url": "https://example.test/raw"}] if market == "us" else []),
    )
    monkeypatch.setattr("src.risk_news.fetch_market_news_fallback", lambda market: [])
    monkeypatch.setattr(
        "src.risk_news._LAST_OFFICIAL_NEWS_HEALTH",
        {
            "taiwan": {"source_health": []},
            "us": {"source_health": [{"provider": "yahoo_finance", "status": "healthy", "item_count": 3}]},
        },
    )

    snapshot = build_news_snapshot()
    provider = next(
        row for row in snapshot["source_health"]
        if row.get("key") == "news_us_yahoo_finance"
    )

    assert provider["raw_item_count"] == 3
    assert provider["filtered_item_count"] == 0
    assert provider["item_count"] == 0
    assert provider["status"] == "no_event"
    assert snapshot["intelligence"]["us"]["collection_state"] == "no_event"


def test_final_intelligence_projection_rebinds_health_after_cache_or_fallback(monkeypatch, tmp_path):
    """The release-bound intelligence cannot retain raw provider availability."""
    monkeypatch.setenv("NEWS_CACHE_PATH", str(tmp_path / "news-cache.json"))
    monkeypatch.setattr("src.risk_news.fetch_market_news", lambda market: [
        {"title": "Company announces quarterly update", "url": "https://example.test/raw", "provider": "yahoo_finance"}
    ] if market == "us" else [])
    monkeypatch.setattr("src.risk_news.fetch_market_news_fallback", lambda market: [])
    monkeypatch.setattr(
        "src.risk_news._LAST_OFFICIAL_NEWS_HEALTH",
        {
            "taiwan": {"source_health": []},
            "us": {"source_health": [{"provider": "yahoo_finance", "status": "healthy", "item_count": 7}]},
        },
    )

    snapshot = build_news_snapshot()
    provider = next(row for row in snapshot["intelligence"]["us"]["source_health"]
                    if row.get("provider") == "yahoo_finance")

    assert provider["raw_item_count"] == 7
    assert provider["filtered_item_count"] == 0
    assert provider["item_count"] == 0
    assert provider["status"] == "no_event"


def test_final_intelligence_projection_reconciles_legacy_builder_output(monkeypatch, tmp_path):
    """A legacy intelligence builder cannot leak raw availability into a release."""
    monkeypatch.setenv("NEWS_CACHE_PATH", str(tmp_path / "news-cache.json"))
    monkeypatch.setattr("src.risk_news.fetch_market_news", lambda market: [])
    monkeypatch.setattr("src.risk_news.fetch_market_news_fallback", lambda market: [])
    monkeypatch.setattr(
        "src.risk_news._LAST_OFFICIAL_NEWS_HEALTH",
        {
            "taiwan": {"source_health": []},
            "us": {"source_health": [{"provider": "yahoo_finance", "status": "healthy", "item_count": 7}]},
        },
    )

    def legacy_builder(*_args, market=None, **_kwargs):
        return {
            "stories": [],
            "status": "no_event",
            "collection_state": "source_failed",
            "source_failure_count": 0,
            "scan_summary": {},
            "source_health": [{
                "provider": "yahoo_finance",
                "key": f"news_{market}_yahoo_finance",
                "status": "healthy",
                "item_count": 7,
            }],
        }

    monkeypatch.setattr("src.risk_news.build_news_intelligence", legacy_builder)
    snapshot = build_news_snapshot()
    us = snapshot["intelligence"]["us"]
    provider = us["source_health"][0]

    assert provider["raw_item_count"] == 7
    assert provider["filtered_item_count"] == 0
    assert provider["item_count"] == 0
    assert provider["status"] == "no_event"
    assert us["collection_state"] == "no_event"


def test_global_story_does_not_trigger_false_taiwan_us_collision():
    story = {
        "title": "Iran oil shock hits Taiwan semiconductor shares and Nasdaq",
        "url": "https://news.google.com/rss/articles/global-shock",
    }
    taiwan = _filter_market_news([story], "taiwan")
    us = _filter_market_news([story], "us")

    assert taiwan and us
    assert not _news_lists_collide(taiwan, us)


def test_global_or_cross_market_story_is_explicitly_auditable():
    story = {
        "title": "Iran oil shock hits Taiwan semiconductor shares and Nasdaq",
        "url": "https://example.test/iran",
    }
    classification = classify_news_market(story)
    assert classification["market_scope"] == "cross_market"
    assert "iran" in classification["global_matches"]
    assert "nasdaq" in classification["us_matches"]
    assert "taiwan" in classification["taiwan_matches"]


def test_us_rss_fallback_uses_us_locale():
    url = _market_news_rss_url("us")
    assert "hl=en-US" in url
    assert "gl=US" in url
    assert "ceid=US%3Aen" in url


def test_market_rss_queries_are_not_encoding_corrupted():
    taiwan_url = _market_news_rss_url("taiwan")
    us_url = _market_news_rss_url("us")
    assert "%E5%8F%B0%E8%82%A1" in taiwan_url
    assert "Federal+Reserve" in us_url


def test_empty_news_scan_is_distinguished_from_provider_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("NEWS_CACHE_PATH", str(tmp_path / "news-cache.json"))
    monkeypatch.setattr("src.risk_news.fetch_market_news", lambda market: [])
    monkeypatch.setattr("src.risk_news.fetch_market_news_fallback", lambda market: [])
    snapshot = build_news_snapshot()
    assert snapshot["taiwan"] == []
    assert snapshot["us"] == []
    assert all(item["status"] == "no_event" for item in snapshot["source_health"])


def test_release_bound_news_intelligence_keeps_provider_failure_state(monkeypatch, tmp_path):
    monkeypatch.setenv("NEWS_CACHE_PATH", str(tmp_path / "news-cache.json"))
    monkeypatch.setattr("src.risk_news.fetch_market_news", lambda market: [])
    monkeypatch.setattr("src.risk_news.fetch_market_news_fallback", lambda market: [])
    monkeypatch.setattr(
        "src.risk_news._LAST_OFFICIAL_NEWS_HEALTH",
        {
            "taiwan": {"source_health": [{"provider": "twse", "status": "failed", "item_count": 0}]},
            "us": {"source_health": [{"provider": "sec", "status": "rate_limited", "item_count": 0}]},
        },
    )
    snapshot = build_news_snapshot()
    assert snapshot["intelligence"]["taiwan"]["collection_state"] == "source_failed"
    assert snapshot["intelligence"]["us"]["collection_state"] == "source_failed"
    assert snapshot["intelligence"]["us"]["source_failure_count"] == 1


def test_news_snapshot_binds_explicit_interest_context(monkeypatch, tmp_path):
    monkeypatch.setenv("NEWS_CACHE_PATH", str(tmp_path / "news-cache.json"))
    monkeypatch.setattr(
        "src.risk_news.fetch_market_news",
        lambda market: [{
            "title": "NVIDIA semiconductor outlook",
            "url": "https://www.nasdaq.com/articles/nvda",
        }],
    )
    monkeypatch.setattr("src.risk_news.fetch_market_news_fallback", lambda market: [])

    snapshot = build_news_snapshot(
        tracked_tickers=["NVDA"],
        research_tickers=["NVDA"],
        tracked_sectors=["semiconductor"],
        active_event_topics=["NVIDIA"],
        creator_mentions=["NVIDIA"],
    )

    graph = snapshot["intelligence"]["us"]["interest_graph"]
    assert graph["source_interest"]["research_candidate"] == {"NVDA": 1}
    assert graph["source_interest"]["tracked_sector"] == {"semiconductor": 1}
    assert snapshot["interest_context"]["creator_mentions"] == ["NVIDIA"]


def test_news_snapshot_binds_current_official_event_context(monkeypatch, tmp_path):
    monkeypatch.setenv("NEWS_CACHE_PATH", str(tmp_path / "news-cache.json"))
    def fetch_news(market):
        if market == "us":
            return [{
                "title": "Iran talks move oil markets",
                "url": "https://www.federalreserve.gov/newsevents/pressreleases/a.htm",
            }]
        return [{
            "title": "Taiwan market closes",
            "url": "https://www.twse.com.tw/news/taiwan-close",
        }]

    monkeypatch.setattr("src.risk_news.fetch_market_news", fetch_news)
    monkeypatch.setattr("src.risk_news.fetch_market_news_fallback", lambda market: [])

    snapshot = build_news_snapshot(official_events={
        "items": [{"title": "Iran ceasefire update", "topic_key": "white-house"}],
    })

    assert "iran" in snapshot["interest_context"]["active_event_topics"]
    graph = snapshot["intelligence"]["us"]["interest_graph"]
    assert graph["source_interest"]["active_event"] == {"iran": 1}
