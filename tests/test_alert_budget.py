from datetime import UTC, datetime, timedelta

from src.alert_budget import decide_alert_budget

NOW = datetime(2026, 8, 5, 2, 0, tzinfo=UTC)


def test_alert_budget_blocks_duplicate_inside_cooldown():
    result = decide_alert_budget(
        {"event_key": "iran-1", "importance": "warning"},
        [{"event_key": "iran-1", "importance": "warning", "sent_at": (NOW - timedelta(minutes=5)).isoformat()}],
        now=NOW,
    )
    assert result == {"allowed": False, "reason": "cooldown", "upgraded": False, "event_key": "iran-1"}


def test_alert_budget_allows_risk_upgrade_during_cooldown():
    result = decide_alert_budget(
        {"event_key": "iran-1", "importance": "high-risk"},
        [{"event_key": "iran-1", "importance": "warning", "sent_at": (NOW - timedelta(minutes=5)).isoformat()}],
        now=NOW,
    )
    assert result["allowed"] is True
    assert result["upgraded"] is True
    assert result["reason"] == "risk_upgrade"


def test_alert_budget_applies_hourly_cap():
    history = [{"event_key": str(i), "importance": "normal", "sent_at": (NOW - timedelta(minutes=2)).isoformat()} for i in range(8)]
    result = decide_alert_budget({"event_key": "new", "importance": "normal"}, history, now=NOW, max_hourly=8)
    assert result["allowed"] is False
    assert result["reason"] == "hourly_budget_exhausted"


def test_alert_budget_normalizes_chinese_risk_labels_for_upgrade():
    result = decide_alert_budget(
        {"event_key": "iran-1", "risk_level": "高風險"},
        [{"event_key": "iran-1", "importance": "警戒", "sent_at": (NOW - timedelta(minutes=5)).isoformat()}],
        now=NOW,
    )
    assert result["allowed"] is True
    assert result["upgraded"] is True
    assert result["reason"] == "risk_upgrade"
