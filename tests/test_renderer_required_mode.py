from src import alert_card_renderer


def test_required_renderer_does_not_silently_send_dark_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("PRSTK_REQUIRE_PLAYWRIGHT", "true")
    monkeypatch.setitem(__import__("sys").modules, "playwright", None)
    try:
        alert_card_renderer.render_alert_card({"title": "test"}, tmp_path / "required.png")
    except RuntimeError as exc:
        assert "Playwright is required" in str(exc)
    else:
        raise AssertionError("required renderer unexpectedly fell back")
