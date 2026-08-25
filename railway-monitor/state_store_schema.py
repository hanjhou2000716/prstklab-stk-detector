"""SQLite schema and additive migrations for the Railway monitor state store."""

from __future__ import annotations

import sqlite3


def initialize_state_schema(connection: sqlite3.Connection) -> None:
    """Create the durable monitor tables and apply additive migrations."""
    connection.execute(
        "CREATE TABLE IF NOT EXISTS seen (event_id TEXT PRIMARY KEY, first_seen_at TEXT NOT NULL)"
    )
    # Older Railway volumes have a two-column ``seen`` table.  Keep those
    # rows, but make them eligible for one post-deploy classification pass
    # so a headline that was previously outside the keyword scope can be
    # re-evaluated after a rule update.
    columns = {row[1] for row in connection.execute("PRAGMA table_info(seen)").fetchall()}
    if "classification" not in columns:
        connection.execute(
            "ALTER TABLE seen ADD COLUMN classification TEXT NOT NULL DEFAULT 'unclassified'"
        )
    if "classified_at" not in columns:
        connection.execute("ALTER TABLE seen ADD COLUMN classified_at TEXT")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS dispatched (category TEXT NOT NULL, summary TEXT NOT NULL, dispatched_at TEXT NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS cache (cache_key TEXT PRIMARY KEY, payload TEXT NOT NULL, refreshed_at TEXT NOT NULL)"
    )
    # Bounded, privacy-safe monitor samples survive Railway restarts.  The
    # payload intentionally contains only aggregate counters and component
    # status labels; raw events, credentials and delivery identifiers never
    # belong in this table.
    connection.execute(
        """CREATE TABLE IF NOT EXISTS health_samples (
            recorded_at TEXT PRIMARY KEY,
            overall_state TEXT NOT NULL,
            failure_count INTEGER NOT NULL DEFAULT 0,
            no_event_count INTEGER NOT NULL DEFAULT 0,
            component_statuses_json TEXT NOT NULL DEFAULT '{}'
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS event_ledger (
            canonical_key TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            source_url TEXT,
            person_fingerprint TEXT,
            location_fingerprint TEXT,
            action_fingerprint TEXT,
            first_discovered_at TEXT NOT NULL,
            last_reminded_at TEXT,
            escalated INTEGER NOT NULL DEFAULT 0,
            verified_sources_json TEXT NOT NULL DEFAULT '[]',
            last_title TEXT,
            updated_at TEXT NOT NULL
        )"""
    )
    # Formal Railway outbox: dispatch attempts survive GitHub Actions
    # cache eviction and can be retried/inspected without replaying every
    # source event.
    connection.execute(
        """CREATE TABLE IF NOT EXISTS delivery_outbox (
            trace_id TEXT PRIMARY KEY,
            canonical_key TEXT NOT NULL,
            source TEXT NOT NULL,
            event_id TEXT NOT NULL,
            category TEXT,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            next_retry_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    outbox_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(delivery_outbox)").fetchall()
    }
    if "category" not in outbox_columns:
        connection.execute("ALTER TABLE delivery_outbox ADD COLUMN category TEXT")
    connection.execute(
        """CREATE TABLE IF NOT EXISTS incoming_events (
            event_id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            title TEXT,
            content TEXT,
            occurred_at TEXT,
            classification TEXT NOT NULL DEFAULT 'unclassified',
            classification_reason TEXT,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            last_error TEXT
        )"""
    )
    incoming_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(incoming_events)").fetchall()
    }
    if "classification_reason" not in incoming_columns:
        connection.execute(
            "ALTER TABLE incoming_events ADD COLUMN classification_reason TEXT"
        )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS delivery_receipts (
            trace_id TEXT NOT NULL,
            recipient_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            error TEXT,
            delivered_count INTEGER,
            failed_count INTEGER,
            reported_at TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(trace_id, recipient_hash)
        )"""
    )
    receipt_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(delivery_receipts)").fetchall()
    }
    # Keep the migration additive: Railway volumes may contain receipts
    # written by an older monitor process.
    for column, definition in (
        ("delivered_count", "INTEGER"),
        ("failed_count", "INTEGER"),
        ("reported_at", "TEXT"),
    ):
        if column not in receipt_columns:
            connection.execute(
                f"ALTER TABLE delivery_receipts ADD COLUMN {column} {definition}"
            )

