from __future__ import annotations

from src.financialjuice_release_contract import validate_financialjuice_release


def _snapshot() -> dict:
    return {
        "financialjuice_observations": [{"observation_id": "fj-1"}],
        "financialjuice_priority_decisions": [{
            "observation_id": "fj-1",
            "vendor_importance": 9,
            "vendor_priority_notification": True,
            "notification_status": "eligible",
            "release_trace_required": True,
        }],
        "financialjuice_priority_events": [{
            "observation_id": "fj-1",
            "source_key": "financialjuice",
            "notification_status": "eligible",
            "vendor_priority_notification": True,
            "alert_eligible": True,
            "source_trace": {"vendor_importance_is_not_risk": True},
        }],
    }


def test_financialjuice_release_contract_accepts_aligned_eligible_item() -> None:
    result = validate_financialjuice_release(_snapshot())
    assert result["ok"] is True
    assert result["status"] == "ready"
    assert result["eligible_count"] == 1


def test_financialjuice_release_contract_blocks_orphan_eligible_decision() -> None:
    snapshot = _snapshot()
    snapshot["financialjuice_priority_events"] = []
    result = validate_financialjuice_release(snapshot)
    assert result["ok"] is False
    assert "eligible_events_missing:fj-1" in result["errors"]


def test_financialjuice_release_contract_blocks_vendor_risk_mixup() -> None:
    snapshot = _snapshot()
    snapshot["financialjuice_priority_events"][0]["source_trace"] = {}
    result = validate_financialjuice_release(snapshot)
    assert result["ok"] is False
    assert "event[0]:vendor_risk_separation_missing" in result["errors"]


def test_financialjuice_release_contract_allows_snapshot_without_fj() -> None:
    result = validate_financialjuice_release({"events": {"items": []}})
    assert result["ok"] is True
    assert result["status"] == "ready"
