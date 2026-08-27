from datetime import UTC, datetime

from src.alert_orchestrator import prepare_alert

NOW = datetime(2026, 8, 27, 4, 0, tzinfo=UTC)


def test_missing_confirmation_remains_pending_and_is_not_deliverable():
    result = prepare_alert(
        {"event_key": "iran-1", "title": "能源供應觀察", "requires_crosscheck": True},
        release_id="release-1",
        snapshot_id="snapshot-1",
        now=NOW,
    )
    assert result["alert"]["lifecycle_state"] == "pending_confirmation"
    assert result["delivery_allowed"] is True  # observation notifications remain visible
    assert "等待核對" in result["alert"]["short_caption"]


def test_confirmed_material_change_is_escalated_and_budgeted():
    event = {
        "event_key": "oil-1",
        "title": "原油供應中斷",
        "lifecycle_state": "confirmed",
        "alert_type": "geopolitical_event",
        "severity": "high-risk",
        "importance": "high-risk",
        "official_confirmed": True,
        "second_source": True,
        "market_sync": True,
        "change_percent": 6.0,
        "market": "global",
    }
    result = prepare_alert(event, release_id="release-1", snapshot_id="snapshot-1", previous_change=0.0, now=NOW)
    assert result["alert"]["lifecycle_state"] == "escalated"
    assert result["budget"]["allowed"] is True
    assert result["delivery_allowed"] is True


def test_quality_block_suppresses_delivery_but_keeps_alert_provenance():
    result = prepare_alert(
        {"event_key": "stale-1", "title": "過期行情", "stale_used": True},
        release_id="release-1",
        snapshot_id="snapshot-1",
        now=NOW,
    )
    assert result["budget"]["reason"] == "stale_data"
    assert result["alert"]["lifecycle_state"] == "suppressed"
    assert result["delivery_allowed"] is False
    assert result["alert"]["release_id"] == "release-1"


def test_direction_reversal_is_material_without_a_large_delta():
    result = prepare_alert(
        {"event_key": "reverse-1", "title": "台指方向反轉", "change_percent": -0.2, "direction_reversed": True},
        release_id="release-1",
        snapshot_id="snapshot-1",
        previous_change=0.2,
        now=NOW,
    )
    assert result["material_change"] is True
