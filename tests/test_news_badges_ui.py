from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_news_cards_render_readable_interest_badges_instead_of_raw_reason_codes():
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "site" / "styles.css").read_text(encoding="utf-8")

    assert "const newsBadgeLabels = (story)" in app
    for label in ("官方", "研究標的", "追蹤標的", "Creator 提及", "產業", "總經"):
        assert f'"{label}"' in app
    assert 'class="news-badges"' in app
    assert "news-reason-detail" in app
    assert ".news-badges" in styles
    assert ".news-badge-official" in styles


def test_news_badges_keep_reason_details_escaped_and_source_visible():
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")

    assert 'const reasonDetails = (story.relevance_reasons || []).slice(0, 2).map((reason) => escapeHtml(reason))' in app
    assert 'const source = escapeHtml(story.source || story.provider_name || "公開來源")' in app
