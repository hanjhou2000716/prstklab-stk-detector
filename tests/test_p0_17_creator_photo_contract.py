"""P0-17 creator photo delivery must fail closed on renderer/API failure."""

from pathlib import Path

from src.creator_notification import deliver_creator_episode
from src.telegram_client import PhotoDeliveryReceipt, TelegramDelivery, TelegramResult

INSIGHT = {"episode_key": "creator:photo-17", "creator_name": "Gooaye", "episode_title": "market", "public_safe": True}


def test_renderer_failure_does_not_send_blank_photo_and_keeps_receipt(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("src.creator_delivery_contract.is_active_creator", lambda _creator: True)
    image = tmp_path / "candidate.png"
    image.write_bytes(b"not-a-valid-render")
    photo_calls: list[dict] = []
    text_calls: list[dict] = []

    def failed_photo(**kwargs):
        photo_calls.append(kwargs)
        return (PhotoDeliveryReceipt(
            alert_id="creator:photo-17", release_id="release-17", snapshot_id="snapshot-17",
            chat_id_hash="hash", status="failed", error_class="renderer_invalid_png",
        ),)

    def text_fallback(**kwargs):
        text_calls.append(kwargs)
        return (TelegramDelivery("8869592162", TelegramResult(17)),)

    result = deliver_creator_episode(
        INSIGHT, release_id="release-17", creator_snapshot_id="snapshot-17",
        mini_app_url="https://example.test/app", release_ready=True,
        token="token", chat_ids=("8869592162",), media_path=image,
        photo_sender=failed_photo, text_sender=text_fallback,
    )
    assert photo_calls and text_calls
    assert result["status"] == "media_degraded"
    assert result["media_mode"] == "text_only"
    assert result["receipts"][0]["error_class"] is None
    assert result["receipts"][0]["delivery_status"] == "delivered"


def test_missing_media_is_explicitly_degraded_not_silent(monkeypatch):
    monkeypatch.setattr("src.creator_delivery_contract.is_active_creator", lambda _creator: True)
    calls: list[dict] = []

    def text_fallback(**kwargs):
        calls.append(kwargs)
        return (TelegramDelivery("8869592162", TelegramResult(18)),)

    result = deliver_creator_episode(
        INSIGHT, release_id="release-17", creator_snapshot_id="snapshot-17",
        mini_app_url="https://example.test/app", release_ready=True,
        token="token", chat_ids=("8869592162",), media_path=None,
        text_sender=text_fallback,
    )
    assert result["status"] == "media_degraded"
    assert result["reasons"] == ["media_unavailable"]
    assert calls
