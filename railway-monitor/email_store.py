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
                CREATE TABLE IF NOT EXISTS public_observations (
                    observation_id TEXT PRIMARY KEY,
                    content_origin TEXT NOT NULL,
                    content_hash TEXT,
                    published_at TEXT,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_public_observations_created
                    ON public_observations(created_at);
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

    def save_public_observation(self, observation: dict[str, Any]) -> bool:
        """Persist only the reviewed, public-safe observation projection.

        The caller must provide ``public_safe=true``.  Transport identifiers,
        sender addresses and raw content are intentionally rejected here as a
        second privacy boundary even if an upstream parser regresses.
        """
        if observation.get("public_safe") is not True:
            raise ValueError("public observation must be marked public_safe")
        blocked = {"body", "raw_body", "attachments", "gmail_message_id", "gmail_thread_id", "sender", "recipient"}
        if any(observation.get(key) not in (None, "", [], {}) for key in blocked):
            raise ValueError("public observation contains private fields")
        observation_id = str(observation.get("observation_id") or "").strip()
        source = str(observation.get("content_origin") or observation.get("source") or "").strip().casefold()
        if not observation_id or not source:
            raise ValueError("public observation identity is required")
        payload = {key: value for key, value in observation.items() if key not in blocked}
        payload["observation_id"] = observation_id
        payload["content_origin"] = source
        payload["source"] = source
        payload["public_safe"] = True
        with self._connect() as connection:
            before = connection.total_changes
            connection.execute(
                """INSERT OR IGNORE INTO public_observations(
                   observation_id, content_origin, content_hash, published_at,
                   created_at, payload_json) VALUES(?,?,?,?,?,?)""",
                (
                    observation_id,
                    source,
                    str(payload.get("content_hash") or "") or None,
                    str(payload.get("published_at") or payload.get("source_published_at") or "") or None,
                    _now(),
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                ),
            )
            return connection.total_changes > before

    def public_observations(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return bounded sanitized observations for the scheduled publisher."""
        bounded = max(1, min(500, int(limit)))
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT payload_json FROM public_observations
                   ORDER BY created_at DESC, observation_id DESC LIMIT ?""",
                (bounded,),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row[0])
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and payload.get("public_safe") is True:
                result.append(payload)
        return result

    def health(self) -> dict[str, Any]:
        with self._connect() as connection:
            observation_count = connection.execute("SELECT COUNT(*) FROM email_observations").fetchone()[0]
            dlq_count = connection.execute("SELECT COUNT(*) FROM email_dlq").fetchone()[0]
            public_count = connection.execute("SELECT COUNT(*) FROM public_observations").fetchone()[0]
            # A message is pending only while it has been durably received
            # but has not reached a terminal parser state.  Keep this count
            # bounded to the private store; only the number is projected to
            # the public health endpoint.
            pending_count = connection.execute(
                "SELECT COUNT(*) FROM email_observations "
                "WHERE parse_status IN ('received', 'queued', 'pending')"
            ).fetchone()[0]
        cursor = self.cursor()
        return {
            "status": "healthy" if cursor["last_sync_at"] else "no_new_content",
            "observation_count": int(observation_count),
            "dlq_count": int(dlq_count),
            "queue_pending_count": int(pending_count),
            "dead_letter_count": int(dlq_count),
            "public_observation_count": int(public_count),
            "cursor": cursor,
            "raw_content_stored": False,
            "source_health": self.source_health(),
        }

    def source_health(self) -> dict[str, dict[str, Any]]:
        """Return bounded, privacy-safe source counters for the health API.

        The monitor must distinguish a quiet source from a parser failure.  We
        derive the projection from sanitized metadata only; message bodies,
        transport IDs and sender addresses never leave the private store.
        """
        sources = {
            "creator": {
                "status": "not_checked", "received_count": 0,
                "parsed_count": 0, "failed_count": 0, "duplicate_count": 0,
                "public_observation_count": 0, "last_received_at": None,
                "last_parsed_at": None, "last_failure_at": None,
                "today_count": 0, "latest_count": 0,
                "morning_batch_count": 0, "coverage_status": "not_checked",
                "consensus_status": "not_checked", "last_release_id": None,
                "last_telegram_delivery_at": None,
                "failure_reason_counts": {}, "last_failure_reason": None,
            },
            "financialjuice": {
                "status": "not_checked", "received_count": 0,
                "parsed_count": 0, "failed_count": 0, "duplicate_count": 0,
                "public_observation_count": 0, "importance_gte_8_count": 0,
                "pending_cluster_count": 0, "last_received_at": None,
                "last_parsed_at": None, "last_failure_at": None,
                "decision": "not_checked", "last_release_id": None,
                "last_telegram_delivery_at": None,
                "failure_reason_counts": {}, "last_failure_reason": None,
            },
        }

        def bucket(source: Any) -> str | None:
            value = str(source or "").strip().casefold()
            if value == "financialjuice":
                return "financialjuice"
            if value and value not in {"unknown", "none"}:
                return "creator"
            return None

        def note(bucket_name: str, key: str, timestamp: Any) -> None:
            current = sources[bucket_name].get(key)
            candidate = str(timestamp or "") or None
            if candidate and (current is None or candidate > str(current)):
                sources[bucket_name][key] = candidate

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT metadata_json, parse_status, received_at, inserted_at FROM email_observations"
            ).fetchall()
            dlq_rows = connection.execute(
                "SELECT metadata_json, failure_reason, created_at FROM email_dlq"
            ).fetchall()
            public_rows = connection.execute(
                "SELECT content_origin, payload_json, created_at FROM public_observations"
            ).fetchall()

        for row in rows:
            try:
                metadata = json.loads(row[0]) if row[0] else {}
            except (TypeError, json.JSONDecodeError):
                metadata = {}
            source_name = bucket(metadata.get("content_origin"))
            if source_name is None:
                continue
            item = sources[source_name]
            item["received_count"] += 1
            status = str(row[1] or "")
            if status == "duplicate":
                item["duplicate_count"] += 1
            elif status in {"parsed", "normalized", "identified"}:
                item["parsed_count"] += 1
                note(source_name, "last_parsed_at", row[3] or row[2])
            note(source_name, "last_received_at", row[2] or row[3])

        for row in dlq_rows:
            try:
                metadata = json.loads(row[0]) if row[0] else {}
            except (TypeError, json.JSONDecodeError):
                metadata = {}
            source_name = bucket(metadata.get("content_origin"))
            if source_name is None:
                continue
            item = sources[source_name]
            item["failed_count"] += 1
            reason = str(row[1] or "parse_failed").strip()[:80] or "parse_failed"
            reason_counts = item.setdefault("failure_reason_counts", {})
            reason_counts[reason] = int(reason_counts.get(reason, 0)) + 1
            timestamp = row[2]
            note(source_name, "last_failure_at", timestamp)
            current = item.get("last_failure_at")
            if current and str(timestamp or "") == str(current):
                item["last_failure_reason"] = reason

        for item in sources.values():
            counts = item.get("failure_reason_counts") or {}
            item["failure_reason_counts"] = dict(
                sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[:8]
            )

        for row in public_rows:
            source_name = bucket(row[0])
            if source_name is None:
                continue
            item = sources[source_name]
            item["public_observation_count"] += 1
            try:
                payload = json.loads(row[1]) if row[1] else {}
            except (TypeError, json.JSONDecodeError):
                payload = {}
            if source_name == "financialjuice" and isinstance(payload, dict):
                try:
                    if float(payload.get("vendor_importance")) >= 8:
                        item["importance_gte_8_count"] += 1
                except (TypeError, ValueError):
                    pass
                cluster = str(payload.get("event_cluster_key") or "").strip()
                if cluster and not bool(payload.get("official_confirmed")):
                    item["pending_cluster_count"] += 1

        for item in sources.values():
            if item["failed_count"] and not item["parsed_count"]:
                item["status"] = "failed"
            elif item["received_count"] or item["public_observation_count"]:
                item["status"] = "healthy" if item["failed_count"] == 0 else "degraded"
            else:
                item["status"] = "no_new_content"
        fj = sources["financialjuice"]
        if fj["public_observation_count"]:
            fj["decision"] = "awaiting_confirmation" if fj["pending_cluster_count"] else "ready_for_release_review"
        return sources


__all__ = ["EmailStore"]
