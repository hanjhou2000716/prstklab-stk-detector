from datetime import UTC, datetime, timedelta

from src.alert_dispatch import evaluate_dispatch, record_dispatch
from src.event_ledger import EventLedger

NOW = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)


def _ledger(tmp_path):
    return EventLedger(tmp_path / "event-ledger.json")


def _event(**overrides):
    value = {
        "kind": "official_event",
        "event_type": "policy",
        "topic_key": "iran-talks",
        "title": "Official confirmation of talks",
        "published_at": NOW.isoformat(),
        "risk_level": "warning",
        "source_url": "https://example.test/events/1?utm_source=feed",
    }
    value.update(overrides)
    return value


def test_dispatch_gate_records_only_successful_delivery(tmp_path):
    ledger = _ledger(tmp_path)
    event = _event()

    first = evaluate_dispatch(event, ledger=ledger, now=NOW)
    assert first.allowed is True
    assert first.reason == "budget_available"

    # A failed send does not call record_dispatch, so the same event remains
    # eligible for a retry in the next workflow attempt.
    retry = evaluate_dispatch(event, ledger=ledger, now=NOW + timedelta(minutes=1))
    assert retry.allowed is True

    record_dispatch(event, ledger=ledger, now=NOW + timedelta(minutes=1))
    blocked = evaluate_dispatch(event, ledger=ledger, now=NOW + timedelta(minutes=2))
    assert blocked.allowed is False
    assert blocked.reason == "cooldown"
    assert blocked.cooldown_remaining > 0


def test_risk_upgrade_bypasses_cooldown(tmp_path):
    ledger = _ledger(tmp_path)
    event = _event(risk_level="warning")
    record_dispatch(event, ledger=ledger, now=NOW)

    escalated = _event(risk_level="high-risk", escalation=True)
    decision = evaluate_dispatch(escalated, ledger=ledger, now=NOW + timedelta(minutes=2))
    assert decision.allowed is True
    assert decision.upgraded is True


def test_hourly_budget_is_shared_across_event_types(tmp_path):
    ledger = _ledger(tmp_path)
    for index in range(2):
        event = _event(topic_key=f"event-{index}", title=f"event {index}")
        record_dispatch(event, ledger=ledger, now=NOW)

    next_event = _event(topic_key="event-3", title="event 3")
    decision = evaluate_dispatch(next_event, ledger=ledger, now=NOW + timedelta(minutes=1), max_hourly=2)
    assert decision.allowed is False
    assert decision.reason == "hourly_budget_exhausted"
