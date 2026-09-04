import json
from pathlib import Path

import pytest

from src.creator_provider_registry import (
    creator_ids,
    editorial_creator_ids,
    get_creator_provider,
    is_known_creator,
    load_creator_registry,
    retired_creator_ids,
)


def test_registry_contains_ordered_editorial_providers():
    assert creator_ids() == ("haojiao", "jenny", "gooaye")
    assert editorial_creator_ids() == creator_ids()
    assert get_creator_provider("JENNY").display_name == "財女珍妮"
    assert get_creator_provider("haojiao").morning_required is True
    assert get_creator_provider("jenny").morning_required is True
    assert get_creator_provider("gooaye").morning_required is False
    assert is_known_creator("jenny")
    assert not is_known_creator("unknown")


def test_all_creator_providers_are_retired_without_erasing_registry_history():
    assert creator_ids(enabled_only=True) == ()
    assert retired_creator_ids() == ("haojiao", "jenny", "gooaye")


def test_registry_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "providers.json"
    payload = json.loads(Path("config/creator_providers.json").read_text(encoding="utf-8"))
    payload["providers"].append(dict(payload["providers"][0]))
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate creator provider"):
        load_creator_registry(path)


def test_registry_rejects_unknown_source_type(tmp_path):
    path = tmp_path / "providers.json"
    payload = json.loads(Path("config/creator_providers.json").read_text(encoding="utf-8"))
    payload["providers"][0]["source_type"] = "official"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="registry schema invalid"):
        load_creator_registry(path)


def test_registry_rejects_schema_drift_before_semantic_normalization(tmp_path):
    path = tmp_path / "providers.json"
    payload = json.loads(Path("config/creator_providers.json").read_text(encoding="utf-8"))
    payload["providers"][0]["unexpected_private_field"] = "must not enter the contract"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="registry schema invalid"):
        load_creator_registry(path)


def test_canonical_registry_validates_against_formal_schema():
    import jsonschema

    registry = json.loads(Path("config/creator_providers.json").read_text(encoding="utf-8"))
    schema = json.loads(Path("schemas/creator-providers.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(registry)
