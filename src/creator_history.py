"""Private, bounded history for sanitized Creator episodes.

Only derived, public-safe metadata is retained.  Raw email bodies, attachment
bytes, local paths and private URLs are rejected before they can reach the
SQLite file.  The public artifact remains bounded separately by the release
contract; this store is for replay, topic evolution and later outcome review.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_PRIVATE_FIELDS = {"body", "raw_body", "attachments", "attachment_bytes", "local_path", "private_url"}
_ALLOWED_FIELDS = {
    "creator_id", "creator_name", "episode_key", "episode_id", "episode_title",
    "published_at", "content_origin", "topics", "markets", "sectors", "tickers",
    "key_takeaways", "creator_market_view", "creator_strategy_view", "creator_risk_view",
    "key_numbers", "claims", "opinions", "verification_state", "evidence_alignment",
    "consensus_stance", "summary_image_available", "summary_image_hash", "parse_status",
    "parser_version", "created_at", "updated_at", "public_safe",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _canonical(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _safe_record(record: dict[str, Any]) -> dict[str, Any]:
    if any(record.get(field) for field in _PRIVATE_FIELDS):
        raise ValueError("private creator content cannot be stored")
    if record.get("public_safe") is not True:
        raise ValueError("only public-safe creator insights can be stored")
    episode_key = str(record.get("episode_key") or "").strip()
    if not episode_key:
        raise ValueError("episode_key is required")
    return {key: value for key, value in record.items() if key in _ALLOWED_FIELDS}


class CreatorHistoryStore:
    """SQLite-backed append-only Creator snapshot history."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS creator_episode_history (
                    snapshot_id TEXT PRIMARY KEY,
                    episode_key TEXT NOT NULL,
                    creator_id TEXT NOT NULL,
                    content_origin TEXT NOT NULL,
                    published_at TEXT,
                    recorded_at TEXT NOT NULL,
                    record_json TEXT NOT NULL
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_creator_history_recent ON creator_episode_history(recorded_at DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_creator_history_episode ON creator_episode_history(episode_key, recorded_at DESC)"
            )

    def append(self, insight: dict[str, Any], *, recorded_at: str | None = None) -> str:
        safe = _safe_record(insight)
        payload = _canonical(safe)
        snapshot_id = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        when = recorded_at or _now().isoformat()
        with self._connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO creator_episode_history(
                    snapshot_id, episode_key, creator_id, content_origin,
                    published_at, recorded_at, record_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    snapshot_id,
                    safe["episode_key"],
                    str(safe.get("creator_id") or safe.get("content_origin") or ""),
                    str(safe.get("content_origin") or "unknown"),
                    safe.get("published_at"),
                    when,
                    payload,
                ),
            )
        return snapshot_id

    def list_recent(self, *, creator_id: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        query = "SELECT record_json FROM creator_episode_history"
        parameters: list[Any] = []
        if creator_id:
            query += " WHERE creator_id = ?"
            parameters.append(str(creator_id))
        query += " ORDER BY recorded_at DESC, snapshot_id DESC LIMIT ?"
        parameters.append(int(limit))
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [json.loads(row["record_json"]) for row in rows]

    def prune(self, *, retention_days: int = 30, now: str | None = None) -> int:
        """Remove old snapshots while retaining the newest snapshot per episode."""
        days = max(30, int(retention_days))
        current = datetime.fromisoformat(now.replace("Z", "+00:00")) if now else _now()
        cutoff = current.replace(tzinfo=current.tzinfo or UTC).astimezone(UTC) - timedelta(days=days)
        with self._connect() as connection:
            removed = connection.execute(
                """DELETE FROM creator_episode_history
                   WHERE recorded_at < ? AND snapshot_id NOT IN (
                     SELECT snapshot_id FROM creator_episode_history AS latest
                     WHERE latest.episode_key = creator_episode_history.episode_key
                     ORDER BY latest.recorded_at DESC LIMIT 1
                   )""",
                (cutoff.isoformat(),),
            ).rowcount
        return int(removed)

    def health(self) -> dict[str, Any]:
        with self._connect() as connection:
            count = int(connection.execute("SELECT COUNT(*) FROM creator_episode_history").fetchone()[0])
        return {"status": "healthy" if count else "no_new_content", "snapshot_count": count, "raw_content_stored": False}


__all__ = ["CreatorHistoryStore"]
