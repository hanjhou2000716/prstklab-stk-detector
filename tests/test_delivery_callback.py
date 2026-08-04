from src.delivery_callback import build_payload


def test_delivery_callback_payload_contains_counts_and_only_failed_hashes(monkeypatch):
    monkeypatch.setenv("TRACE_ID", "prstk-jin10-abcd")
    monkeypatch.setenv("DELIVERY_STATUS", "partial")
    monkeypatch.setenv("DELIVERED_COUNT", "4")
    monkeypatch.setenv("FAILED_COUNT", "1")
    monkeypatch.setenv("FAILED_RECIPIENT_HASHES", "abc123,def456")
    monkeypatch.setenv("RELEASE_ID", "release-123")
    monkeypatch.setenv("SNAPSHOT_ID", "market-123")
    payload = build_payload()
    assert payload["trace_id"] == "prstk-jin10-abcd"
    assert payload["delivery_status"] == "partial"
    assert payload["delivered_count"] == 4
    assert payload["failed_recipient_hashes"] == ["abc123", "def456"]
    assert payload["release_id"] == "release-123"
    assert payload["snapshot_id"] == "market-123"
    assert "chat_id" not in str(payload)
