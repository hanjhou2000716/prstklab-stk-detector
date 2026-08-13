"""P0-16 delivery lineage and recipient-isolation contracts."""

from src.creator_photo_delivery import build_creator_receipt
from src.delivery_callback import build_payload


def test_receipt_binds_release_snapshot_and_hashed_recipient(monkeypatch):
    monkeypatch.setenv("RELEASE_ID", "release-16")
    monkeypatch.setenv("SNAPSHOT_ID", "snapshot-16")
    monkeypatch.setenv("TRACE_ID", "trace-16")
    monkeypatch.setenv("ALERT_ID", "alert-16")
    monkeypatch.setenv("DELIVERY_MODE", "photo")
    monkeypatch.setenv("DELIVERY_STATUS", "delivered")
    monkeypatch.setenv("DELIVERED_COUNT", "1")
    monkeypatch.setenv("FAILED_COUNT", "0")
    monkeypatch.setenv("FAILED_RECIPIENT_HASHES", "")
    payload = build_payload()
    assert payload["release_id"] == "release-16"
    assert payload["snapshot_id"] == "snapshot-16"
    assert payload["alert_id"] == "alert-16"
    assert payload["delivery_mode"] == "photo"
    assert payload["delivered_count"] == 1


def test_receipt_never_persists_raw_chat_id():
    receipt = build_creator_receipt(
        {"episode_key": "creator:ep-16"},
        release_id="release-16",
        creator_snapshot_id="snapshot-16",
        chat_id="8869592162",
        status="delivered",
        message_id=16,
    )
    assert receipt["recipient_hash"] == "7a30574fc065a0a7"
    assert "chat_id" not in receipt
    assert receipt["release_id"] == "release-16"
    assert receipt["creator_snapshot_id"] == "snapshot-16"


def test_failed_recipient_isolated_from_successful_receipt():
    delivered = build_creator_receipt(
        {"episode_key": "creator:ep-16"},
        release_id="release-16", creator_snapshot_id="snapshot-16",
        chat_id="8869592162", status="delivered", message_id=16,
    )
    failed = build_creator_receipt(
        {"episode_key": "creator:ep-16"},
        release_id="release-16", creator_snapshot_id="snapshot-16",
        chat_id="8317010256", status="retryable", error_class="telegram_429",
    )
    assert delivered["delivery_status"] == "delivered"
    assert failed["delivery_status"] == "retryable"
    assert delivered["recipient_hash"] != failed["recipient_hash"]
