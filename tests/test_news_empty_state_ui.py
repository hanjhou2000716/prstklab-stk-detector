from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_news_empty_state_distinguishes_no_event_from_provider_failure_and_cache():
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "site" / "styles.css").read_text(encoding="utf-8")

    assert "const newsEmptyState = (health)" in app
    assert 'status === "failed"' in app
    assert 'status === "stale"' in app
    assert 'status === "no_event"' in app
    assert 'class=\"empty news-empty-state\"' in app
    assert "newsHealthFor = (market)" in app
    assert ".news-empty-state" in styles


def test_news_empty_state_never_displays_provider_error_payload_verbatim():
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")

    assert "health.data_gap" not in app
    assert "health.error" not in app
    assert 'escapeHtml(state.detail)' in app
