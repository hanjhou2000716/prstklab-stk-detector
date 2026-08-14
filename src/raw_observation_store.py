"""Append-only raw observation store for public provider responses.

The store deliberately uses only the Python standard library so it works in
GitHub Actions and on Railway without an additional native dependency.  Raw
payloads are content-addressed JSON files; SQLite stores the immutable index
and provenance needed to replay parsers later.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.atomic_file import replace_with_retry, write_bytes_with_retry

SCHEMA_VERSION = 1
_SQLITE_RETRY_ATTEMPTS = 3


def _sqlite_retryable(exc: sqlite3.OperationalError) -> bool:
    message = str(exc).lower()
    return "locked" in message or "busy" in message


def _canonical_bytes(payload: Any) -> bytes:
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8")
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


@dataclass(frozen=True)
class RawObservation:
    observation_id: str
    provider: str
    endpoint: str
    fetched_at: str
    request_id: str
    http_status: int | None
    payload_hash: str
    raw_payload_location: str
    parser_version: str
    parsing_status: str


class RawObservationStore:
    """Persist raw responses without updating or overwriting prior rows."""

    def __init__(self, root: Path | str = "data/raw_observations", *, db_name: str = "observations.sqlite3") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / db_name
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS observations (
                    observation_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    http_status INTEGER,
                    payload_hash TEXT NOT NULL,
                    raw_payload_location TEXT NOT NULL,
                    parser_version TEXT NOT NULL,
                    parsing_status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_observations_identity
                    ON observations(provider, endpoint, request_id, payload_hash);
                CREATE INDEX IF NOT EXISTS idx_observations_provider_time
                    ON observations(provider, fetched_at);
                """
            )

    @staticmethod
    def _observation_id(provider: str, endpoint: str, request_id: str, payload_hash: str) -> str:
        material = "|".join((provider, endpoint, request_id, payload_hash)).encode("utf-8")
        return hashlib.sha256(material).hexdigest()[:32]

    def record(
        self,
        *,
        provider: str,
        endpoint: str,
        fetched_at: str,
        request_id: str,
        payload: Any,
        http_status: int | None,
        parser_version: str,
        parsing_status: str,
    ) -> RawObservation:
        """Write one raw payload and immutable metadata row.

        Re-recording an identical request/payload is idempotent and returns the
        existing row; a different payload always receives a new observation.
        """
        if not provider.strip() or not endpoint.strip() or not request_id.strip():
            raise ValueError("provider, endpoint and request_id are required")
        payload_bytes = _canonical_bytes(payload)
        payload_hash = hashlib.sha256(payload_bytes).hexdigest()
        observation_id = self._observation_id(provider, endpoint, request_id, payload_hash)
        relative = Path(provider) / fetched_at[:10] / f"{payload_hash}.json"
        destination = self.root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            temporary = destination.with_name(f".{destination.name}.{observation_id}.tmp")
            try:
                write_bytes_with_retry(payload_bytes, temporary)
                replace_with_retry(temporary, destination)
            finally:
                if temporary.exists():
                    temporary.unlink()
        created_at = datetime.now(UTC).isoformat()
        for attempt in range(_SQLITE_RETRY_ATTEMPTS):
            try:
                with self._connect() as connection:
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO observations (
                            observation_id, provider, endpoint, fetched_at, request_id,
                            http_status, payload_hash, raw_payload_location,
                            parser_version, parsing_status, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            observation_id,
                            provider,
                            endpoint,
                            fetched_at,
                            request_id,
                            http_status,
                            payload_hash,
                            str(relative).replace("\\", "/"),
                            parser_version,
                            parsing_status,
                            created_at,
                        ),
                    )
                    row = connection.execute(
                        "SELECT * FROM observations WHERE observation_id = ?", (observation_id,)
                    ).fetchone()
                break
            except sqlite3.OperationalError as exc:
                if not _sqlite_retryable(exc) or attempt == _SQLITE_RETRY_ATTEMPTS - 1:
                    raise
                time.sleep(0.05 * (2**attempt))
        if row is None:  # pragma: no cover - defensive database failure
            raise RuntimeError("observation row was not created")
        return self._row(row)

    def get(self, observation_id: str) -> RawObservation | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM observations WHERE observation_id = ?", (observation_id,)
            ).fetchone()
        return self._row(row) if row else None

    def list_recent(self, *, provider: str | None = None, limit: int = 100) -> list[RawObservation]:
        if limit <= 0:
            return []
        query = "SELECT * FROM observations"
        parameters: tuple[Any, ...] = ()
        if provider:
            query += " WHERE provider = ?"
            parameters = (provider,)
        query += " ORDER BY fetched_at DESC, observation_id DESC LIMIT ?"
        parameters += (int(limit),)
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._row(row) for row in rows]

    def count(self, *, provider: str | None = None) -> int:
        query = "SELECT COUNT(*) FROM observations"
        parameters: tuple[Any, ...] = ()
        if provider:
            query += " WHERE provider = ?"
            parameters = (provider,)
        with self._connect() as connection:
            return int(connection.execute(query, parameters).fetchone()[0])

    def _row(self, row: sqlite3.Row) -> RawObservation:
        values = dict(row)
        return RawObservation(
            observation_id=values["observation_id"],
            provider=values["provider"],
            endpoint=values["endpoint"],
            fetched_at=values["fetched_at"],
            request_id=values["request_id"],
            http_status=values["http_status"],
            payload_hash=values["payload_hash"],
            raw_payload_location=values["raw_payload_location"],
            parser_version=values["parser_version"],
            parsing_status=values["parsing_status"],
        )


def observation_metadata(rows: Iterable[RawObservation]) -> list[dict[str, Any]]:
    """Convert rows to safe JSON metadata for a source-health endpoint."""
    return [
        {
            "observation_id": row.observation_id,
            "provider": row.provider,
            "endpoint": row.endpoint,
            "fetched_at": row.fetched_at,
            "request_id": row.request_id,
            "http_status": row.http_status,
            "payload_hash": row.payload_hash,
            "raw_payload_location": row.raw_payload_location,
            "parser_version": row.parser_version,
            "parsing_status": row.parsing_status,
        }
        for row in rows
    ]
