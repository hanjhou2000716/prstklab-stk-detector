from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_mini_app_uses_the_revised_briefing_structure():
    page = (ROOT / "site" / "index.html").read_text(encoding="utf-8")

    assert "D.inv System" in page
    assert "稜量速報系統" in page
    assert 'id="market-focus"' in page
    assert 'id="briefing-report"' in page
    assert "session-grid" not in page
    assert "總經與公開節目" not in page


def test_mini_app_uses_a_light_neutral_palette_and_balanced_logo_rules():
    styles = (ROOT / "site" / "styles.css").read_text(encoding="utf-8")

    assert "color-scheme: light" in styles
    assert "--canvas: #e8e8e4" in styles
    assert "--orange: #c77b43" in styles
    assert ".brand-prstk" in styles
    assert ".brand-dinv" in styles


def test_mini_app_renders_compact_market_risk_cards_without_subscores():
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")

    assert "const renderFocus" in app
    assert "risk-metric-card" in app
    assert "sentiment.sub_scores" not in app
    assert "renderFocus(snapshot.events, externalAlert)" in app
    assert "renderBriefing(snapshot.briefing, snapshot.generated_at)" in app


def test_mini_app_uses_strategy_drawers_and_places_source_health_after_sentiment():
    page = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    styles = (ROOT / "site" / "styles.css").read_text(encoding="utf-8")

    assert 'class="research-drawer"' in page
    assert "<details" in page
    assert "動能狙擊" in page
    assert ".research-drawer[open] summary" in styles
    assert "#risk > .panel:not(.source-health-panel) { order: 3; }" in styles
    assert ".source-health-panel { order: 4; }" in styles


def test_source_health_is_a_collapsible_card_with_a_warming_state():
    page = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "site" / "styles.css").read_text(encoding="utf-8")

    assert '<details id="source-health"' in page
    assert 'source.status === "warming" ? "建檔中"' in app
    assert ".source-status.warming" in styles


def test_quote_provenance_uses_the_compact_provider_and_time_format():
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")

    assert "const compactQuoteMeta" in app
    assert 'raw.includes("Yahoo") ? "Yahoo"' in app
    assert "const label = !clock" in app
    assert "return `${label} | ${time}${freshness}`" in app
    assert "Yahoo Finance public daily quote" not in app


def test_mini_app_hides_empty_event_trace_and_has_a_legacy_health_fallback():
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")

    assert "container.hidden = container.childElementCount === 0" in app
    assert "此市場快照建立於健康狀態欄位上線前" in app
    assert "renderSourceHealth(snapshot.source_health, snapshot)" in app
