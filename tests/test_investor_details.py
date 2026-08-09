from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_technical_evidence_is_collapsed_by_default():
    page = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    assert '<details class="technical-details">' in page
    assert 'class="technical-details" open' not in page


def test_vix_advanced_metadata_is_collapsed():
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
    assert 'class="metric-details"' in app
    assert '<details class="metric-details" open>' not in app
