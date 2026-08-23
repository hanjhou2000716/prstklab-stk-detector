from datetime import date

from src.schedule_contract import (
    CREATOR_BATCH_CRON_SCHEDULES,
    CREATOR_MORNING_BATCH_TIME,
    TAIPEI,
    creator_batch_cutoff,
    creator_batch_late_end,
)


def test_creator_batch_contract_is_1030_taipei_with_bounded_late_window() -> None:
    day = date(2026, 8, 21)
    cutoff = creator_batch_cutoff(day)
    late_end = creator_batch_late_end(day)
    assert CREATOR_MORNING_BATCH_TIME.hour == 10
    assert CREATOR_MORNING_BATCH_TIME.minute == 30
    assert cutoff.tzinfo == TAIPEI
    assert late_end == cutoff.replace(hour=13, minute=30)


def test_creator_batch_recheck_crons_are_explicit_utc_contract() -> None:
    assert CREATOR_BATCH_CRON_SCHEDULES == {
        "30 2 * * 1-5",
        "45 3 * * 1-5",
        "15 5 * * 1-5",
    }
