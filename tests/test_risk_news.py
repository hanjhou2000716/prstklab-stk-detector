from src.risk_news import _market_risk, _news_from_html, _parse_taifex_vix_file, sentiment_label


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

    assert _parse_taifex_vix_file(content) == {
        "value": 36.21,
        "date": "2026-07-23",
        "source_label": "臺灣期貨交易所",
    }


def test_taifex_fallback_keeps_taiwan_vix_available(monkeypatch):
    monkeypatch.setattr("src.risk_news._latest_close", lambda symbol: (_ for _ in ()).throw(ValueError("unavailable")))
    result = _market_risk("台股", "^VIXTWN", fallback=lambda: {
        "value": 36.21, "date": "2026-07-23", "change_percent": 1.2, "source_label": "臺灣期貨交易所",
    })

    assert result["vix"]["source_label"] == "臺灣期貨交易所"
    assert result["errors"] == []
