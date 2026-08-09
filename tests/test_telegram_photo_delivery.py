import json

from src import telegram_client
from src.telegram_client import send_photo_brief, send_photo_briefs


class Response:
    status_code = 200
    ok = True
    def json(self):
        return {"ok": True, "result": {"message_id": 42}}

def test_photo_delivery_uses_one_message_and_deep_link(monkeypatch, tmp_path):
    photo = tmp_path / "card.png"
    photo.write_bytes(b"png")
    captured = {}
    def post(url, **kwargs):
        captured.update(url=url, kwargs=kwargs)
        return Response()
    monkeypatch.setattr(telegram_client.requests, "post", post)
    receipt = send_photo_brief(token="secret", chat_id="123", caption="🔵 測試｜觀察", photo_path=photo, mini_app_url="https://example.test/app", alert_id="a1", release_id="r1", snapshot_id="s1")
    assert receipt.status == "delivered" and receipt.message_id == 42
    assert captured["url"].endswith("/sendPhoto")
    assert "photo" in captured["kwargs"]["files"]
    payload = json.loads(captured["kwargs"]["data"]["reply_markup"])
    assert "alert=a1" in payload["inline_keyboard"][0][0]["web_app"]["url"]


def test_photo_broadcast_isolates_one_failed_recipient(monkeypatch, tmp_path):
    photo = tmp_path / "card.png"
    photo.write_bytes(b"png")
    calls = []

    def fake_send(**kwargs):
        calls.append(kwargs["chat_id"])
        if kwargs["chat_id"] == "blocked":
            raise telegram_client.TelegramError("bot was blocked by the user")
        return telegram_client.PhotoDeliveryReceipt("a1", "r1", "s1", "ok", "delivered", message_id=7)

    monkeypatch.setattr(telegram_client, "send_photo_brief", fake_send)
    receipts = send_photo_briefs(
        token="secret", chat_ids=("blocked", "ok"), caption="測試", photo_path=photo,
        mini_app_url="https://example.test/app", alert_id="a1", release_id="r1", snapshot_id="s1",
    )
    assert calls == ["blocked", "ok"]
    assert [item.status for item in receipts] == ["failed", "delivered"]


def test_photo_delivery_validates_inputs(tmp_path):
    import pytest
    photo = tmp_path / "card.png"
    photo.write_bytes(b"png")
    with pytest.raises(ValueError):
        send_photo_brief(token="t", chat_id="1", caption="", photo_path=photo, mini_app_url="https://example.test", alert_id="a", release_id="r", snapshot_id="s")
    with pytest.raises(ValueError):
        send_photo_brief(token="t", chat_id="1", caption="ok", photo_path=photo, mini_app_url="http://example.test", alert_id="a", release_id="r", snapshot_id="s")
    with pytest.raises(FileNotFoundError):
        send_photo_brief(token="t", chat_id="1", caption="ok", photo_path=tmp_path / "missing", mini_app_url="https://example.test", alert_id="a", release_id="r", snapshot_id="s")


def test_photo_delivery_records_api_error_and_rate_limit_retry(monkeypatch, tmp_path):
    photo = tmp_path / "card.png"
    photo.write_bytes(b"png")
    sleeps = []

    class Response:
        ok = False
        status_code = 429
        def json(self):
            return {"ok": False, "parameters": {"retry_after": 1}}

    monkeypatch.setattr(telegram_client.requests, "post", lambda *args, **kwargs: Response())
    monkeypatch.setattr(telegram_client, "sleep", sleeps.append)
    receipt = send_photo_brief(token="t", chat_id="1", caption="ok", photo_path=photo, mini_app_url="https://example.test", alert_id="a", release_id="r", snapshot_id="s")
    assert receipt.status == "failed" and receipt.error_class == "temporary_transport"
    assert sleeps == [1, 1]


def test_send_photo_briefs_rejects_empty_recipients(tmp_path):
    import pytest
    with pytest.raises(ValueError, match="recipient"):
        send_photo_briefs(token="t", chat_ids=(), caption="ok", photo_path=tmp_path / "x", mini_app_url="https://example.test", alert_id="a", release_id="r", snapshot_id="s")
