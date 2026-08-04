"""Append-only point-in-time fundamentals store used by research and backtests."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


def _dt(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=parsed.tzinfo or UTC)


@dataclass(frozen=True)
class FundamentalSnapshot:
    instrument_id: str
    metric: str
    value: float | None
    as_of: str
    published_at: str
    fetched_at: str
    source: str
    source_url: str
    restated: bool = False
    snapshot_id: str = ""

    def normalized(self) -> FundamentalSnapshot:
        published = _dt(self.published_at).isoformat()
        fetched = _dt(self.fetched_at).isoformat()
        if _dt(published) > _dt(fetched):
            raise ValueError("published_at cannot be later than fetched_at")
        payload = {key: value for key, value in asdict(self).items() if key != "snapshot_id"}
        snapshot_id = self.snapshot_id or hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:24]
        return FundamentalSnapshot(**{**payload, "published_at": published, "fetched_at": fetched, "snapshot_id": snapshot_id})


class PointInTimeStore:
    """SQLite index that never returns a filing published after the signal."""

    def __init__(self, path: Path | str = ":memory:") -> None:
        self.path = str(path)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS fundamentals (
                snapshot_id TEXT PRIMARY KEY, instrument_id TEXT NOT NULL,
                metric TEXT NOT NULL, value REAL, as_of TEXT NOT NULL,
                published_at TEXT NOT NULL, fetched_at TEXT NOT NULL,
                source TEXT NOT NULL, source_url TEXT NOT NULL, restated INTEGER NOT NULL
            )"""
        )
        self.connection.commit()

    def append(self, snapshot: FundamentalSnapshot) -> FundamentalSnapshot:
        row = snapshot.normalized()
        self.connection.execute(
            "INSERT OR IGNORE INTO fundamentals VALUES (?,?,?,?,?,?,?,?,?,?)",
            (row.snapshot_id, row.instrument_id, row.metric, row.value, row.as_of, row.published_at, row.fetched_at, row.source, row.source_url, int(row.restated)),
        )
        self.connection.commit()
        return row

    def append_many(self, snapshots: Iterable[FundamentalSnapshot]) -> int:
        count = 0
        for snapshot in snapshots:
            self.append(snapshot)
            count += 1
        return count

    def available_as_of(self, instrument_id: str, signal_at: str | datetime) -> list[FundamentalSnapshot]:
        signal = _dt(signal_at).isoformat()
        rows = self.connection.execute(
            "SELECT instrument_id,metric,value,as_of,published_at,fetched_at,source,source_url,restated,snapshot_id FROM fundamentals WHERE instrument_id=? AND published_at<=? ORDER BY metric,published_at DESC",
            (instrument_id, signal),
        ).fetchall()
        latest: dict[str, FundamentalSnapshot] = {}
        for values in rows:
            row = FundamentalSnapshot(
                instrument_id=str(values[0]), metric=str(values[1]), value=values[2],
                as_of=str(values[3]), published_at=str(values[4]), fetched_at=str(values[5]),
                source=str(values[6]), source_url=str(values[7]), restated=bool(values[8]),
                snapshot_id=str(values[9]),
            )
            latest.setdefault(row.metric, row)
        return list(latest.values())

    def close(self) -> None:
        self.connection.close()


def audit_no_lookahead(snapshots: Iterable[FundamentalSnapshot], signal_at: str | datetime) -> list[str]:
    """Return violations instead of allowing future filings into a backtest."""
    signal = _dt(signal_at)
    errors: list[str] = []
    for snapshot in snapshots:
        try:
            if _dt(snapshot.published_at) > signal:
                errors.append(f"{snapshot.instrument_id}:{snapshot.metric}:published_after_signal")
        except (TypeError, ValueError):
            errors.append(f"{snapshot.instrument_id}:{snapshot.metric}:invalid_timestamp")
    return errors
