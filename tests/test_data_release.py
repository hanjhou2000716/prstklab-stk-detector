import pytest

from src import data_release
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


def test_publish_force_adds_ignored_release_artifacts(tmp_path, monkeypatch):
    """Ignored data files must still be staged into the isolated release index."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "snapshot.json").write_text("{}", encoding="utf-8")
    calls = []

    monkeypatch.setattr(data_release, "_fetch_branch", lambda branch: True)

    def fake_run(*args, **kwargs):
        command = args[0]
        calls.append(command)
        if command[:2] == ["git", "write-tree"]:
            return data_release.subprocess.CompletedProcess(command, 0, "tree123\n", "")
        if command[:2] == ["git", "commit-tree"]:
            return data_release.subprocess.CompletedProcess(command, 0, "commit123\n", "")
        return data_release.subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(data_release.subprocess, "run", fake_run)
    monkeypatch.setattr(
        data_release, "_run",
        lambda *args, **kwargs: data_release.subprocess.CompletedProcess(args, 0, "", ""),
    )

    result = publish(root=tmp_path, includes=["data/snapshot.json"])
    assert result["published"] is True
    assert ["git", "add", "-f", "--", "data/snapshot.json"] in calls


def test_restore_skips_cache_paths_missing_from_remote_branch(tmp_path, monkeypatch):
    site_data = tmp_path / "site" / "data"
    site_data.mkdir(parents=True)
    (site_data / "market.json").write_text("{}", encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "sec-companyfacts-cache.json").write_text("{}", encoding="utf-8")
    calls = []

    def fake_run(*args, check=True):
        calls.append(args)
        if args[:2] == ("fetch", "origin"):
            return data_release.subprocess.CompletedProcess(args, 0, "", "")
        if args[0] == "ls-tree":
            return data_release.subprocess.CompletedProcess(args, 0, "site/data/market.json\n", "")
        if args[0] == "checkout":
            return data_release.subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError(args)

    monkeypatch.setattr(data_release, "_run", fake_run)
    result = data_release.restore(
        root=tmp_path,
        includes=["site/data", "data/sec-companyfacts-cache.json"],
    )

    assert result["restored"] is True
    assert result["files"] == ["site/data/market.json"]
    assert result["missing_remote"] == ["data/sec-companyfacts-cache.json"]
    checkout = next(args for args in calls if args[0] == "checkout")
    assert "data/sec-companyfacts-cache.json" not in checkout


def test_restore_reports_empty_remote_release_without_pathspec_failure(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "taiwan-mops-pristine-history.json").write_text("{}", encoding="utf-8")

    def fake_run(*args, check=True):
        if args[:2] == ("fetch", "origin"):
            return data_release.subprocess.CompletedProcess(args, 0, "", "")
        if args[0] == "ls-tree":
            return data_release.subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError(args)

    monkeypatch.setattr(data_release, "_run", fake_run)
    result = data_release.restore(root=tmp_path, includes=["data/taiwan-mops-pristine-history.json"])

    assert result == {
        "restored": False,
        "branch": "data-release",
        "reason": "no_remote_paths",
        "missing_remote": ["data/taiwan-mops-pristine-history.json"],
    }
