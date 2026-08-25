from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "railway-monitor"))

from health_history_store import append_health_sample, load_health_samples  # noqa: E402


def test_health_samples_are_durable_bounded_and_redacted() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute(
        """CREATE TABLE health_samples (
            recorded_at TEXT PRIMARY KEY,
            overall_state TEXT NOT NULL,
            failure_count INTEGER NOT NULL,
            no_event_count INTEGER NOT NULL,
            component_statuses_json TEXT NOT NULL
        )"""
    )
    for index in range(4):
        append_health_sample(connection, {
            "recorded_at": f"2026-08-25T00:0{index}:00+00:00",
            "overall_state": "healthy",
            "failure_count": 0,
            "no_event_count": 1,
            "component_statuses": {"gdelt": "no_event"},
            "secret": "must-not-persist",
        }, max_samples=2)
    rows = load_health_samples(connection, max_samples=2)
    assert [row["recorded_at"] for row in rows] == [
        "2026-08-25T00:02:00+00:00", "2026-08-25T00:03:00+00:00",
    ]
    assert "secret" not in str(rows)
