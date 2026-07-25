from pathlib import Path


def test_mini_app_deploys_both_brand_assets():
    root = Path(__file__).resolve().parents[1]
    page = (root / "site" / "index.html").read_text(encoding="utf-8")

    for filename in ("PRStK-Remove.png", "D.inv-removebg-preview.png"):
        assert (root / "site" / "assets" / filename).is_file()
        assert f"assets/{filename}" in page


def test_mini_app_distinguishes_market_session_from_quote_freshness():
    root = Path(__file__).resolve().parents[1]
    page = (root / "site" / "index.html").read_text(encoding="utf-8")
    app = (root / "site" / "app.js").read_text(encoding="utf-8")

    assert 'id="quote-as-of"' in page
    assert 'id="market-status"' in page
    assert "session-grid" not in page
    assert "renderQuoteFreshness" in app


def test_mini_app_has_visible_index_and_strategy_sections():
    root = Path(__file__).resolve().parents[1]
    page = (root / "site" / "index.html").read_text(encoding="utf-8")
    app = (root / "site" / "app.js").read_text(encoding="utf-8")

    assert 'id="index-list"' in page
    assert 'id="research-list"' in page
    assert "renderQuoteList" in app


def test_mini_app_renders_event_text_without_injecting_untrusted_links():
    root = Path(__file__).resolve().parents[1]
    app = (root / "site" / "app.js").read_text(encoding="utf-8")

    assert "renderEvents" in app
    assert "event.title" in app
    assert "href=\"${event.url}" not in app


def test_mini_app_has_a_detailed_alert_card_and_compact_brief_title():
    root = Path(__file__).resolve().parents[1]
    page = (root / "site" / "index.html").read_text(encoding="utf-8")
    app = (root / "site" / "app.js").read_text(encoding="utf-8")

    assert 'id="alert-card"' in page
    assert 'id="alert-quote-grid"' in page
    assert "renderAlertCard" in app
    assert "event.brief_title" in app


def test_mini_app_integrates_the_alert_into_risk_and_splits_research_by_market():
    root = Path(__file__).resolve().parents[1]
    page = (root / "site" / "index.html").read_text(encoding="utf-8")
    app = (root / "site" / "app.js").read_text(encoding="utf-8")

    assert 'href="#risk">風險' in page
    assert 'href="#market">市場' in page
    assert 'data-market="taiwan"' in page
    assert 'data-market="us"' in page
    assert "activeResearchMarket = \"taiwan\"" in app
    assert "renderBriefing" not in app


def test_mini_app_numbers_taiwan_and_us_news_independently():
    root = Path(__file__).resolve().parents[1]
    page = (root / "site" / "index.html").read_text(encoding="utf-8")
    app = (root / "site" / "app.js").read_text(encoding="utf-8")

    assert 'id="taiwan-news" class="news-list numbered-list"' in page
    assert 'id="us-news" class="news-list numbered-list"' in page
    assert "stories.slice(0, 3)" in app


def test_mini_app_orders_sections_and_uses_strategy_match_scores():
    root = Path(__file__).resolve().parents[1]
    page = (root / "site" / "index.html").read_text(encoding="utf-8")
    app = (root / "site" / "app.js").read_text(encoding="utf-8")

    assert page.index('id="risk"') < page.index('id="market"') < page.index('id="research"') < page.index('id="news"')
    assert "價值投資" in page
    assert "strategyScore" in app
    assert "共振相符度" in app
    assert "items.slice(0, 5)" in app


def test_mini_app_labels_intraday_and_daily_quote_freshness():
    root = Path(__file__).resolve().parents[1]
    app = (root / "site" / "app.js").read_text(encoding="utf-8")

    assert "quote_basis" in app
    assert "quoteFreshness" in app
