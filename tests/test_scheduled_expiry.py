from datetime import UTC, datetime

from src.scheduled_expiry import expired_occurrence, main


def test_taipei_backup_after_original_thirty_minute_deadline_expires():
    result = expired_occurrence(
        event_name="schedule",
        schedule="45 0 * * 1-5",
        payload={"run_created_at": "2026-10-06T00:45:00Z"},
        now=datetime(2026, 10, 6, 1, 15, tzinfo=UTC),
    )
    assert result is not None
    assert result["slot"] == "pre_open"
    assert result["slot_date"] == "2026-10-06"
    assert result["deadline"] == "2026-10-06T09:15:00+08:00"
    assert result["reason"] == "expired_scheduled_occurrence"


def test_run_before_deadline_does_not_expire_and_expiry_is_inclusive():
    payload = {"run_created_at": "2026-10-06T00:45:00Z"}
    assert expired_occurrence(
        event_name="schedule", schedule="45 0 * * 1-5", payload=payload,
        now=datetime(2026, 10, 6, 1, 14, 59, tzinfo=UTC),
    ) is None
    assert expired_occurrence(
        event_name="schedule", schedule="45 0 * * 1-5", payload=payload,
        now=datetime(2026, 10, 6, 1, 15, tzinfo=UTC),
    ) is not None


def test_new_york_expiry_uses_daylight_saving_timezone_and_fixed_anchor():
    result = expired_occurrence(
        event_name="repository_dispatch",
        payload={
            "slot": "us_premarket",
            "dispatch_unix": "1791291600",
            "schedule_contract_version": "4",
            "time_zone": "America/New_York",
            "trace_id": "scheduled-us-20261006",
        },
        now=datetime(2026, 10, 6, 14, 0, tzinfo=UTC),
    )
    assert result is not None
    assert result["slot"] == "us_premarket"
    assert result["slot_date"] == "2026-10-06"
    assert result["anchor"].endswith("-04:00")
    assert result["deadline"].endswith("-04:00")


def test_manual_or_unknown_schedule_never_gets_silently_expired():
    assert expired_occurrence(
        event_name="workflow_dispatch", schedule="45 0 * * 1-5",
        now=datetime(2026, 10, 6, 12, 0, tzinfo=UTC),
    ) is None
    assert expired_occurrence(
        event_name="schedule", schedule="unknown",
        payload={"run_created_at": "2026-10-06T00:45:00Z"},
        now=datetime(2026, 10, 6, 12, 0, tzinfo=UTC),
    ) is None


def test_repository_dispatch_keeps_original_date_and_rejects_invalid_timestamp():
    result = expired_occurrence(
        event_name="repository_dispatch",
        payload={
            "slot": "pre_open",
            "dispatch_unix": "1791247500",
            "schedule_contract_version": "4",
            "time_zone": "Asia/Taipei",
            "trace_id": "scheduled-tw-20261006",
        },
        now=datetime(2026, 10, 6, 12, 0, tzinfo=UTC),
    )
    assert result is not None
    assert result["slot"] == "pre_open"
    assert result["slot_date"] == "2026-10-06"
    assert expired_occurrence(
        event_name="repository_dispatch",
        payload={"slot": "pre_open", "dispatch_unix": "%cjo:unixtime%"},
        now=datetime(2026, 10, 6, 12, 0, tzinfo=UTC),
    ) is None


def test_invalid_dispatch_contract_is_not_misclassified_as_normal_expiry():
    result = expired_occurrence(
        event_name="repository_dispatch",
        payload={
            "slot": "pre_open",
            "dispatch_unix": "1791247500",
            "schedule_contract_version": "99",
            "time_zone": "Asia/Taipei",
            "trace_id": "scheduled-tw-20261006",
        },
        now=datetime(2026, 10, 6, 12, 0, tzinfo=UTC),
    )
    assert result is None


def test_legacy_explicit_timestamp_dispatch_is_checked_without_optional_market_packages():
    result = expired_occurrence(
        event_name="repository_dispatch",
        payload={
            "slot": "pre_open",
            "contract_version": "2",
            "time_zone": "Asia/Taipei",
            "scheduled_for_at": "2026-10-06T08:45:00+08:00",
        },
        now=datetime(2026, 10, 6, 12, 0, tzinfo=UTC),
    )
    assert result is not None
    assert result["slot"] == "pre_open"
    assert result["anchor"] == "2026-10-06T08:45:00+08:00"


def test_non_expired_path_always_writes_explicit_false_output(monkeypatch, tmp_path):
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_EVENT_PATH", "")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    assert main() == 0
    assert output.read_text(encoding="utf-8") == "expired=false\n"
