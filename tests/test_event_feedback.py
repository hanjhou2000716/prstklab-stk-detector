import pytest

from src.event_feedback import normalize_feedback, summarize_feedback


def test_unreviewed_feedback_does_not_change_metrics():
    result = summarize_feedback([
        {"cluster_id": "a", "label": "correct", "reviewed": True},
        {"cluster_id": "b", "label": "irrelevant", "reviewed": True},
        {"cluster_id": "c", "label": "correct", "reviewed": False},
    ])
    assert result["reviewed_count"] == 2
    assert result["precision"] == 0.5
    assert result["threshold_update_allowed"] is False


def test_delivery_quality_metrics_are_explicit():
    result = summarize_feedback([
        {"cluster_id": "a", "label": "correct", "reviewed": True},
        {"cluster_id": "b", "label": "too_late", "reviewed": True},
        {"cluster_id": "c", "label": "insufficient_source", "reviewed": True},
    ])
    assert result["too_late_rate"] == pytest.approx(0.3333)
    assert result["source_insufficiency_rate"] == pytest.approx(0.3333)
    assert result["delivery_usable_rate"] == pytest.approx(0.3333)


def test_unknown_label_fails_closed():
    with pytest.raises(ValueError):
        normalize_feedback({"label": "buy"})