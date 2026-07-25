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
    assert "交易日（非報價基準日）" in page
    assert "renderQuoteFreshness" in app


def test_mini_app_has_visible_index_and_strategy_sections():
    root = Path(__file__).resolve().parents[1]
    page = (root / "site" / "index.html").read_text(encoding="utf-8")
    app = (root / "site" / "app.js").read_text(encoding="utf-8")

    assert 'id="index-list"' in page
    assert '<details class="detail-panel" open>' in page
    assert "renderIndices" in app


def test_mini_app_accepts_only_trusted_official_event_links():
    root = Path(__file__).resolve().parents[1]
    app = (root / "site" / "app.js").read_text(encoding="utf-8")

    assert "isTrustedEventUrl" in app
    assert ".federalreserve.gov" in app
    assert ".bls.gov" in app
    assert ".bea.gov" in app
