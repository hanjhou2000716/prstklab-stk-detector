from src.risk_news import (
    _market_risk,
    _news_from_html,
    _parse_taifex_vix_file,
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
