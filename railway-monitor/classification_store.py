"""Durable classification state for the Railway monitor.

This module owns only the SQLite state transitions for ``seen`` and
``incoming_events``.  Keyword matching and dispatch policy remain in the
canonical classifier and monitor, so a state-store extraction cannot create a
second classification implementation.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Any

_ALLOWED_CLASSIFICATIONS = frozenset({"unclassified", "in_scope", "out_of_scope", "baseline"})


def _now() -> str:
    return datetime.now(UTC).isoformat()


def record_incoming_flash(
    connection: sqlite3.Connection,
    *,
    event_id: str,
    title: str,
    content: str,
    occurred_at: str,
    classification_reason: str | None = None,
    source: str = "jin10",
) -> None:
    now = _now()
    connection.execute(
        """INSERT INTO incoming_events(event_id,source,title,content,occurred_at,classification_reason,first_seen_at,last_seen_at)
           VALUES(?,?,?,?,?,?,?,?)
           ON CONFLICT(event_id) DO UPDATE SET title=excluded.title, content=excluded.content,
             occurred_at=excluded.occurred_at,
             classification_reason=CASE WHEN incoming_events.classification='unclassified'
               THEN COALESCE(excluded.classification_reason, incoming_events.classification_reason)
               ELSE incoming_events.classification_reason END,
             last_seen_at=excluded.last_seen_at""",
        (event_id, source, title, content, occurred_at, classification_reason, now, now),
    )
    connection.commit()


def set_classification_reason(
    connection: sqlite3.Connection,
    event_id: str,
    reason: str,
    error: str | None = None,
) -> None:
    connection.execute(
        "UPDATE incoming_events SET classification_reason=?, last_error=?, last_seen_at=? WHERE event_id=?",
        (str(reason)[:200], error[:500] if error else None, _now(), event_id),
    )
    connection.commit()


def classification_reason_counts(connection: sqlite3.Connection) -> dict[str, int]:
    rows = connection.execute(
        """SELECT COALESCE(classification_reason, 'unknown'), COUNT(*)
           FROM incoming_events WHERE classification='unclassified'
           GROUP BY COALESCE(classification_reason, 'unknown')"""
    ).fetchall()
    return {str(reason): int(count) for reason, count in rows}


def classification_diagnostics(connection: sqlite3.Connection) -> dict[str, Any]:
    rows = connection.execute(
        """SELECT COALESCE(classification, 'unknown'), COUNT(*)
           FROM incoming_events GROUP BY COALESCE(classification, 'unknown')"""
    ).fetchall()
    reason_counts = classification_reason_counts(connection)
    return {
        "classification_counts": {str(label): int(count) for label, count in rows},
        "reason_counts": reason_counts,
        "unclassified_count": sum(reason_counts.values()),
    }


def release_classification(connection: sqlite3.Connection, event_id: str, error: str) -> None:
    now = _now()
    connection.execute(
        "UPDATE seen SET classification='unclassified', classified_at=NULL WHERE event_id=?",
        (event_id,),
    )
    connection.execute(
        "UPDATE incoming_events SET classification='unclassified', classification_reason=?, last_error=?, last_seen_at=? WHERE event_id=?",
        (f"dispatch_failed:{error[:120]}" if error else "dispatch_failed", error[:500], now, event_id),
    )
    connection.commit()


def add_if_new(connection: sqlite3.Connection, event_id: str) -> bool:
    cursor = connection.execute(
        "INSERT OR IGNORE INTO seen(event_id, first_seen_at, classification) VALUES (?, ?, 'unclassified')",
        (event_id, _now()),
    )
    connection.commit()
    return cursor.rowcount == 1


def claim_classification(connection: sqlite3.Connection, event_id: str, classification: str) -> bool:
    """Claim an event once while allowing legacy unclassified rows to retry."""
    if classification not in _ALLOWED_CLASSIFICATIONS:
        raise ValueError(f"unsupported event classification: {classification}")
    now = _now()
    row = connection.execute(
        "SELECT classification FROM seen WHERE event_id = ?", (event_id,)
    ).fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO seen(event_id, first_seen_at, classification, classified_at) VALUES (?, ?, ?, ?)",
            (event_id, now, classification, now if classification != "unclassified" else None),
        )
        connection.commit()
        return classification != "unclassified"
    previous = str(row[0] or "unclassified")
    if previous != "unclassified" or classification == "unclassified":
        return False
    connection.execute(
        "UPDATE seen SET classification = ?, classified_at = ? WHERE event_id = ? AND classification = 'unclassified'",
        (classification, now, event_id),
    )
    connection.execute(
        "UPDATE incoming_events SET classification = ?, last_seen_at = ? WHERE event_id = ?",
        (classification, now, event_id),
    )
    connection.commit()
    return True


def classification_for(connection: sqlite3.Connection, event_id: str) -> str | None:
    row = connection.execute(
        "SELECT classification FROM seen WHERE event_id = ?", (event_id,)
    ).fetchone()
    return str(row[0]) if row and row[0] else None


def set_classification(connection: sqlite3.Connection, event_id: str, classification: str) -> None:
    if classification not in {"in_scope", "out_of_scope", "baseline"}:
        raise ValueError(f"unsupported event classification: {classification}")
    now = _now()
    connection.execute(
        "UPDATE seen SET classification = ?, classified_at = ? WHERE event_id = ?",
        (classification, now, event_id),
    )
    connection.execute(
        "UPDATE incoming_events SET classification = ?, last_seen_at = ? WHERE event_id = ?",
        (classification, now, event_id),
    )
    connection.commit()
