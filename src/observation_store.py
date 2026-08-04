"""Append-only raw observation store for public source responses.

The store uses SQLite for the index and hash-addressed JSON payload files for
raw bodies. It is intentionally provider-neutral and never stores request
headers or credentials. A duplicate payload is idempotent; an existing raw
file is never overwritten.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.adapters.base import AdapterObservation, payload_hash

SCHEMA_VERSION = "1"


def _utc(value: datetime | None = None) -> str:
    return (value or datetime.now(UTC)).astimezone(UTC).isoformat()


def _safe_provider(value: str) -> str:
    clean = "".join(ch.lower() if ch.isalnum() or ch in "-_" else "_" for ch in value.strip())
    return clean or "unknown"


@dataclass(frozen=True)
class RawObservationRecord:
    observation_id: int
    provider: str
    endpoint: str
    source_tier: str
    fetched_at: str
    request_id: str | None
    http_status: int | None
    payload_hash: str
    raw_payload_location: str
    parser_version: str
    parse_status: str
    created_at: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class RawObservationStore:
    """Persist raw public observations without update-in-place semantics."""

    def __init__(self, root: Path | str = Path("data/raw-observations"), *, database: Path | str | None = None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = Path(database) if database else self.root / "observations.sqlite3"
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS raw_observations (
                    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    source_tier TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    request_id TEXT,
                    http_status INTEGER,
                    payload_hash TEXT NOT NULL UNIQUE,
                    raw_payload_location TEXT NOT NULL,
                    parser_version TEXT NOT NULL,
                    parse_status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    schema_version TEXT NOT NULL DEFAULT '1'
                )
            """)
            connection.execute("CREATE INDEX IF NOT EXISTS idx_raw_provider_time ON raw_observations(provider, fetched_at)")

    def _payload_location(self, observation: AdapterObservation) -> Path:
        day = observation.fetched_at.astimezone(UTC).date().isoformat()
        return self.root / _safe_provider(observation.provider) / day / f"{observation.payload_hash or payload_hash(observation.payload)}.json"

    @staticmethod
    def _write_once(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            with path.open("xb") as handle:
                handle.write(encoded)
        except FileExistsError:
            if hashlib.sha256(path.read_bytes()).hexdigest() != hashlib.sha256(encoded).hexdigest():
                raise ValueError("immutable raw observation path contains different content") from None
    def append(self, observation: AdapterObservation, *, parser_version: str) -> RawObservationRecord:
        """Write payload once, then insert its metadata idempotently."""
        digest = observation.payload_hash or payload_hash(observation.payload)
        if digest != payload_hash(observation.payload):
            raise ValueError("payload hash does not match observation payload")
        location = self._payload_location(observation)
        self._write_once(location, observation.payload)
        created = _utc()
        with self._connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO raw_observations
                (provider, endpoint, source_tier, fetched_at, request_id, http_status,
                 payload_hash, raw_payload_location, parser_version, parse_status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    observation.provider, observation.endpoint, observation.source_tier,
                    _utc(observation.fetched_at), observation.request_id, observation.http_status,
                    digest, str(location), parser_version, observation.parse_status, created,
                ),
            )
            row = connection.execute("SELECT * FROM raw_observations WHERE payload_hash = ?", (digest,)).fetchone()
        assert row is not None
        return RawObservationRecord(**{key: row[key] for key in RawObservationRecord.__dataclass_fields__})

    def get(self, digest: str) -> RawObservationRecord | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM raw_observations WHERE payload_hash = ?", (digest,)).fetchone()
        return RawObservationRecord(**{key: row[key] for key in RawObservationRecord.__dataclass_fields__}) if row else None

    def read_payload(self, record: RawObservationRecord) -> Any:
        return json.loads(Path(record.raw_payload_location).read_text(encoding="utf-8"))

    def list(self, *, provider: str | None = None, limit: int = 100) -> list[RawObservationRecord]:
        limit = max(1, min(int(limit), 10_000))
        query = "SELECT * FROM raw_observations"
        params: tuple[Any, ...] = ()
        if provider:
            query += " WHERE provider = ?"
            params = (provider,)
        query += " ORDER BY fetched_at DESC LIMIT ?"
        params += (limit,)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [RawObservationRecord(**{key: row[key] for key in RawObservationRecord.__dataclass_fields__}) for row in rows]

    def count(self, *, provider: str | None = None) -> int:
        query = "SELECT COUNT(*) FROM raw_observations"
        params: tuple[Any, ...] = ()
        if provider:
            query += " WHERE provider = ?"
            params = (provider,)
        with self._connect() as connection:
            return int(connection.execute(query, params).fetchone()[0])
