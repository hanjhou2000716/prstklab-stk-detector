import json
from datetime import UTC, datetime
from pathlib import Path

from src.external_observation_input import external_source_health, load_external_observations, merge_external_source_health


def test_loader_rejects_private_and_unknown_rows(tmp_path: Path) -> None:
    path = tmp_path / "external.json"
    path.write_text(json.dumps({"observations": [
        {"observation_id": "safe", "source": "financialjuice", "public_safe": True},
        {"observation_id": "private", "source": "financialjuice", "public_safe": True, "body": "raw"},
        {"observation_id": "unknown", "source": "other", "public_safe": True},
    ]}), encoding="utf-8")
    accepted, rejected = load_external_observations(path)
    assert [row["observation_id"] for row in accepted] == ["safe"]
    assert rejected == 2


def test_compound_records_require_integrity_fields(tmp_path: Path) -> None:
    path = tmp_path / "compound.json"
    path.write_text(json.dumps({
        "parse_status": "parsed", "content_origin": "financialjuice", "public_safe": True,
        "item_count": 1, "items": [{"item_id": "item-1", "content_hash": "a" * 64,
        "event_cluster_key": "cluster-1", "candidate_event_type": "energy",
        "original_headline": "Oil supply risk"}],
    }), encoding="utf-8")
    accepted, rejected = load_external_observations(path)
    assert [row["observation_id"] for row in accepted] == ["item-1"]
    assert rejected == 0


def test_source_health_merge_counts_runtime_gap() -> None:
    row = external_source_health(path=Path("missing.json"), accepted=[], rejected=0, checked_at=datetime.now(UTC))
    merged = merge_external_source_health({"status": "healthy", "sources": []}, row)
    assert merged["missing_source_count"] == 1
    assert merged["runtime_failure_count"] == 1
