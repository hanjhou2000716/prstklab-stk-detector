"""P0-22 event timeline continuity and reviewed-feedback contracts."""

import pytest

from src.event_feedback import build_feedback_contract, record_feedback, summarize_feedback
from src.event_timeline import build_timeline


def test_p0_22_timeline_keeps_cluster_versions_auditable() -> None:
    rows = build_timeline([
        {"event_cluster_key": "cluster-1", "market": "global", "risk_level": "R2", "published_at": "2026-08-12T01:00:00Z"},
        {"event_cluster_key": "cluster-1", "market": "global", "risk_level": "R4", "published_at": "2026-08-12T02:00:00Z"},
    ], market="global", risk_level="R4")
    assert len(rows) == 1
    assert rows[0]["event_cluster_key"] == "cluster-1"


def test_p0_22_feedback_is_review_only_and_pii_free() -> None:
    contract = build_feedback_contract({"event_cluster_key": "cluster-1", "event_type": "conflict"})
    row = record_feedback({"event_cluster_key": "cluster-1", "label": "correct", "chat_id": "private"})
    assert contract["review_required"] is True
    assert contract["policy_update_allowed"] is False
    assert "chat_id" not in row
    with pytest.raises(ValueError):
        record_feedback({"event_key": "cluster-1", "label": "unknown"})


def test_p0_22_feedback_metrics_only_use_reviewed_rows() -> None:
    rows = [
        record_feedback({"event_key": "a", "label": "correct", "reviewed": True}),
        record_feedback({"event_key": "b", "label": "irrelevant", "reviewed": True}),
        record_feedback({"event_key": "c", "label": "correct", "reviewed": False}),
    ]
    summary = summarize_feedback(rows, expected_relevant=2)
    assert summary["reviewed_count"] == 2
    assert summary["precision"] == 0.5
    assert summary["policy_update_allowed"] is False
