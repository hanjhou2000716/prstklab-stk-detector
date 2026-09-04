import pytest

from src.creator_delivery_contract import creator_notification_key, decide_creator_delivery


def test_creator_notification_is_idempotent_and_release_gated() -> None:
    insight = {"episode_key": "gooaye:ep-7", "public_safe": True}
    key = creator_notification_key("gooaye:ep-7")
    result = decide_creator_delivery(insight, release_ready=True, media_available=True, delivery_history=[{"notification_key": key, "status": "delivered"}])
    assert result["allowed"] is False
    assert "already_delivered" in result["reasons"]


def test_creator_media_degrades_to_text_only_after_ready_release(monkeypatch) -> None:
    monkeypatch.setattr("src.creator_delivery_contract.is_active_creator", lambda _creator: True)
    result = decide_creator_delivery({"episode_key": "haojiao:ep-1", "public_safe": True}, release_ready=True, media_available=False)
    assert result["allowed"] is True
    assert result["media_mode"] == "text_only"
    assert result["status"] == "media_degraded"


def test_creator_delivery_rejects_missing_episode_key() -> None:
    with pytest.raises(ValueError):
        creator_notification_key("")
