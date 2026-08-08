from pathlib import Path

from src import photo_smoke_test
from src.alert_card_renderer import fallback_card


def test_photo_smoke_scopes_delivery_and_validates_dimensions(monkeypatch, tmp_path):
    class Settings:
        telegram_bot_token = "token"
        telegram_chat_ids = ("one",)
        dashboard_url = "https://example.test/app"

    monkeypatch.setattr(photo_smoke_test, "get_settings", lambda: Settings())

    def fake_render(_alert, output):
        path = Path(output)
        return fallback_card(path)

    monkeypatch.setattr(photo_smoke_test, "render_alert_card", fake_render)
    captured = {}

    def fake_send_photo_briefs(**kwargs):
        captured.update(kwargs)
        return (type("Receipt", (), {"status": "delivered"})(),)

    monkeypatch.setattr(photo_smoke_test, "send_photo_briefs", fake_send_photo_briefs)
    assert photo_smoke_test.run() == 0
    assert captured["chat_ids"] == ("one",)
    assert captured["caption"] == photo_smoke_test.CAPTION
