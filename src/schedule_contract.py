"""Canonical Taiwan-time schedule boundaries shared by Creator and releases."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TAIPEI_TIMEZONE = "Asia/Taipei"
TAIPEI = ZoneInfo(TAIPEI_TIMEZONE)
CREATOR_MORNING_BATCH_TIME = time(10, 30)
CREATOR_MORNING_LATE_GRACE_MINUTES = 180

# GitHub cron is UTC. These are the scheduled runs allowed to finalize or
# re-check the same day's Creator morning batch.
CREATOR_BATCH_CRON_SCHEDULES = frozenset({
    "30 2 * * 1-5",  # 10:30 Taipei
    "45 3 * * 1-5",  # 11:45 Taipei
    "15 5 * * 1-5",  # 13:15 Taipei
})


def creator_batch_cutoff(day: date) -> datetime:
    """Return the immutable 10:30 Asia/Taipei cutoff for ``day``."""
    return datetime.combine(day, CREATOR_MORNING_BATCH_TIME, tzinfo=TAIPEI)


def creator_batch_late_end(day: date) -> datetime:
    """Return the bounded late-arrival deadline in the same timezone."""
    return creator_batch_cutoff(day) + timedelta(minutes=CREATOR_MORNING_LATE_GRACE_MINUTES)


__all__ = [
    "CREATOR_BATCH_CRON_SCHEDULES",
    "CREATOR_MORNING_BATCH_TIME",
    "CREATOR_MORNING_LATE_GRACE_MINUTES",
    "TAIPEI",
    "TAIPEI_TIMEZONE",
    "creator_batch_cutoff",
    "creator_batch_late_end",
]
