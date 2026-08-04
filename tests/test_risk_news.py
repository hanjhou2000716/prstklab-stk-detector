from src.risk_news import (
    classify_news_market,
    _filter_market_news,
    _market_news_rss_url,
    _market_risk,
    _news_from_html,
    _news_from_rss,
    _parse_taifex_vix_file,
    build_news_snapshot,
    build_risk_snapshot,
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
    assert parsed["source_label"] == "臺灣期貨交易所"
    assert parsed["percentile"] is None
    assert parsed["stage"] == "極度恐慌"


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


def test_market_news_rss_parser_keeps_market_specific_links():
    xml = """
    <rss><channel>
      <item><title>US Nasdaq outlook</title><link>https://news.google.com/rss/articles/us1</link></item>
      <item><title>Taiwan semiconductor outlook</title><link>https://news.google.com/rss/articles/tw1</link></item>
    </channel></rss>
    """
    stories = _news_from_rss(xml, "us")
    assert stories[0]["url"].endswith("/us1")
    assert stories[0]["source"] == "Google News｜美股線索"


def test_duplicate_market_payload_uses_separate_fallback_feeds(monkeypatch):
    duplicate = [{"title": "same", "url": "https://news.cnyes.com/news/id/1"}]
    monkeypatch.setattr("src.risk_news.fetch_market_news", lambda market: duplicate.copy())
    monkeypatch.setattr(
        "src.risk_news.fetch_market_news_fallback",
        lambda market: [{"title": market, "url": f"https://news.google.com/rss/articles/{market}"}],
    )

    snapshot = build_news_snapshot()

    assert snapshot["taiwan"][0]["title"] == "taiwan"
    assert snapshot["us"][0]["title"] == "us"
    assert all(item.get("fallback_used") for item in snapshot["source_health"])


def test_news_cache_prevents_empty_us_panel_after_transient_outage(monkeypatch, tmp_path):
    cache_path = tmp_path / "news-cache.json"
    monkeypatch.setenv("NEWS_CACHE_PATH", str(cache_path))
    fresh = {
        "taiwan": [{"title": "Taiwan", "url": "https://example.test/tw"}],
        "us": [{"title": "US", "url": "https://example.test/us"}],
    }
    monkeypatch.setattr("src.risk_news.fetch_market_news", lambda market: fresh[market])
    monkeypatch.setattr("src.risk_news.fetch_market_news_fallback", lambda market: [])
    first = build_news_snapshot()
    assert first["us"][0]["title"] == "US"
    assert cache_path.exists()

    def unavailable(_market):
        raise RuntimeError("temporary outage")

    monkeypatch.setattr("src.risk_news.fetch_market_news", unavailable)
    second = build_news_snapshot()

    assert second["us"][0]["title"] == "US"
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


def test_market_classifier_routes_fed_and_lai_to_their_own_tabs():
    fed = {"title": "Federal Reserve keeps rates unchanged", "url": "https://example.test/fed"}
    lai = {"title": "Taiwan President Lai Ching-te addresses parliament", "url": "https://example.test/lai"}

    assert classify_news_market(fed)["market_scope"] == "us"
    assert classify_news_market(lai)["market_scope"] == "taiwan"
    assert _filter_market_news([fed, lai], "taiwan")[0]["title"].startswith("Taiwan")
    assert _filter_market_news([fed, lai], "us")[0]["title"].startswith("Federal")


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
