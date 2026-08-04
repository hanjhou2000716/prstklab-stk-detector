from pathlib import Path

import pytest

from src.data_release import DataReleaseError, _safe_path, publish


def test_data_release_rejects_paths_outside_public_data():
    with pytest.raises(DataReleaseError):
        _safe_path("src/secrets.json")
    with pytest.raises(DataReleaseError):
        _safe_path("site/data/../secret.json")


def test_publish_dry_run_expands_only_existing_data(tmp_path):
    data = tmp_path / "site" / "data"
    data.mkdir(parents=True)
    (data / "market.json").write_text("{}", encoding="utf-8")
    result = publish(root=tmp_path, includes=["site/data"], dry_run=True)
    assert result["dry_run"] is True
    assert result["branch"] == "data-release"
    assert result["files"] == ["site/data/market.json"]


def test_publish_rejects_empty_release(tmp_path):
    with pytest.raises(DataReleaseError, match="no data files"):
        publish(root=tmp_path, includes=["site/data"], dry_run=True)