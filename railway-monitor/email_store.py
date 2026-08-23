"""Private, durable Gmail cursor/observation store for the Railway worker.

The store intentionally persists only hashes and sanitized metadata.  Raw mail
and attachments never enter this database, which keeps a restart/replay safe
without turning Railway into a public archive.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class EmailStore:
    """SQLite-backed idempotency, cursor and DLQ state."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialise(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS gmail_cursor (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    watch_expiration TEXT,
                    watch_last_renewed_at TEXT,
                    watch_error TEXT,
                    watch_error_at TEXT,
                    last_history_id TEXT,
                    last_notification_at TEXT,
                    last_sync_at TEXT,
                    last_full_sync_at TEXT,
                    last_message_id TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS email_observations (
                    gmail_message_id TEXT PRIMARY KEY,
                    observation_id TEXT NOT NULL,
                    content_hash TEXT,
                    creator_episode_key TEXT,
                    event_cluster_key TEXT,
                    parse_status TEXT NOT NULL,
                    parser_version TEXT NOT NULL,
                    received_at TEXT,
                    inserted_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_email_content_hash
                    ON email_observations(content_hash)
                    WHERE content_hash IS NOT NULL;
                CREATE TABLE IF NOT EXISTS email_dlq (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    gmail_message_id TEXT NOT NULL,
                    parser_name TEXT NOT NULL,
                    parser_version TEXT NOT NULL,
                    template_fingerprint TEXT NOT NULL,
                    parse_status TEXT NOT NULL,
                    failure_reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_email_dlq_message
                    ON email_dlq(gmail_message_id, created_at);
                """
            )
            # Existing Railway volumes predate the watch lease observability
            # columns.  Migrate in place without dropping the durable cursor.
            columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(gmail_cursor)")}
            for name in ("watch_last_renewed_at", "watch_error", "watch_error_at"):
                if name not in columns:
                    connection.execute(f"ALTER TABLE gmail_cursor ADD COLUMN {name} TEXT")

    def cursor(self) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM gmail_cursor WHERE id = 1").fetchone()
        if row is None:
            return {
                "watch_expiration": None,
                "watch_last_renewed_at": None,
                "watch_error": None,
                "watch_error_at": None,
                "last_history_id": None,
                "last_notification_at": None,
                "last_sync_at": None,
                "last_full_sync_at": None,
                "last_message_id": None,
            }
        return {key: row[key] for key in row.keys() if key != "id" and key != "updated_at"}

    def save_cursor(self, **values: Any) -> dict[str, Any]:
        current = self.cursor()
        current.update({key: value for key, value in values.items() if key in current})
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO gmail_cursor(id, watch_expiration, watch_last_renewed_at,
                   watch_error, watch_error_at, last_history_id,
                   last_notification_at, last_sync_at, last_full_sync_at,
                   last_message_id, updated_at)
                   VALUES(1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET watch_expiration=excluded.watch_expiration,
                   watch_last_renewed_at=excluded.watch_last_renewed_at,
                   watch_error=excluded.watch_error,
                   watch_error_at=excluded.watch_error_at,
                   last_history_id=excluded.last_history_id,
                   last_notification_at=excluded.last_notification_at,
                   last_sync_at=excluded.last_sync_at,
                   last_full_sync_at=excluded.last_full_sync_at,
                   last_message_id=excluded.last_message_id,
                   updated_at=excluded.updated_at""",
                (
                    current["watch_expiration"], current["watch_last_renewed_at"],
                    current["watch_error"], current["watch_error_at"], current["last_history_id"],
                    current["last_notification_at"], current["last_sync_at"],
                    current["last_full_sync_at"], current["last_message_id"], _now(),
                ),
            )
        return current

    def claim_observation(self, observation: dict[str, Any]) -> bool:
        """Atomically claim one Gmail message; return False on replay/dedupe."""
        message_id = str(observation.get("gmail_message_id") or "").strip()
        if not message_id:
            raise ValueError("gmail_message_id is required")
        content_hash = observation.get("body_hash") or observation.get("content_hash")
        content_hash = str(content_hash) if content_hash else None
        metadata = {key: value for key, value in observation.items() if key not in {"body", "raw_body", "attachments"}}
        with self._connect() as connection:
            try:
                connection.execute(
                    """INSERT INTO email_observations(
                       gmail_message_id, observation_id, content_hash,
                       creator_episode_key, event_cluster_key, parse_status,
                       parser_version, received_at, inserted_at, metadata_json)
                       VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        message_id, str(observation.get("observation_id") or f"email-{_hash(message_id)[:16]}"),
                        content_hash, observation.get("creator_episode_key"),
                        observation.get("event_cluster_key"), str(observation.get("parse_status") or "received"),
                        str(observation.get("parser_version") or "unknown"), observation.get("received_at"),
                        _now(), json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    ),
                )
            except sqlite3.IntegrityError:
                return False
        return True

    def record_dlq(self, *, message_id: str, parser_name: str, parser_version: str,
                   template_fingerprint: str, parse_status: str, failure_reason: str,
                   metadata: dict[str, Any] | None = None) -> None:
        """Record a bounded, privacy-safe parse failure for later replay."""
        safe = {key: value for key, value in (metadata or {}).items() if key not in {"body", "raw_body", "attachments"}}
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO email_dlq(gmail_message_id, parser_name, parser_version,
                   template_fingerprint, parse_status, failure_reason, created_at, metadata_json)
                   VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(message_id), str(parser_name), str(parser_version), str(template_fingerprint),
                    str(parse_status), str(failure_reason), _now(), json.dumps(safe, ensure_ascii=False, sort_keys=True),
                ),
            )

    def health(self) -> dict[str, Any]:
        with self._connect() as connection:
            observation_count = connection.execute("SELECT COUNT(*) FROM email_observations").fetchone()[0]
            dlq_count = connection.execute("SELECT COUNT(*) FROM email_dlq").fetchone()[0]
        cursor = self.cursor()
        return {
            "status": "healthy" if cursor["last_sync_at"] else "no_new_content",
            "observation_count": int(observation_count),
            "dlq_count": int(dlq_count),
            "cursor": cursor,
            "raw_content_stored": False,
        }


__all__ = ["EmailStore"]
