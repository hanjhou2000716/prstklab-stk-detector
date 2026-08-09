from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_technical_evidence_is_collapsed_by_default():
    page = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    assert '<details class="technical-details">' in page
    assert 'class="technical-details" open' not in page


def test_vix_investor_view_does_not_expose_fetch_timestamp_or_missing_percentile_placeholder():
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
    assert "vix.fetched_at" not in app
    assert "歷史百分位待取得" not in app
    assert "歷史百分位未取得" not in app
