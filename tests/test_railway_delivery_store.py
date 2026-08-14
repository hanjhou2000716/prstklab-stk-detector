from __future__ import annotations

import importlib.util
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parents[1] / "railway-monitor"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


schema = _load("railway_state_schema_for_delivery_test", "state_store_schema.py")
delivery = _load("railway_delivery_store_test", "delivery_store.py")


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    schema.initialize_state_schema(connection)
    return connection


def test_outbox_round_trip_and_retry_backoff_are_durable():
    connection = _connection()
    delivery.record_outbox(
        connection,
        trace_id="trace-1",
        canonical_key="event-1",
        source="test",
        event_id="event-1",
        category="price",
        payload={"dispatch_payload": {"alert_id": "a1"}, "notification_keys": ["k1"]},
    )
    assert delivery.outbox_state(connection, "trace-1") == ("pending", True)
    assert delivery.due_outbox(connection) == [
        {
            "trace_id": "trace-1",
            "dispatch_payload": {"alert_id": "a1"},
            "status": "pending",
            "attempts": 0,
            "updated_at": connection.execute(
                "SELECT updated_at FROM delivery_outbox WHERE trace_id='trace-1'"
            ).fetchone()[0],
        }
    ]
    delivery.mark_outbox(connection, "trace-1", "failed", "temporary timeout")
    assert delivery.outbox_state(connection, "trace-1") == ("failed", True)
    assert delivery.due_outbox(connection) == []
    assert delivery.delivery_diagnostics(connection)["retryable_count"] == 1


def test_delivery_receipt_requires_explicit_origin_and_keeps_recipient_failures():
    connection = _connection()
    payload = {
        "trace_id": "trace-2",
        "receipt_kind": "production",
        "receipt_origin": "github_actions",
        "release_id": "release-2",
        "snapshot_id": "snapshot-2",
        "alert_id": "alert-2",
        "delivery_mode": "photo",
        "delivery_status": "partial",
        "delivered_count": 1,
        "failed_count": 1,
        "failed_recipient_hashes": ["hash-b"],
        "reported_at": "2026-08-14T01:00:00+00:00",
    }
    assert delivery.record_delivery_status(connection, payload) is True
    diagnostics = delivery.delivery_diagnostics(connection)
    assert diagnostics["last_receipt_status"] == "partial"
    assert diagnostics["last_delivered_count"] == 1
    assert diagnostics["last_failed_count"] == 1
    assert diagnostics["last_failed_recipient_hash_count"] == 1
    history = delivery.delivery_history(connection)
    assert history[0]["notification_keys"] == []
    assert history[0]["recipient_count"] == 2

    rejected = dict(payload, trace_id="trace-3", receipt_origin="unknown")
    assert delivery.record_delivery_status(connection, rejected) is False


def test_legacy_receipt_counts_are_read_and_terminal_history_is_pruned():
    connection = _connection()
    old = (datetime.now(UTC) - timedelta(days=31)).isoformat()
    connection.execute(
        """INSERT INTO delivery_outbox(
            trace_id, canonical_key, source, event_id, category, payload_json,
            status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'sent', ?, ?)""",
        ("trace-old", "old", "test", "old", "briefing", "{}", old, old),
    )
    connection.execute(
        """INSERT INTO delivery_receipts(
            trace_id, recipient_hash, status, error, updated_at
        ) VALUES (?, '__aggregate__', 'delivered', ?, ?)""",
        ("trace-old", json.dumps({"delivered_count": 2, "failed_count": 0, "reported_at": old}), old),
    )
    connection.commit()
    assert delivery.delivery_history(connection)[0]["delivered_count"] == 2
    assert delivery.prune_delivery_history(connection) == 1
    assert connection.execute("SELECT 1 FROM delivery_outbox WHERE trace_id='trace-old'").fetchone() is None


def test_photo_smoke_receipt_can_register_without_prior_outbox():
    connection = _connection()
    payload = {
        "trace_id": "photo-trace",
        "receipt_kind": "photo_smoke",
        "release_id": "photo-smoke-test",
        "snapshot_id": "photo-smoke-test",
        "alert_id": "photo-smoke-test",
        "delivery_mode": "photo",
        "delivery_status": "delivered",
        "delivered_count": 1,
        "failed_count": 0,
    }
    assert delivery.record_delivery_status(connection, payload) is True
    assert delivery.outbox_state(connection, "photo-trace") == ("delivered", False)
