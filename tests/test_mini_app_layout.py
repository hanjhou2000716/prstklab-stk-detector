from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_mini_app_uses_the_revised_briefing_structure():
    page = (ROOT / "site" / "index.html").read_text(encoding="utf-8")

    assert "D.inv System" in page
    assert "稜量速報系統" in page
    assert 'id="market-focus"' in page
    assert "session-grid" not in page
    assert "總經與公開節目" not in page


def test_mini_app_uses_a_light_neutral_palette_and_balanced_logo_rules():
    styles = (ROOT / "site" / "styles.css").read_text(encoding="utf-8")

    assert "color-scheme: light" in styles
    assert "--canvas: #eeece6" in styles
    assert ".brand-prstk" in styles
    assert ".brand-dinv" in styles


def test_mini_app_renders_market_focus_and_macro_fgi_subscores():
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")

    assert "const renderFocus" in app
    assert "sentiment.sub_scores" in app
    assert "renderFocus(snapshot.events)" in app
