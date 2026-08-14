from __future__ import annotations

import importlib.util
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


schema = _load("railway_state_schema_for_cache_test", "state_store_schema.py")
cache = _load("railway_cache_store_test", "cache_store.py")


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    schema.initialize_state_schema(connection)
    return connection


def test_cache_roundtrip_is_json_safe_and_bounded_by_age():
    connection = _connection()
    payload = [{"title": "台股事件", "url": "https://example.test/a"}]
    cache.write_cache(connection, "gdelt-success", payload)
    assert cache.read_cache(connection, "gdelt-success", 60) == payload
    assert cache.read_cache(connection, "missing", 60) is None


def test_cache_rejects_invalid_or_stale_payload():
    connection = _connection()
    old = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    connection.execute(
        "INSERT INTO cache(cache_key, payload, refreshed_at) VALUES (?, ?, ?)",
        ("old", "{not-json", old),
    )
    connection.execute(
        "INSERT INTO cache(cache_key, payload, refreshed_at) VALUES (?, ?, ?)",
        ("stale", "[]", old),
    )
    connection.commit()
    assert cache.read_cache(connection, "old", 3600) is None
    assert cache.read_cache(connection, "stale", 60) is None


def test_cache_rejects_non_list_json():
    connection = _connection()
    cache.write_cache(connection, "object", [{"ok": "yes"}])
    connection.execute("UPDATE cache SET payload='{}' WHERE cache_key='object'")
    connection.commit()
    assert cache.read_cache(connection, "object", 60) is None
