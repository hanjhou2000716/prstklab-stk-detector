from datetime import date, datetime

import pytest

from src.schedule_contract import (
    CREATOR_BATCH_CRON_SCHEDULES,
    CREATOR_MORNING_BATCH_TIME,
    LEGACY_SCHEDULE_CONTRACT_VERSION,
    SCHEDULE_CONTRACT_VERSION,
    SCHEDULE_TIMEZONE,
    TAIPEI,
    build_cron_job_dispatch_payload,
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
    assert result["reason"] == "invalid_schedule_context:missing_dispatch_unix"
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
        contract_version=LEGACY_SCHEDULE_CONTRACT_VERSION,
    )
    retired = validate_scheduled_context(
        slot="intraday",
        scheduled_for_at="2026-09-08T10:30:00+08:00",
        now=now,
        contract_version=LEGACY_SCHEDULE_CONTRACT_VERSION,
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
    assert client["schedule_contract_version"] == LEGACY_SCHEDULE_CONTRACT_VERSION
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
        contract_version=LEGACY_SCHEDULE_CONTRACT_VERSION,
        time_zone=SCHEDULE_TIMEZONE,
    )
    assert first is not None
    assert first["scheduled_slot"] == "post_close"
    assert first["slot_date"] == "2026-09-08"
    assert first["delivery_intent"] == "notify_candidate"


def test_cron_job_payload_uses_runtime_timestamp_and_trace_placeholders():
    payload = build_cron_job_dispatch_payload("morning", notify=False)
    client = payload["client_payload"]

    assert payload["event_type"] == "scheduled-brief"
    assert client == {
        "slot": "morning",
        "scheduled_slot": "morning",
        "dispatch_unix": "%cjo:unixtime%",
        "trace_id": "%cjo:uuid4%",
        "time_zone": SCHEDULE_TIMEZONE,
        "schedule_contract_version": SCHEDULE_CONTRACT_VERSION,
        "trigger_kind": "cron-job.org",
        "notify": False,
        "force": False,
    }


@pytest.mark.parametrize(
    ("slot", "dispatch", "expected"),
    (
        ("morning", "2026-09-09T06:00:30+08:00", "2026-09-09T06:00:00+08:00"),
        ("pre_open", "2026-09-09T08:45:30+08:00", "2026-09-09T08:45:00+08:00"),
        ("post_close", "2026-09-09T14:20:30+08:00", "2026-09-09T14:20:00+08:00"),
        ("us_premarket", "2026-09-09T21:00:30+08:00", "2026-09-09T21:00:00+08:00"),
    ),
)
def test_v3_dispatch_reconstructs_the_fixed_anchor(slot, dispatch, expected):
    from datetime import datetime

    dispatch_at = datetime.fromisoformat(dispatch)
    result = validate_scheduled_context(
        slot=slot,
        scheduled_for_at="",
        dispatch_unix=str(int(dispatch_at.timestamp())),
        now=dispatch_at,
        contract_version=SCHEDULE_CONTRACT_VERSION,
        time_zone=SCHEDULE_TIMEZONE,
    )

    assert result["contract_status"] == "valid"
    assert result["scheduled"].isoformat() == expected
    assert result["delay_seconds"] == 30


def test_v3_late_dispatch_is_publish_only_and_uses_anchor_delay():
    from datetime import datetime

    dispatch_at = datetime.fromisoformat("2026-09-09T06:40:00+08:00")
    result = validate_scheduled_context(
        slot="morning",
        scheduled_for_at="",
        dispatch_unix=str(int(dispatch_at.timestamp())),
        now=dispatch_at,
        contract_version=SCHEDULE_CONTRACT_VERSION,
        time_zone=SCHEDULE_TIMEZONE,
    )

    assert result["contract_status"] == "valid"
    assert result["reason"] == "late_schedule_publish_only"
    assert result["delay_seconds"] == 40 * 60


def test_v3_us_premarket_after_midnight_keeps_the_previous_slot_date():
    from datetime import datetime

    dispatch_at = datetime.fromisoformat("2026-09-10T01:30:00+08:00")
    result = validate_scheduled_context(
        slot="us_premarket",
        scheduled_for_at="",
        dispatch_unix=str(int(dispatch_at.timestamp())),
        now=dispatch_at,
        contract_version=SCHEDULE_CONTRACT_VERSION,
        time_zone=SCHEDULE_TIMEZONE,
    )

    assert result["contract_status"] == "valid"
    assert result["slot_date"] == "2026-09-09"
    assert result["scheduled"].isoformat() == "2026-09-09T21:00:00+08:00"


def test_v3_dispatch_after_the_next_anchor_is_rejected():
    from datetime import datetime

    dispatch_at = datetime.fromisoformat("2026-09-09T08:41:00+08:00")
    result = validate_scheduled_context(
        slot="morning",
        scheduled_for_at="",
        dispatch_unix=str(int(dispatch_at.timestamp())),
        now=dispatch_at,
        contract_version=SCHEDULE_CONTRACT_VERSION,
        time_zone=SCHEDULE_TIMEZONE,
    )

    assert result["reason"] == "invalid_schedule_context:dispatch_outside_anchor_window"
