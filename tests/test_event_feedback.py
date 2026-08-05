import pytest

from src.event_feedback import record_feedback, summarize_feedback


def test_feedback_is_pii_free_and_requires_known_label():
    row = record_feedback({"event_key": "cluster-1", "label": "correct", "chat_id": "secret"})
    assert row["event_key"] == "cluster-1"
    assert "chat_id" not in row
    with pytest.raises(ValueError):
        record_feedback({"event_key": "cluster-1", "label": "unknown"})


def test_feedback_summary_reports_quality_and_delivery_delay():
    rows = [
        record_feedback({"event_key": "a", "label": "correct", "reviewed": True, "event_seen_at": "2026-08-05T00:00:00+00:00", "delivered_at": "2026-08-05T00:00:30+00:00"}),
        record_feedback({"event_key": "b", "label": "irrelevant", "reviewed": True}),
        record_feedback({"event_key": "c", "label": "correct", "reviewed": False}),
    ]
    summary = summarize_feedback(rows, expected_relevant=2)
    assert summary["reviewed_count"] == 2
    assert summary["precision"] == 0.5
    assert summary["recall"] == 0.5
    assert summary["mean_time_to_detect_seconds"] == 30
    assert summary["policy_update_allowed"] is False
