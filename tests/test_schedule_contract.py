from datetime import date, datetime

import pytest

from src.schedule_contract import (
    CREATOR_BATCH_CRON_SCHEDULES,
    CREATOR_MORNING_BATCH_TIME,
    SCHEDULE_CONTRACT_VERSION,
    SCHEDULE_TIMEZONE,
    TAIPEI,
    build_scheduled_dispatch_payload,
    creator_batch_cutoff,
    creator_batch_late_end,
    validate_scheduled_context,
)
from src.scheduled_brief import resolve_schedule_diagnostic, resolve_slot_context


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


def test_repository_dispatch_without_scheduled_for_is_an_explicit_contract_error():
    now = datetime(2026, 9, 8, 21, 0, tzinfo=TAIPEI)
    result = resolve_schedule_diagnostic(
        "us_premarket",
        now,
        trigger_kind="repository_dispatch",
        contract_version=SCHEDULE_CONTRACT_VERSION,
        time_zone=SCHEDULE_TIMEZONE,
    )

    assert result["valid"] is False
    assert result["reason"] == "invalid_schedule_context:missing_scheduled_for_at"
    context = result["context"]
    assert isinstance(context, dict)
    assert context["delivery_intent"] == "publish_only"
    assert context["contract_status"] == "invalid"


def test_repository_dispatch_requires_contract_version_and_timezone():
    now = datetime(2026, 9, 8, 21, 0, tzinfo=TAIPEI)
    missing_version = validate_scheduled_context(
        slot="us_premarket",
        scheduled_for_at="2026-09-08T21:00:00+08:00",
        now=now,
        contract_version="",
        time_zone=SCHEDULE_TIMEZONE,
    )
    bad_timezone = validate_scheduled_context(
        slot="us_premarket",
        scheduled_for_at="2026-09-08T21:00:00+08:00",
        now=now,
        contract_version=SCHEDULE_CONTRACT_VERSION,
        time_zone="UTC",
    )

    assert missing_version["reason"].endswith("unsupported_contract_version")
    assert bad_timezone["reason"].endswith("invalid_time_zone")


def test_repository_dispatch_rejects_naive_or_retired_schedule_context():
    now = datetime(2026, 9, 8, 14, 20, tzinfo=TAIPEI)
    naive = validate_scheduled_context(
        slot="post_close",
        scheduled_for_at="2026-09-08T14:20:00",
        now=now,
    )
    retired = validate_scheduled_context(
        slot="intraday",
        scheduled_for_at="2026-09-08T10:30:00+08:00",
        now=now,
    )

    assert naive["reason"].endswith("invalid_scheduled_for_at")
    assert retired["reason"].endswith("retired_routine_slot")


def test_backup_payload_is_canonical_and_validates_at_receiver():
    payload = build_scheduled_dispatch_payload(
        "pre_open",
        "2026-09-08T08:45:00+08:00",
        trigger_kind="cron-job.org",
    )
    client = payload["client_payload"]

    assert payload["event_type"] == "scheduled-brief"
    assert client["scheduled_slot"] == "pre_open"
    assert client["schedule_contract_version"] == SCHEDULE_CONTRACT_VERSION
    assert client["time_zone"] == SCHEDULE_TIMEZONE
    assert client["scheduled_for_at"] == "2026-09-08T08:45:00+08:00"


def test_backup_payload_rejects_non_anchor_slots():
    with pytest.raises(ValueError, match="retired_routine_slot"):
        build_scheduled_dispatch_payload(
            "intraday",
            "2026-09-08T10:30:00+08:00",
        )


def test_same_anchor_content_is_still_resolved_as_one_fixed_identity():
    first = resolve_slot_context(
        "post_close",
        datetime(2026, 9, 8, 14, 20, tzinfo=TAIPEI),
        trigger_kind="repository_dispatch",
        scheduled_for_at="2026-09-08T14:20:00+08:00",
        contract_version=SCHEDULE_CONTRACT_VERSION,
        time_zone=SCHEDULE_TIMEZONE,
    )
    assert first is not None
    assert first["scheduled_slot"] == "post_close"
    assert first["slot_date"] == "2026-09-08"
    assert first["delivery_intent"] == "notify_candidate"
