from __future__ import annotations

from pathlib import Path

from src.creator_notification import creator_telegram_caption, creator_text_caption, deliver_creator_episode
from src.telegram_client import TelegramDelivery, TelegramResult

INSIGHT = {
    "creator_name": "Gooaye",
    "content_origin": "gooaye",
    "episode_key": "gooaye:ep-1",
    "episode_title": "AI 與半導體風險觀察",
    "key_takeaways": ["等待官方資料核對"],
    "public_safe": True,
}


def _enable_test_creator_lane(monkeypatch) -> None:
    """Keep delivery mechanics covered without re-enabling production sources."""
    monkeypatch.setattr("src.creator_delivery_contract.is_active_creator", lambda _creator: True)
    monkeypatch.setattr("src.creator_notification.creator_ids", lambda *, enabled_only=False: ("gooaye",))


def test_captions_respect_photo_and_text_limits() -> None:
    assert len(creator_telegram_caption(INSIGHT)) <= 40
    assert len(creator_text_caption(INSIGHT)) <= 40
    assert "<" not in creator_telegram_caption({**INSIGHT, "episode_title": "x < y"})


def test_creator_missing_media_degrades_to_text_and_keeps_deep_link(tmp_path: Path, monkeypatch) -> None:
    _enable_test_creator_lane(monkeypatch)
    calls: list[dict] = []

    def fake_text(**kwargs):
        calls.append(kwargs)
        return (TelegramDelivery("8869592162", TelegramResult(44)),)

    result = deliver_creator_episode(
        INSIGHT,
        release_id="release-1",
        creator_snapshot_id="creator-1",
        mini_app_url="https://example.test/app",
        release_ready=True,
        token="token",
        chat_ids=("8869592162",),
        media_path=tmp_path / "missing.png",
        text_sender=fake_text,
    )
    assert result["status"] == "media_degraded"
    assert result["media_mode"] == "text_only"
    assert result["receipts"][0]["delivery_status"] == "delivered"
    assert "view=creator" in calls[0]["target_url"]


def test_creator_photo_success_returns_lineage_receipt(tmp_path: Path, monkeypatch) -> None:
    _enable_test_creator_lane(monkeypatch)
    image = tmp_path / "summary.png"
    image.write_bytes(b"png")

    def fake_photo(**kwargs):
        return (type("Receipt", (), {
            "status": "delivered", "message_id": 12,
            "telegram_file_id_hash": "a" * 12, "error_class": None,
        })(),)

    result = deliver_creator_episode(
        INSIGHT,
        release_id="release-1",
        creator_snapshot_id="creator-1",
        mini_app_url="https://example.test/app",
        release_ready=True,
        token="token",
        chat_ids=("8869592162",),
        media_path=image,
        photo_sender=fake_photo,
    )
    assert result["status"] == "delivered"
    assert result["media_mode"] == "photo"
    assert result["receipts"][0]["release_id"] == "release-1"
    assert result["receipts"][0]["recipient_hash"] == "7a30574fc065a0a7"


def test_creator_delivery_is_idempotent_across_delivery_status(monkeypatch) -> None:
    _enable_test_creator_lane(monkeypatch)
    result = deliver_creator_episode(
        INSIGHT,
        release_id="release-1",
        creator_snapshot_id="creator-1",
        mini_app_url="https://example.test/app",
        release_ready=True,
        token="token",
        chat_ids=("8869592162",),
        delivery_history=[{
            "notification_key": "creator:gooaye:ep-1:initial",
            "delivery_status": "delivered",
        }],
    )
    assert result["allowed"] is False
    assert "already_delivered" in result["reasons"]
