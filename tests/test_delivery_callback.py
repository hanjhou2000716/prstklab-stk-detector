import hashlib
import json

import pytest

from src.delivery_callback import build_payload, send_callback


def test_delivery_callback_payload_contains_counts_and_only_failed_hashes(monkeypatch):
    monkeypatch.setenv("TRACE_ID", "prstk-jin10-abcd")
    monkeypatch.setenv("DELIVERY_STATUS", "partial")
    monkeypatch.setenv("DELIVERED_COUNT", "4")
    monkeypatch.setenv("FAILED_COUNT", "1")
    monkeypatch.setenv("FAILED_RECIPIENT_HASHES", "abc123,def456")
    monkeypatch.setenv("RELEASE_ID", "release-123")
    monkeypatch.setenv("SNAPSHOT_ID", "market-123")
    monkeypatch.setenv("DELIVERY_RECEIPT_KIND", "production")
    monkeypatch.setenv("NOTIFICATION_KEYS", "n-1,n-2,n-1")
    payload = build_payload()
    assert payload["trace_id"] == "prstk-jin10-abcd"
    assert payload["delivery_status"] == "partial"
    assert payload["delivered_count"] == 4
    assert payload["failed_recipient_hashes"] == ["abc123", "def456"]
    assert payload["release_id"] == "release-123"
    assert payload["snapshot_id"] == "market-123"
    assert payload["receipt_kind"] == "production"
    assert payload["notification_keys"] == ["n-1", "n-2"]
    assert "chat_id" not in str(payload)


def test_delivery_callback_preserves_release_bound_financialjuice_trace(monkeypatch):
    monkeypatch.setenv("TRACE_ID", "brief-fj-trace")
    monkeypatch.setenv("DELIVERY_STATUS", "delivered")
    monkeypatch.setenv("DELIVERED_COUNT", "1")
    monkeypatch.setenv("FAILED_COUNT", "0")
    monkeypatch.setenv("RELEASE_ID", "release-fj-1")
    monkeypatch.setenv("SNAPSHOT_ID", "market-fj-1")
    digest = hashlib.sha256(b"fj-observation").hexdigest()
    monkeypatch.setenv("FINANCIALJUICE_TRACE", json.dumps({
        "observation_id_hash": digest,
        "item_id": "fj-item-1",
        "event_cluster_key": "cluster-fj-1",
        "vendor_importance": 9,
        "prstk_risk": {"prstk_risk_level": "R2"},
        "notification_reason": "vendor_priority_importance_ge_8",
        "release_id": "release-fj-1",
        "snapshot_id": "market-fj-1",
        "delivery_status": "delivered",
    }))
    payload = build_payload()
    trace = payload["financialjuice_delivery_trace"]
    assert trace["observation_id_hash"] == digest
    assert trace["release_id"] == "release-fj-1"
    assert "fj-observation" not in str(trace)


def test_delivery_callback_rejects_mismatched_financialjuice_release(monkeypatch):
    monkeypatch.setenv("TRACE_ID", "brief-fj-trace")
    monkeypatch.setenv("RELEASE_ID", "release-real")
    monkeypatch.setenv("SNAPSHOT_ID", "market-real")
    monkeypatch.setenv("FINANCIALJUICE_TRACE", json.dumps({"release_id": "release-other"}))
    with pytest.raises(ValueError, match="release_id"):
        build_payload()


def test_delivery_callback_posts_to_worker_endpoint(monkeypatch):
    monkeypatch.setenv("TRACE_ID", "worker-trace")
    monkeypatch.setenv("RELEASE_ID", "release-worker")
    monkeypatch.setenv("SNAPSHOT_ID", "snapshot-worker")
    monkeypatch.setenv("DELIVERY_RECEIPT_KIND", "photo_smoke")
    monkeypatch.setenv("DELIVERY_STATUS", "delivered")
    monkeypatch.setenv("DELIVERED_COUNT", "1")
    monkeypatch.setenv("FAILED_COUNT", "0")
    monkeypatch.setenv("RECEIPT_CALLBACK_URL", "https://worker.example/api/delivery-receipt")
    monkeypatch.setenv("DELIVERY_RECEIPT_SHARED_SECRET", "test-only-secret")
    monkeypatch.delenv("RAILWAY_STATUS_URL", raising=False)
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Response()

    monkeypatch.setattr("src.delivery_callback.requests.post", post)
    assert send_callback() is True
    assert captured["url"] == "https://worker.example/api/delivery-receipt"
    assert captured["headers"]["X-PRSTK-Signature"].startswith("sha256=")
    assert "test-only-secret" not in captured["data"].decode()
