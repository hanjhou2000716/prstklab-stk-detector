from datetime import UTC, datetime, timedelta

from src.incident_cadence import (
    can_emit_pending_alert,
    clear_pending_alert,
    mark_pending_alert,
    preserve_pending_alert,
)


def test_pending_alert_reservation_enforces_thirty_minute_retry_window():
    now = datetime(2026, 10, 25, 2, 0, tzinfo=UTC)
    body = mark_pending_alert("incident\nNext reminder at: 2026-10-25T02:00:00+00:00", "100/1", now)

    assert can_emit_pending_alert(body, "100/1", now + timedelta(minutes=29, seconds=59)) is False
    assert can_emit_pending_alert(body, "101/1", now + timedelta(minutes=29, seconds=59)) is False
    assert can_emit_pending_alert(body, "101/1", now + timedelta(minutes=30)) is True


def test_pending_alert_legacy_marker_uses_due_time_and_malformed_marker_fails_closed():
    now = datetime(2026, 10, 25, 2, 30, tzinfo=UTC)
    legacy = "incident\nAlert pending consumer: 100/1\nNext reminder at: 2026-10-25T02:00:00+00:00"
    malformed = legacy + "\nAlert pending since: invalid"

    assert can_emit_pending_alert(legacy, "101/1", now) is True
    assert can_emit_pending_alert(malformed, "101/1", now) is False


def test_pending_alert_preserve_and_clear_are_identity_scoped():
    now = datetime(2026, 10, 25, 2, 0, tzinfo=UTC)
    prior = mark_pending_alert("old evidence", "100/2", now)
    updated = preserve_pending_alert("new evidence", prior)

    assert updated.splitlines() == [
        "new evidence",
        "Alert pending consumer: 100/2",
        f"Alert pending since: {now.isoformat()}",
    ]
    assert clear_pending_alert(updated.splitlines()) == ["new evidence"]
