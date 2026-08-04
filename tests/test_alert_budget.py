from datetime import datetime, timedelta

from src.alert_budget import AlertBudget, merge_low_risk


def test_cooldown_blocks_normal_event():
    now = datetime(2026, 8, 4, 10)
    decision = AlertBudget().decide(now=now, event_key="x", event_times=[now - timedelta(minutes=5)], hourly_times=[])
    assert not decision.allowed
    assert decision.reason == "event_cooldown"


def test_high_priority_can_upgrade():
    now = datetime(2026, 8, 4, 10)
    decision = AlertBudget().decide(now=now, event_key="x", event_times=[now], hourly_times=[now] * 20, priority="high")
    assert decision.allowed


def test_digest_is_bounded():
    result = merge_low_risk([{"id": str(i)} for i in range(6)])
    assert result["merged"]
    assert len(result["events"]) == 4
