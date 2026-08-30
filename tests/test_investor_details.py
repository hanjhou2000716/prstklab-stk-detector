from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_technical_evidence_is_collapsed_by_default():
    page = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    assert 'class="technical-details"' in page
    assert 'class="technical-details" open' not in page


def test_vix_investor_view_keeps_stage_and_optional_percentile_without_engineering_time():
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
    assert "const vixStage" in app
    assert "const vixPercentile" in app
    assert "vixTime" not in app
    assert "const vixFetchedAt" not in app


def test_vix_engineering_time_style_remains_available_for_non_investor_diagnostics():
    styles = (ROOT / "site" / "styles.css").read_text(encoding="utf-8")
    assert ".risk-metric-card small.risk-metric-time" in styles
