from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "railway-monitor" / "state_store_schema.py"
SPEC = importlib.util.spec_from_file_location("railway_state_store_schema_test", MODULE_PATH)
assert SPEC and SPEC.loader
schema = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(schema)


def _tables(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {row[0] for row in rows}


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}


def test_initialize_state_schema_creates_all_durable_tables_and_is_idempotent():
    connection = sqlite3.connect(":memory:")

    schema.initialize_state_schema(connection)
    schema.initialize_state_schema(connection)

    assert {
        "seen",
        "dispatched",
        "cache",
        "event_ledger",
        "delivery_outbox",
        "incoming_events",
        "delivery_receipts",
    } <= _tables(connection)
    assert {"event_id", "first_seen_at", "classification", "classified_at"} <= _columns(connection, "seen")
    assert "category" in _columns(connection, "delivery_outbox")
    assert "classification_reason" in _columns(connection, "incoming_events")
    assert {"delivered_count", "failed_count", "reported_at"} <= _columns(
        connection, "delivery_receipts"
    )


def test_initialize_state_schema_adds_columns_to_legacy_railway_volume():
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE seen (event_id TEXT PRIMARY KEY, first_seen_at TEXT NOT NULL);
        CREATE TABLE delivery_outbox (
            trace_id TEXT PRIMARY KEY, canonical_key TEXT NOT NULL,
            source TEXT NOT NULL, event_id TEXT NOT NULL, payload_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT, next_retry_at TEXT, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE incoming_events (
            event_id TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT, content TEXT,
            occurred_at TEXT, classification TEXT NOT NULL DEFAULT 'unclassified',
            first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, last_error TEXT
        );
        CREATE TABLE delivery_receipts (
            trace_id TEXT NOT NULL, recipient_hash TEXT NOT NULL, status TEXT NOT NULL,
            error TEXT, updated_at TEXT NOT NULL,
            PRIMARY KEY(trace_id, recipient_hash)
        );
        """
    )

    schema.initialize_state_schema(connection)

    assert {"classification", "classified_at"} <= _columns(connection, "seen")
    assert "category" in _columns(connection, "delivery_outbox")
    assert "classification_reason" in _columns(connection, "incoming_events")
    assert {"delivered_count", "failed_count", "reported_at"} <= _columns(
        connection, "delivery_receipts"
    )
