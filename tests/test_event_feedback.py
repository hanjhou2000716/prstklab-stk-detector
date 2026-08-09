import pytest

from src.event_feedback import build_feedback_contract, record_feedback, summarize_feedback


def test_feedback_contract_is_public_safe_and_does_not_mutate_policy():
    contract = build_feedback_contract(
        {"event_cluster_key": "cluster-1", "event_type": "geopolitical_event"}
    )
    assert contract["event_key"] == "cluster-1"
    assert contract["event_type"] == "geopolitical_event"
    assert contract["review_required"] is True
    assert contract["policy_update_allowed"] is False
    assert contract["pii_included"] is False
    assert set(contract["labels"]) == {
        "correct", "irrelevant", "duplicate", "wrong_direction",
        "insufficient_source", "too_late", "not_needed",
    }
    assert "chat_id" not in contract


def test_feedback_contract_does_not_invent_an_event_key():
    contract = build_feedback_contract({"event_type": "briefing"})
    assert "event_key" not in contract
    assert contract["enabled"] is True


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
