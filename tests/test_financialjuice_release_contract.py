from __future__ import annotations

from src.financialjuice_notification import financialjuice_notification_key
from src.financialjuice_release_contract import validate_financialjuice_release


def _snapshot() -> dict:
    canonical = "financialjuice-fact:fixture"
    version = "financialjuice-fact-version:fixture"
    notification_key = financialjuice_notification_key({
        "canonical_fact_key": canonical,
        "material_fact_version": version,
    })
    return {
        "financialjuice_observations": [{
            "observation_id": "fj-1",
            "canonical_fact_key": canonical,
            "material_fact_version": version,
            "notification_key": notification_key,
        }],
        "financialjuice_priority_decisions": [{
            "observation_id": "fj-1",
            "vendor_importance": 9,
            "vendor_priority_notification": True,
            "delivery_policy": "fj_priority",
            "notification_status": "eligible",
            "release_trace_required": True,
            "public_signal_eligible": True,
            "public_short_message": "🟣 FJ 9/10｜Oil supply risk。",
            "canonical_fact_key": canonical,
            "material_fact_version": version,
            "notification_key": notification_key,
            "identity_contract_status": "valid",
        }],
        "financialjuice_priority_events": [{
            "observation_id": "fj-1",
            "source_key": "financialjuice",
            "notification_status": "eligible",
            "vendor_priority_notification": True,
            "vendor_importance": 9,
            "delivery_policy": "fj_priority",
            "alert_eligible": True,
            "public_signal_eligible": True,
            "public_short_message": "🟣 FJ 9/10｜Oil supply risk。",
            "source_trace": {"vendor_importance_is_not_risk": True},
            "canonical_fact_key": canonical,
            "material_fact_version": version,
            "notification_key": notification_key,
            "identity_contract_status": "valid",
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


def test_financialjuice_release_contract_blocks_identity_lineage_mismatch() -> None:
    snapshot = _snapshot()
    snapshot["financialjuice_priority_events"][0]["canonical_fact_key"] = "financialjuice-fact:other"

    result = validate_financialjuice_release(snapshot)

    assert result["ok"] is False
    assert "event[0]:canonical_fact_key_mismatch" in result["errors"]


def test_financialjuice_release_contract_allows_snapshot_without_fj() -> None:
    result = validate_financialjuice_release({"events": {"items": []}})
    assert result["ok"] is True


def test_financialjuice_release_contract_allows_audited_stale_legacy_rows() -> None:
    snapshot = {
        "financialjuice_observations": [{"observation_id": "fj-stale"}],
        "financialjuice_priority_decisions": [{
            "observation_id": "fj-stale",
            "vendor_importance": 10,
            "vendor_priority_notification": False,
            "notification_status": "missing_source_timestamp",
            "release_trace_required": True,
            "public_signal_eligible": False,
            "public_short_message": "",
        }],
        "financialjuice_priority_events": [],
    }
    result = validate_financialjuice_release(snapshot)
    assert result["ok"] is True
    assert result["eligible_count"] == 0
    assert result["status"] == "ready"
