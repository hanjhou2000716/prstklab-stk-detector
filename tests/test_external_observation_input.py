import json
from datetime import UTC, datetime
from pathlib import Path

from src.external_observation_input import (
    external_source_health,
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
