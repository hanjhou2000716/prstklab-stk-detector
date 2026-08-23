import json
from pathlib import Path

import pytest

from src.creator_provider_registry import (
    creator_ids,
    editorial_creator_ids,
    get_creator_provider,
    is_known_creator,
    load_creator_registry,
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
    with pytest.raises(ValueError, match="unsupported creator source type"):
        load_creator_registry(path)
