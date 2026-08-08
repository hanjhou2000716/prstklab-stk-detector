import pytest

from src import delivery_callback
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


def test_delivery_callback_skips_when_url_is_not_configured(monkeypatch):
    monkeypatch.delenv("RAILWAY_STATUS_URL", raising=False)
    assert delivery_callback.send_callback() is False


def test_delivery_callback_requires_trace_and_secret(monkeypatch):
    monkeypatch.setenv("RAILWAY_STATUS_URL", "https://railway.example")
    monkeypatch.delenv("TRACE_ID", raising=False)
    monkeypatch.delenv("RAILWAY_STATUS_SHARED_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="TRACE_ID"):
        delivery_callback.send_callback()


def test_delivery_callback_posts_signed_payload(monkeypatch):
    monkeypatch.setenv("RAILWAY_STATUS_URL", "https://railway.example/")
    monkeypatch.setenv("TRACE_ID", "trace-1")
    monkeypatch.setenv("RAILWAY_STATUS_SHARED_SECRET", "secret")
    captured = {}

    class Response:
        def raise_for_status(self):
            captured["raised"] = True

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(delivery_callback.requests, "post", fake_post)
    assert delivery_callback.send_callback() is True
    assert captured["url"] == "https://railway.example/delivery-status"
    assert captured["headers"]["X-PRSTK-Signature"].startswith("sha256=")
    assert captured["raised"] is True
