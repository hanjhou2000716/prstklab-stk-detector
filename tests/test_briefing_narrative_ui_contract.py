from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_mini_app_uses_direct_card_fields_without_duplicate_narrative_blocks() -> None:
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
    assert "renderLabeledValue" in app
    assert "morning-analysis-highlights" not in app
    assert "morning-analysis-details" not in app
    assert "展開詳解" not in app
    assert "narrative.evidence_refs" not in app


def test_narrative_css_wraps_long_evidence_for_narrow_cards() -> None:
    styles = (ROOT / "site" / "styles.css").read_text(encoding="utf-8")
    assert ".briefing-evidence" in styles
    assert ".morning-analysis-highlights" not in styles
    assert ".morning-analysis-details" not in styles
    assert "overflow-wrap: anywhere" in styles


def test_taiwan_cash_futures_and_official_statistics_use_two_compact_cards() -> None:
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "site" / "styles.css").read_text(encoding="utf-8")
    assert 'item.layout === "taiwan_pair_v2"' in app
    assert 'item.layout === "taiwan_stats_v2"' in app
    assert "marketCardProjection.instruments" in app
    assert ".taiwan-market-pair" in styles
    assert ".taiwan-market-stats" in styles
    assert ".taiwan-market-takeaway" in styles
    assert "@media (max-width: 520px)" in styles


def test_us_cards_use_compact_market_scoped_layout_and_keep_quote_evidence():
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "site" / "styles.css").read_text(encoding="utf-8")
    cards = (ROOT / "src" / "briefing_cards.py").read_text(encoding="utf-8")
    assert 'item.layout === "us_cash_v2"' in app
    assert 'item.layout === "us_futures_sox_v2"' in app
    assert '"version": "us-market-cards-v2"' in cards
    assert '"market_scope": "us"' in cards
    assert '"reference_facts": reference_futures' in cards
    assert '"supplementary_facts": [sox_fact]' in cards
    assert ".us-market-cash" in styles
    assert ".us-market-reference" in styles
    assert ".us-market-sox" in styles
    assert "contract_basis" in app
    assert "quoteMovementPrefix(rawPercent)" in app
    assert "projectionCards ||" in app
    assert '["taiwan", "us"].includes(marketCardProjection?.market_scope)' in app
    assert "marketCardProjection.market_scope === \"taiwan\"" in app


def test_four_reports_use_the_single_lower_sentiment_panel():
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    cards = (ROOT / "src" / "briefing_cards.py").read_text(encoding="utf-8")
    assert 'class="briefing-market-sentiment"' not in app
    assert 'id="market-sentiment-card"' in html
    assert '"sentiments": list(market_sentiments or [])' in cards


def test_routine_news_is_integrated_into_briefing_and_not_a_separate_alert_card():
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    digest = (ROOT / "src" / "market_digest.py").read_text(encoding="utf-8")
    assert "briefing-overview-news-label" in app
    assert "briefing-overview-news-sentence" in app
    assert 'new Set(["morning", "pre_open", "post_close", "us_premarket"])' in app
    assert 'id="alert-session-news"' not in html
    assert "session_news_summary" in digest
    assert '"historical_reference"].includes(state)' in app
    assert 'statisticIcons = { turnover: "💰", breadth: "📊", institutions: "🏦" }' in app
    assert "safeHttpsUrl(session.source_url)" in app
    assert 'class="us-market-date-footer"' in app
