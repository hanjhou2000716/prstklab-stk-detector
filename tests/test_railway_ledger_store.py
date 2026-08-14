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


schema = _load("railway_state_schema_for_ledger_test", "state_store_schema.py")
ledger = _load("railway_ledger_store_test", "ledger_store.py")


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    schema.initialize_state_schema(connection)
    return connection


def test_event_ledger_observe_merge_and_cooldown_transition():
    connection = _connection()
    first = ledger.observe_alert(
        connection,
        canonical_key="event-key",
        event_type="geopolitical_event",
        source_urls=["https://example.com/a"],
        fingerprints={"person": "p", "location": "iran", "action": "talks"},
        title="Officials open talks",
    )
    assert first == {
        "canonical_key": "event-key",
        "is_new": True,
        "last_reminded_at": None,
        "escalated": False,
    }
    assert ledger.ledger_may_dispatch(first, cooldown_seconds=1800) is True
    ledger.mark_alert_reminded(connection, canonical_key="event-key")
    second = ledger.observe_alert(
        connection,
        canonical_key="event-key",
        event_type="geopolitical_event",
        source_urls=["https://example.com/b"],
        fingerprints={"person": "p", "location": "iran", "action": "talks"},
        title="Officials open talks — update",
    )
    assert second["is_new"] is False
    assert second["last_reminded_at"]
    assert ledger.ledger_may_dispatch(second, cooldown_seconds=1800) is False
    sources = connection.execute(
        "SELECT verified_sources_json FROM event_ledger WHERE canonical_key='event-key'"
    ).fetchone()[0]
    assert "example.com/a" in sources and "example.com/b" in sources


def test_category_cooldown_allows_new_escalation_term_only():
    connection = _connection()
    assert ledger.category_may_dispatch(
        connection,
        category="market_risk",
        summary="market observation",
        cooldown_seconds=1800,
        escalation_terms=["escalated"],
    ) is True
    ledger.record_category_dispatch(connection, category="market_risk", summary="market observation")
    assert ledger.category_may_dispatch(
        connection,
        category="market_risk",
        summary="market observation",
        cooldown_seconds=1800,
        escalation_terms=["escalated"],
    ) is False
    assert ledger.category_may_dispatch(
        connection,
        category="market_risk",
        summary="market observation escalated",
        cooldown_seconds=1800,
        escalation_terms=["escalated"],
    ) is True


def test_event_ledger_retention_removes_only_old_rows():
    connection = _connection()
    old = (datetime.now(UTC) - timedelta(days=31)).isoformat()
    connection.execute(
        """INSERT INTO event_ledger(
            canonical_key, event_type, source_url, person_fingerprint,
            location_fingerprint, action_fingerprint, first_discovered_at,
            last_reminded_at, escalated, verified_sources_json, last_title, updated_at
        ) VALUES (?, ?, '', '', '', '', ?, ?, 0, '[]', 'old', ?)""",
        ("old-key", "test", old, old, old),
    )
    connection.commit()
    assert ledger.prune_event_ledger(connection) == 1
    assert connection.execute("SELECT 1 FROM event_ledger WHERE canonical_key='old-key'").fetchone() is None
