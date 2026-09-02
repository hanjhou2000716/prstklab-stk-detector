import json
from datetime import UTC, datetime
from pathlib import Path

from src.external_observation_input import (
    external_source_health,
    external_source_health_from_remote,
    load_external_observations,
    merge_external_source_health,
)


def test_loads_only_public_safe_financialjuice_records(tmp_path):
    path = tmp_path / "external.json"
    path.write_text(json.dumps({"observations": [
        {
            "observation_id": "fj-1", "source": "financialjuice",
            "headline": "Public headline", "public_safe": True,
            "source_url": "https://financialjuice.com/item/1",
        },
        {
            "observation_id": "fj-private", "source": "financialjuice",
            "public_safe": True, "body": "raw mail must not cross boundary",
        },
        {"observation_id": "unknown", "source": "unknown", "public_safe": True},
    ]}), encoding="utf-8")
    accepted, rejected = load_external_observations(path)
    assert [item["observation_id"] for item in accepted] == ["fj-1"]
    assert rejected == 2
    assert "body" not in accepted[0]


def test_preserves_financialjuice_vendor_semantics_at_public_boundary(tmp_path):
    path = tmp_path / "external-rich.json"
    path.write_text(json.dumps({"observations": [{
        "observation_id": "fj-rich", "source": "financialjuice", "public_safe": True,
        "vendor_original_headline": "Company evaluates partnership",
        "vendor_translation": "某公司據報正在評估合作",
        "vendor_analysis": "目前仍未正式確認",
        "vendor_possible_impact": "可能影響 AI 伺服器供應鏈",
    }]}), encoding="utf-8")
    accepted, rejected = load_external_observations(path)
    assert rejected == 0
    assert accepted[0]["vendor_original_headline"] == "Company evaluates partnership"
    assert accepted[0]["vendor_translation"] == "某公司據報正在評估合作"
    assert accepted[0]["vendor_analysis"] == "目前仍未正式確認"
    assert accepted[0]["vendor_possible_impact"] == "可能影響 AI 伺服器供應鏈"


def test_loads_public_safe_creator_rows_without_treating_them_as_financialjuice(tmp_path):
    path = tmp_path / "creator.json"
    path.write_text(json.dumps({"observations": [{
        "observation_id": "jenny-1", "source": "jenny", "content_origin": "jenny",
        "episode_key": "jenny:episode-1", "episode_title": "Public episode",
        "claims": ["A public claim"], "public_safe": True,
    }]}), encoding="utf-8")
    accepted, rejected = load_external_observations(path)
    assert rejected == 0
    assert accepted[0]["content_origin"] == "jenny"
    assert accepted[0]["episode_key"] == "jenny:episode-1"


def test_loads_public_safe_financialjuice_compound_envelope_without_transport_id(tmp_path):
    path = tmp_path / "compound.json"
    path.write_text(json.dumps({
        "parse_status": "parsed",
        "message_id": "private-mail-id-must-not-propagate",
        "content_origin": "financialjuice",
        "content_type": "breaking_news",
        "compound": True,
        "public_safe": True,
        "item_count": 2,
        "items": [
            {
                "item_id": "fj-item-1", "content_hash": "a" * 64,
                "event_cluster_key": "fj-cluster-1", "candidate_event_type": "energy",
                "original_headline": "Oil supply risk", "vendor_importance": 8,
            },
            {
                "item_id": "fj-item-2", "content_hash": "b" * 64,
                "event_cluster_key": "fj-cluster-2", "candidate_event_type": "policy",
                "original_headline": "Export controls",
            },
        ],
    }), encoding="utf-8")
    accepted, rejected = load_external_observations(path)
    assert [item["observation_id"] for item in accepted] == ["fj-item-1", "fj-item-2"]
    assert rejected == 0
    assert all(item["source"] == "financialjuice" for item in accepted)
    assert all("message_id" not in item for item in accepted)


def test_compound_envelope_count_mismatch_fails_closed(tmp_path):
    path = tmp_path / "compound-invalid.json"
    path.write_text(json.dumps({
        "parse_status": "parsed", "content_origin": "financialjuice",
        "public_safe": True, "item_count": 2, "items": [],
    }), encoding="utf-8")
    accepted, rejected = load_external_observations(path)
    assert accepted == []
    assert rejected == 1


def test_unresolved_compound_envelope_does_not_emit_partial_observations(tmp_path):
    path = tmp_path / "compound-unresolved.json"
    path.write_text(json.dumps({
        "parse_status": "compound_unresolved", "message_id": "private-id",
        "content_origin": "financialjuice", "public_safe": True,
        "item_count": 1, "items": [],
    }), encoding="utf-8")
    accepted, rejected = load_external_observations(path)
    assert accepted == []
    assert rejected == 1


def test_compound_item_with_raw_private_field_is_rejected(tmp_path):
    path = tmp_path / "compound-private.json"
    path.write_text(json.dumps({
        "parse_status": "parsed", "content_origin": "financialjuice",
        "public_safe": True, "item_count": 1,
        "items": [{
            "item_id": "fj-item-private", "content_hash": "c" * 64,
            "event_cluster_key": "fj-cluster-private", "candidate_event_type": "energy",
            "original_headline": "Oil supply risk", "body": "raw private mail",
        }],
    }), encoding="utf-8")
    accepted, rejected = load_external_observations(path)
    assert accepted == []
    assert rejected == 1


def test_missing_or_malformed_input_is_explicitly_failed(tmp_path):
    missing = tmp_path / "missing.json"
    accepted, rejected = load_external_observations(missing)
    assert accepted == []
    assert rejected == 0
    row = external_source_health(path=missing, accepted=[], rejected=0, checked_at=datetime.now(UTC))
    assert row and row["semantic_state"] == "failed"


def test_loader_rejects_input_under_pages_tree(tmp_path, monkeypatch):
    site = tmp_path / "site"
    site.mkdir()
    path = site / "external.json"
    path.write_text(json.dumps({"observations": [{
        "observation_id": "fj-1", "source": "financialjuice", "public_safe": True,
    }]}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    accepted, rejected = load_external_observations(path)
    assert accepted == []
    assert rejected == 1


def test_external_health_merge_recomputes_gap_counts():
    health = {
        "status": "healthy", "sources": [{
            "key": "market_quotes", "status": "healthy", "semantic_state": "healthy",
        }], "missing_source_count": 0, "runtime_failure_count": 0,
        "configuration_missing_count": 0, "state_counts": {}, "observability": {},
    }
    row = external_source_health(
        path=Path("external.json"), accepted=[], rejected=1,
        checked_at=datetime.now(UTC),
    )
    merged = merge_external_source_health(health, row)
    assert merged["missing_source_count"] == 1
    assert merged["runtime_failure_count"] == 1
    assert merged["gap_source_keys"] == ["external_financialjuice"]


def test_external_health_exposes_financialjuice_observability_without_private_fields(tmp_path):
    (tmp_path / "external.json").write_text("[]", encoding="utf-8")
    row = external_source_health(
        path=tmp_path / "external.json",
        accepted=[
            {
                "observation_id": "fj-1", "source": "financialjuice", "public_safe": True,
                "vendor_importance": 8, "fetched_at": "2026-08-14T01:02:03Z",
                "event_cluster_key": "cluster-1", "official_confirmed": False,
                "market_sync_confirmed": False,
            },
            {
                "observation_id": "fj-2", "source": "financialjuice", "public_safe": True,
                "vendor_importance": 7, "fetched_at": "2026-08-14T01:03:03Z",
            },
        ],
        rejected=2,
        checked_at=datetime.now(UTC),
    )
    assert row is not None
    metrics = row["observability"]
    assert metrics["qualifying_item_count"] == 1
    assert metrics["pending_cluster_count"] == 1
    assert metrics["last_notification_decision"] == "eligible"
    assert metrics["parser_error_count"] == 2
    assert metrics["last_delivery_at"] is None
    assert "observation_id" not in metrics


def test_remote_external_health_preserves_status_and_fallback() -> None:
    checked_at = datetime.now(UTC)
    accepted = [{
        "observation_id": "fj-remote", "source": "financialjuice", "public_safe": True,
        "vendor_importance": 8,
    }]
    ready = external_source_health_from_remote(
        {"status": "ready", "count": 1, "rejected_count": 0},
        accepted=accepted, rejected=0, checked_at=checked_at,
    )
    assert ready["semantic_state"] == "healthy"
    assert ready["last_success_at"] == checked_at.isoformat()
    failed = external_source_health_from_remote(
        {"status": "failed", "reason": "http_503", "rejected_count": 0},
        accepted=accepted, rejected=0, checked_at=checked_at,
    )
    assert failed["semantic_state"] == "partial"
    assert failed["issues"] == ["http_503"]
    missing = external_source_health_from_remote(
        {"status": "configuration_missing", "reason": "not_configured", "rejected_count": 0},
        accepted=[], rejected=0, checked_at=checked_at,
    )
    assert missing["semantic_state"] == "configuration_missing"


def test_remote_empty_scan_aliases_are_successful_no_event_states() -> None:
    checked_at = datetime.now(UTC)
    for provider_status in ("no_new_content", "scan_complete", "empty", "idle"):
        row = external_source_health_from_remote(
            {"status": provider_status, "rejected_count": 0},
            accepted=[], rejected=0, checked_at=checked_at,
        )
        assert row["provider_status"] == provider_status
        assert row["semantic_state"] == "no_event"
        assert row["last_success_at"] == checked_at.isoformat()


def test_remote_configuration_aliases_remain_configuration_missing() -> None:
    checked_at = datetime.now(UTC)
    for provider_status in ("configuration_required", "not_configured"):
        row = external_source_health_from_remote(
            {"status": provider_status, "reason": "missing_secret"},
            accepted=[], rejected=0, checked_at=checked_at,
        )
        assert row["provider_status"] == provider_status
        assert row["semantic_state"] == "configuration_missing"
        assert row["last_success_at"] is None
