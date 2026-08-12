from src.creator_release import build_creator_release, validate_creator_release


def _parent():
    return {"release_id": "release-1", "market_snapshot_id": "market-1", "event_snapshot_id": "event-1"}


def test_creator_release_is_lineage_bound_and_hash_addressed():
    artifact = build_creator_release([{"episode_key": "e1", "public_safe": True, "verification_state": "unverified"}], parent_manifest=_parent())
    assert artifact["status"] == "ready"
    assert artifact["parent_release_id"] == "release-1"
    assert len(artifact["artifact_hash"]) == 64


def test_invalid_creator_artifact_is_unavailable_not_parent_failure():
    artifact = build_creator_release([{"episode_key": "e1", "raw_body": "secret", "public_safe": True, "verification_state": "unverified"}], parent_manifest=_parent())
    assert artifact["status"] == "unavailable"
    assert "creator insight contains private raw fields" in artifact["validation_errors"]


def test_parent_mismatch_is_explicit():
    errors = validate_creator_release({"schema_version": "1.0", "public_safe": True, "parent_release_id": "wrong", "market_snapshot_id": "market-1", "event_snapshot_id": "event-1", "insights": []}, parent_manifest=_parent())
    assert "creator artifact parent release mismatch" in errors
