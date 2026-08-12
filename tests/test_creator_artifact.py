from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.creator_artifact import build_creator_artifact, validate_creator_artifact


def _insight(index: int, **extra):
    return {
        "creator_id": "gooaye",
        "creator_name": "股癌",
        "content_origin": "gooaye",
        "episode_key": f"gooaye:ep-{index}",
        "episode_title": f"Episode {index}",
        "published_at": f"2026-08-{index + 1:02d}T00:00:00Z",
        "key_takeaways": ["public point"],
        "verification_state": "unverified",
        "public_safe": True,
        **extra,
    }


def test_public_artifact_limits_retention_and_compacts_history() -> None:
    artifact = build_creator_artifact(
        [_insight(index) for index in range(12)],
        parent_release_id="release-1",
        market_snapshot_id="market-1",
        research_snapshot_id="research-1",
        event_snapshot_id="event-1",
    )
    assert artifact["status"] == "ready"
    episodes = artifact["creators"]["gooaye"]["episodes"]
    assert len(episodes) == 10
    assert episodes[0]["display_mode"] == "full"
    assert all(item["display_mode"] == "compact" for item in episodes[1:])
    assert artifact["retention"]["public_per_creator"] == 10


def test_private_fields_and_duplicate_episode_fail_closed() -> None:
    artifact = build_creator_artifact([_insight(1, raw_body="secret"), _insight(2), _insight(2)])
    assert artifact["status"] == "ready"
    assert artifact["invalid_records"] == ["0:private_field", "2:duplicate_or_missing_episode"]
    artifact["creators"]["gooaye"]["episodes"][0]["raw_body"] = "secret"
    assert "gooaye:private_episode_field" in validate_creator_artifact(artifact)


def test_public_artifact_schema_and_no_image_url() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((Path(__file__).parents[1] / "schemas" / "creator-insights.schema.json").read_text(encoding="utf-8"))
    artifact = build_creator_artifact([_insight(1, image_url="https://private.test/x.png")], snapshot_id="creator-snapshot-1")
    jsonschema.validate(artifact, schema)
    assert "image_url" not in artifact["creators"]["gooaye"]["episodes"][0]
