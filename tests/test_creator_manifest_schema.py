import json
from pathlib import Path


def test_release_manifest_schema_declares_optional_creator_contract():
    schema = json.loads(Path("schemas/release-manifest.schema.json").read_text(encoding="utf-8"))
    properties = schema["properties"]
    assert properties["creator_status"]["enum"] == ["ready", "unavailable", "not_available"]
    assert "creator_artifact_hash" in properties
