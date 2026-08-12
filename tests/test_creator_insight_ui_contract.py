from pathlib import Path


def test_creator_insight_panel_is_safe_and_optional():
    page = Path("site/index.html").read_text(encoding="utf-8")
    app = Path("site/app.js").read_text(encoding="utf-8")
    assert 'id="creator-intelligence"' in page
    assert "const renderCreatorInsights" in app
    assert "snapshot.creator_release || snapshot.creator_intelligence" in app
    assert "raw_body" not in app
