"""Durable event-ledger and alert-cooldown persistence for Railway.

The monitor supplies already-normalized identity facts; this module owns only
SQLite state transitions for deduplication, cooldowns and retention.  It does
not classify events or decide release eligibility.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any


def category_may_dispatch(
    connection: sqlite3.Connection,
    *,
    category: str,
    summary: str,
    cooldown_seconds: int,
    escalation_terms: Iterable[str],
) -> bool:
    row = connection.execute(
        "SELECT summary, dispatched_at FROM dispatched WHERE category = ? ORDER BY rowid DESC LIMIT 1",
        (category,),
    ).fetchone()
    if row is None:
        return True
    previous_summary, previous_time = row
    try:
        elapsed = (datetime.now(UTC) - datetime.fromisoformat(str(previous_time))).total_seconds()
    except ValueError:
        return True
    if elapsed >= cooldown_seconds:
        return True
    current = summary.casefold()
    previous = str(previous_summary).casefold()
    return any(
        term.casefold() in current and term.casefold() not in previous
        for term in escalation_terms
    )


def record_category_dispatch(
    connection: sqlite3.Connection,
    *,
    category: str,
    summary: str,
) -> None:
    connection.execute(
        "INSERT INTO dispatched(category, summary, dispatched_at) VALUES (?, ?, ?)",
        (category, summary, datetime.now(UTC).isoformat()),
    )
    connection.commit()


def observe_alert(
    connection: sqlite3.Connection,
    *,
    canonical_key: str,
    event_type: str,
    source_urls: Iterable[str],
    fingerprints: dict[str, str],
    title: str,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    urls = sorted({str(url) for url in source_urls if str(url)})
    row = connection.execute(
        """SELECT first_discovered_at, last_reminded_at, escalated,
                  verified_sources_json
           FROM event_ledger WHERE canonical_key = ?""",
        (canonical_key,),
    ).fetchone()
    if row is None:
        connection.execute(
            """INSERT INTO event_ledger(
                canonical_key,event_type,source_url,person_fingerprint,
                location_fingerprint,action_fingerprint,first_discovered_at,
                last_reminded_at,escalated,verified_sources_json,last_title,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                canonical_key,
                event_type,
                urls[0] if urls else "",
                fingerprints.get("person", ""),
                fingerprints.get("location", ""),
                fingerprints.get("action", ""),
                now,
                None,
                0,
                json.dumps(urls),
                title,
                now,
            ),
        )
        connection.commit()
        return {
            "canonical_key": canonical_key,
            "is_new": True,
            "last_reminded_at": None,
            "escalated": False,
        }
    try:
        previous_sources = json.loads(row[3] or "[]") if row[3] else []
    except (TypeError, json.JSONDecodeError):
        previous_sources = []
    merged_sources = sorted(set(previous_sources) | set(urls)) if isinstance(previous_sources, list) else urls
    connection.execute(
        "UPDATE event_ledger SET verified_sources_json = ?, updated_at = ? WHERE canonical_key = ?",
        (json.dumps(merged_sources), now, canonical_key),
    )
    connection.commit()
    return {
        "canonical_key": canonical_key,
        "is_new": False,
        "last_reminded_at": row[1],
        "escalated": bool(row[2]),
    }


def mark_alert_reminded(
    connection: sqlite3.Connection,
    *,
    canonical_key: str,
    escalated: bool = False,
) -> None:
    now = datetime.now(UTC).isoformat()
    connection.execute(
        """UPDATE event_ledger
           SET last_reminded_at = ?,
               escalated = CASE WHEN ? THEN 1 ELSE escalated END,
               updated_at = ?
           WHERE canonical_key = ?""",
        (now, int(escalated), now, canonical_key),
    )
    connection.commit()


def ledger_may_dispatch(
    record: dict[str, Any],
    *,
    cooldown_seconds: int,
) -> bool:
    if record.get("is_new") or record.get("escalated"):
        return True
    raw = record.get("last_reminded_at")
    if not raw:
        return True
    try:
        return (datetime.now(UTC) - datetime.fromisoformat(str(raw))).total_seconds() >= cooldown_seconds
    except ValueError:
        return True


def prune_event_ledger(connection: sqlite3.Connection, retention_days: int = 30) -> int:
    cutoff = datetime.now(UTC).timestamp() - max(30, int(retention_days)) * 86400
    cursor = connection.execute(
        """DELETE FROM event_ledger
           WHERE strftime('%s', COALESCE(last_reminded_at, first_discovered_at)) < ?""",
        (str(int(cutoff)),),
    )
    connection.commit()
    return int(cursor.rowcount if cursor.rowcount >= 0 else 0)
