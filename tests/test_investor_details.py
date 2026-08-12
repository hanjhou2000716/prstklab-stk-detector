from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_technical_evidence_is_collapsed_by_default():
    page = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    assert '<details class="technical-details">' in page
    assert 'class="technical-details" open' not in page


def test_vix_investor_view_uses_readable_time():
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
    assert "const vixFetchedAt = traceTime(vix.fetched_at);" in app
    assert "toLocaleString(\"zh-TW\"" in app


def test_vix_investor_view_exposes_time_stage_and_percentile_state():
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "site" / "styles.css").read_text(encoding="utf-8")
    assert "資料時間暫時無法取得" in app
    assert "歷史百分位待取得" in app
    assert "risk-metric-time" in app
    assert ".risk-metric-card small.risk-metric-time" in styles
