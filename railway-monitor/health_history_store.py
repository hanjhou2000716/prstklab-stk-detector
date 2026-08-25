"""Durable, privacy-safe Railway monitor health-history queries."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def _safe_sample(sample: dict[str, Any]) -> tuple[str, str, int, int, str]:
    """Validate and serialize only the public health sample contract."""
    recorded_at = str(sample.get("recorded_at") or "").strip()
    if not recorded_at:
        raise ValueError("health sample requires recorded_at")
    component_statuses = sample.get("component_statuses")
    if not isinstance(component_statuses, dict):
        raise ValueError("health sample component_statuses must be an object")
    statuses = {
        str(key): str(value)
        for key, value in component_statuses.items()
        if str(key).strip() and str(value).strip()
    }
    # Only aggregate counters and status labels cross into durable storage.
    # This explicitly prevents accidental persistence of tokens, bodies,
    # transport identifiers or recipient data if the runtime state grows.
    try:
        failure_count = max(0, int(sample.get("failure_count") or 0))
        no_event_count = max(0, int(sample.get("no_event_count") or 0))
    except (TypeError, ValueError) as error:
        raise ValueError("health sample counters must be integers") from error
    overall_state = str(sample.get("overall_state") or "not_checked").strip()
    if not overall_state:
        overall_state = "not_checked"
    return (
        recorded_at,
        overall_state,
        failure_count,
        no_event_count,
        json.dumps(statuses, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    )


def append_health_sample(
    connection: sqlite3.Connection,
    sample: dict[str, Any],
    *,
    max_samples: int = 168,
) -> None:
    """Upsert one sample and prune older rows to the seven-day bound."""
    recorded_at, overall_state, failure_count, no_event_count, statuses = _safe_sample(sample)
    bound = max(1, min(10_000, int(max_samples)))
    connection.execute(
        """INSERT INTO health_samples(
            recorded_at, overall_state, failure_count, no_event_count, component_statuses_json
        ) VALUES(?,?,?,?,?)
        ON CONFLICT(recorded_at) DO UPDATE SET
            overall_state=excluded.overall_state,
            failure_count=excluded.failure_count,
            no_event_count=excluded.no_event_count,
            component_statuses_json=excluded.component_statuses_json""",
        (recorded_at, overall_state, failure_count, no_event_count, statuses),
    )
    connection.execute(
        """DELETE FROM health_samples
           WHERE recorded_at NOT IN (
             SELECT recorded_at FROM health_samples ORDER BY recorded_at DESC LIMIT ?
           )""",
        (bound,),
    )
    connection.commit()


def load_health_samples(
    connection: sqlite3.Connection,
    *,
    max_samples: int = 168,
) -> list[dict[str, Any]]:
    """Load the bounded public sample projection in chronological order."""
    bound = max(1, min(10_000, int(max_samples)))
    rows = connection.execute(
        """SELECT recorded_at, overall_state, failure_count, no_event_count,
                  component_statuses_json
           FROM health_samples ORDER BY recorded_at DESC LIMIT ?""",
        (bound,),
    ).fetchall()
    samples: list[dict[str, Any]] = []
    for recorded_at, overall_state, failure_count, no_event_count, statuses_json in reversed(rows):
        try:
            statuses = json.loads(statuses_json)
        except (TypeError, json.JSONDecodeError):
            statuses = {}
        if not isinstance(statuses, dict):
            statuses = {}
        samples.append({
            "recorded_at": str(recorded_at),
            "overall_state": str(overall_state),
            "failure_count": max(0, int(failure_count or 0)),
            "no_event_count": max(0, int(no_event_count or 0)),
            "component_statuses": {
                str(key): str(value) for key, value in statuses.items()
                if str(key).strip() and str(value).strip()
            },
        })
    return samples


__all__ = ["append_health_sample", "load_health_samples"]
