"""Durable bounded cache persistence for Railway source fallbacks."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any


def read_cache(
    connection: sqlite3.Connection,
    cache_key: str,
    max_age_seconds: int,
) -> list[dict[str, str]] | None:
    """Return a recent list cache entry, or ``None`` when absent/invalid/stale."""
    row = connection.execute(
        "SELECT payload, refreshed_at FROM cache WHERE cache_key = ?", (cache_key,)
    ).fetchone()
    if row is None:
        return None
    payload, refreshed_at = row
    try:
        age = (
            datetime.now(UTC)
            - datetime.fromisoformat(str(refreshed_at))
        ).total_seconds()
        cached: Any = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return cached if age <= max(0, int(max_age_seconds)) and isinstance(cached, list) else None


def write_cache(
    connection: sqlite3.Connection,
    cache_key: str,
    payload: list[dict[str, str]],
) -> None:
    """Atomically replace one cache key with a timestamped JSON payload."""
    connection.execute(
        "INSERT OR REPLACE INTO cache(cache_key, payload, refreshed_at) VALUES (?, ?, ?)",
        (
            cache_key,
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            datetime.now(UTC).isoformat(),
        ),
    )
    connection.commit()
