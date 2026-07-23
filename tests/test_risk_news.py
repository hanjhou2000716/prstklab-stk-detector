from src.risk_news import _news_from_html, sentiment_label


def test_sentiment_labels_cover_fixed_thresholds():
    assert sentiment_label(None) == "資料暫時無法取得"
    assert sentiment_label(9.9) == "極度恐慌"
    assert sentiment_label(10) == "恐慌"
    assert sentiment_label(25) == "中立／偏恐慌"
    assert sentiment_label(51) == "貪婪"
    assert sentiment_label(76) == "極度貪婪"


def test_news_extraction_keeps_only_relevant_unique_article_links():
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
    ]
