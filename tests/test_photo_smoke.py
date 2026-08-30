from src import photo_smoke_test


def test_legacy_photo_smoke_scopes_text_delivery(monkeypatch):
    class Settings:
        telegram_bot_token = "token"
        telegram_chat_ids = ("one",)
        dashboard_url = "https://example.test/app"

    monkeypatch.setattr(photo_smoke_test, "get_settings", lambda: Settings())

    captured = {}

    def fake_send_text_briefs_audited(**kwargs):
        captured.update(kwargs)
        return (type("Receipt", (), {"status": "delivered"})(),)

    monkeypatch.setattr(photo_smoke_test, "send_text_briefs_audited", fake_send_text_briefs_audited)
    assert photo_smoke_test.run() == 0
    assert captured["chat_ids"] == ("one",)
    assert captured["text"] == photo_smoke_test.CAPTION
