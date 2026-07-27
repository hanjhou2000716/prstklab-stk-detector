import pytest

from src.telegram_client import mini_app_button, mini_app_menu_button, send_briefs, validate_brief


def test_accepts_30_character_brief():
    validate_brief("測" * 30)


def test_rejects_over_30_character_brief():
    with pytest.raises(ValueError, match="超過 30 字"):
        validate_brief("測" * 31)


def test_rejects_blank_brief():
    with pytest.raises(ValueError, match="不可空白"):
        validate_brief("   ")


def test_mini_app_button_uses_telegram_web_app_field():
    assert mini_app_button("https://example.github.io/app/") == {
        "text": "📡 開啟稜量速報系統",
        "web_app": {"url": "https://example.github.io/app/"},
    }


def test_mini_app_button_rejects_non_https_url():
    with pytest.raises(ValueError, match="HTTPS"):
        mini_app_button("http://example.test/app")


def test_mini_app_menu_button_uses_persistent_web_app_shape():
    assert mini_app_menu_button("https://example.github.io/app/") == {
        "type": "web_app",
        "text": "稜量系統",
        "web_app": {"url": "https://example.github.io/app/"},
    }


def test_send_briefs_delivers_to_each_configured_recipient(monkeypatch):
    calls = []

    class Response:
        ok = True

        @staticmethod
        def json():
            return {"ok": True, "result": {"message_id": 1}}

    def fake_post(url, json, timeout):
        calls.append((url, json["chat_id"]))
        return Response()

    monkeypatch.setattr("src.telegram_client.requests.post", fake_post)
    results = send_briefs(
        token="token",
        chat_ids=("100", "200"),
        text="測試快報",
        dashboard_url="https://example.github.io/app/",
    )

    assert len(results) == 2
    assert all(result.delivered for result in results)
    assert [chat_id for _, chat_id in calls] == ["100", "200"]


def test_send_briefs_keeps_other_recipients_running_when_one_has_not_started_bot(monkeypatch):
    class Response:
        def __init__(self, chat_id):
            self.ok = chat_id != "missing"

        def json(self):
            if self.ok:
                return {"ok": True, "result": {"message_id": 1}}
            return {"ok": False, "description": "Bad Request: chat not found"}

    monkeypatch.setattr(
        "src.telegram_client.requests.post",
        lambda url, json, timeout: Response(json["chat_id"]),
    )

    results = send_briefs(
        token="token",
        chat_ids=("available", "missing", "also-available"),
        text="市場快報",
        dashboard_url="https://example.github.io/app/",
    )

    assert [result.delivered for result in results] == [True, False, True]
    assert results[1].error == "Bad Request: chat not found"
