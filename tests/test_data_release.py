from pathlib import Path

import pytest

from src import data_release
from src.data_release import DataReleaseError, _safe_path, publish


def test_all_data_release_publishers_share_one_concurrency_group():
    """Prevent concurrent workflows from racing the immutable data branch."""
    root = Path(__file__).resolve().parents[1]
    workflows = sorted((root / ".github" / "workflows").glob("*.yml"))
    publishers = [
        path for path in workflows
        if "python -m src.data_release --publish" in path.read_text(encoding="utf-8")
    ]
    assert publishers
    for path in publishers:
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        group = None
        for index, line in enumerate(lines):
            if line.strip() != "concurrency:":
                continue
            for candidate in lines[index + 1:index + 12]:
                stripped = candidate.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if stripped.startswith("group:"):
                    group = stripped.split(":", 1)[1].strip().split("#", 1)[0].strip()
                break
            if group is not None:
                break
        assert group is not None, f"{path.name} must define a concurrency group"
        assert group.startswith("main-data-writer-"), f"{path.name} must use the shared writer queue"
        assert "python -m src.writer_queue" in text, f"{path.name} must wait for older writers"
        assert "--expected-base-sha" in text, f"{path.name} must fence publication against its prepared base"


def test_data_release_rejects_paths_outside_public_data():
    with pytest.raises(DataReleaseError):
        _safe_path("src/secrets.json")
    with pytest.raises(DataReleaseError):
        _safe_path("site/data/../secret.json")


def test_fetch_branch_updates_remote_tracking_ref(monkeypatch):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return data_release.subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(data_release, "_run", fake_run)

    assert data_release._fetch_branch("data-release") is True
    assert calls == [
        (
            (
                "fetch",
                "origin",
                "refs/heads/data-release:refs/remotes/origin/data-release",
            ),
            {"check": False},
        )
    ]


def test_push_retry_treats_candidate_already_on_remote_as_success(monkeypatch):
    base = "a" * 40
    candidate = "b" * 40
    remote_tip = base
    pushes = []

    def fake_run(*args, **kwargs):
        nonlocal remote_tip
        if args[:2] == ("rev-parse", "refs/remotes/origin/data-release"):
            return data_release.subprocess.CompletedProcess(args, 0, remote_tip + "\n", "")
        if args[:1] == ("push",):
            pushes.append(args)
            return data_release.subprocess.CompletedProcess(args, 1, "", "remote: Internal Server Error")
        raise AssertionError(args)

    monkeypatch.setattr(data_release, "_run", fake_run)
    monkeypatch.setattr(data_release, "time", type("Clock", (), {"sleep": staticmethod(lambda _seconds: None)}))

    def fetch(_branch):
        nonlocal remote_tip
        remote_tip = candidate
        return True

    monkeypatch.setattr(data_release, "_fetch_branch", fetch)
    recovered = data_release._push_commit_with_retry(
        branch="data-release", commit=candidate, expected_parent=base,
    )

    assert recovered is True
    assert len(pushes) == 1


def test_push_retry_retries_only_when_prepared_base_is_still_current(monkeypatch):
    base = "a" * 40
    candidate = "b" * 40
    remote_tip = base
    pushes = []

    def fake_run(*args, **kwargs):
        if args[:2] == ("rev-parse", "refs/remotes/origin/data-release"):
            return data_release.subprocess.CompletedProcess(args, 0, remote_tip + "\n", "")
        if args[:1] == ("push",):
            pushes.append(args)
            if len(pushes) == 1:
                return data_release.subprocess.CompletedProcess(args, 1, "", "HTTP 503")
            return data_release.subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError(args)

    monkeypatch.setattr(data_release, "_run", fake_run)
    monkeypatch.setattr(data_release, "time", type("Clock", (), {"sleep": staticmethod(lambda _seconds: None)}))
    monkeypatch.setattr(data_release, "_fetch_branch", lambda _branch: True)

    recovered = data_release._push_commit_with_retry(
        branch="data-release", commit=candidate, expected_parent=base,
    )

    assert recovered is True
    assert len(pushes) == 2
    assert all("--force" not in call for call in pushes)


def test_push_retry_stops_when_remote_base_changes(monkeypatch):
    base = "a" * 40
    candidate = "b" * 40
    remote_tip = base
    pushes = []

    def fake_run(*args, **kwargs):
        if args[:2] == ("rev-parse", "refs/remotes/origin/data-release"):
            return data_release.subprocess.CompletedProcess(args, 0, remote_tip + "\n", "")
        if args[:1] == ("push",):
            pushes.append(args)
            return data_release.subprocess.CompletedProcess(args, 1, "", "HTTP 500")
        raise AssertionError(args)

    def fetch(_branch):
        nonlocal remote_tip
        remote_tip = "c" * 40
        return True

    monkeypatch.setattr(data_release, "_run", fake_run)
    monkeypatch.setattr(data_release, "time", type("Clock", (), {"sleep": staticmethod(lambda _seconds: None)}))
    monkeypatch.setattr(data_release, "_fetch_branch", fetch)

    with pytest.raises(DataReleaseError, match="data_release_push_remote_ref_changed"):
        data_release._push_commit_with_retry(
            branch="data-release", commit=candidate, expected_parent=base,
        )
    assert len(pushes) == 1


def test_push_retry_does_not_retry_permission_or_non_server_failures(monkeypatch):
    base = "a" * 40
    candidate = "b" * 40
    pushes = []

    def fake_run(*args, **kwargs):
        if args[:2] == ("rev-parse", "refs/remotes/origin/data-release"):
            return data_release.subprocess.CompletedProcess(args, 0, base + "\n", "")
        if args[:1] == ("push",):
            pushes.append(args)
            return data_release.subprocess.CompletedProcess(args, 1, "", "HTTP 403: denied")
        raise AssertionError(args)

    monkeypatch.setattr(data_release, "_run", fake_run)
    with pytest.raises(DataReleaseError, match="data_release_push_rejected"):
        data_release._push_commit_with_retry(
            branch="data-release", commit=candidate, expected_parent=base,
        )
    assert len(pushes) == 1


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


def test_publish_rejects_stale_expected_base_before_creating_commit(tmp_path, monkeypatch):
    data_dir = tmp_path / "site" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "market.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(data_release, "_fetch_branch", lambda _branch: True)
    monkeypatch.setattr(
        data_release, "_run",
        lambda *args, **_kwargs: data_release.subprocess.CompletedProcess(args, 0, "b" * 40 + "\n", ""),
    )
    monkeypatch.setattr(
        data_release.subprocess, "run",
        lambda *_args, **_kwargs: pytest.fail("stale prepared release must stop before writing"),
    )

    with pytest.raises(DataReleaseError, match="expected_base_sha_mismatch"):
        publish(
            root=tmp_path, includes=["site/data"], expected_base_sha="a" * 40,
        )


def test_publish_rejects_unavailable_remote_base_when_expected(tmp_path, monkeypatch):
    data_dir = tmp_path / "site" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "market.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(data_release, "_fetch_branch", lambda _branch: False)
    monkeypatch.setattr(
        data_release, "_run",
        lambda *args, **_kwargs: data_release.subprocess.CompletedProcess(args, 0, "a" * 40 + "\n", ""),
    )
    with pytest.raises(DataReleaseError, match="expected_base_sha_remote_unavailable"):
        publish(root=tmp_path, includes=["site/data"], expected_base_sha="a" * 40)


def test_publish_rejects_explicitly_empty_expected_base(tmp_path, monkeypatch):
    data_dir = tmp_path / "site" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "market.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(data_release, "_fetch_branch", lambda _branch: True)
    monkeypatch.setattr(
        data_release, "_run",
        lambda *args, **_kwargs: data_release.subprocess.CompletedProcess(args, 0, "a" * 40 + "\n", ""),
    )
    with pytest.raises(DataReleaseError, match="expected_base_sha_invalid"):
        publish(root=tmp_path, includes=["site/data"], expected_base_sha="")


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


def test_publish_stages_on_existing_release_tree(tmp_path, monkeypatch):
    """A partial publisher must preserve caches written by another workflow."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "market.json").write_text("{}", encoding="utf-8")
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

    def fake_git_run(*args, **kwargs):
        if args[:2] == ("rev-parse", "refs/remotes/origin/data-release"):
            return data_release.subprocess.CompletedProcess(args, 0, "parent123\n", "")
        if args[:2] == ("rev-parse", "parent123^{tree}"):
            return data_release.subprocess.CompletedProcess(args, 0, "oldtree\n", "")
        return data_release.subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(data_release, "_run", fake_git_run)
    result = publish(root=tmp_path, includes=["data/market.json"])

    assert result["published"] is True
    assert ["git", "read-tree", "parent123"] in calls


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


def test_restore_discovers_remote_alert_archive_when_local_checkout_is_empty(tmp_path, monkeypatch):
    site_data = tmp_path / "site" / "data"
    site_data.mkdir(parents=True)
    (site_data / "market.json").write_text("{}", encoding="utf-8")

    def fake_run(*args, check=True):
        if args[:2] == ("fetch", "origin"):
            return data_release.subprocess.CompletedProcess(args, 0, "", "")
        if args[0] == "ls-tree" and args[-1] == "site/data/alerts":
            return data_release.subprocess.CompletedProcess(args, 0, "site/data/alerts/old-alert.json\n", "")
        if args[0] == "ls-tree":
            return data_release.subprocess.CompletedProcess(args, 0, "site/data/market.json\nsite/data/alerts/old-alert.json\n", "")
        if args[0] == "checkout":
            return data_release.subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError(args)

    monkeypatch.setattr(data_release, "_run", fake_run)
    result = data_release.restore(root=tmp_path, includes=["site/data"])

    assert result["restored"] is True
    assert "site/data/alerts/old-alert.json" in result["files"]


def test_restore_clears_public_artifacts_missing_from_remote_release(tmp_path, monkeypatch):
    site_data = tmp_path / "site" / "data"
    site_data.mkdir(parents=True)
    (site_data / "market.json").write_text("new", encoding="utf-8")
    (site_data / "legacy-event.json").write_text("old", encoding="utf-8")

    def fake_run(*args, check=True):
        if args[:2] == ("fetch", "origin"):
            return data_release.subprocess.CompletedProcess(args, 0, "", "")
        if args[0] == "ls-tree":
            return data_release.subprocess.CompletedProcess(args, 0, "site/data/market.json\n", "")
        if args[0] == "checkout":
            return data_release.subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError(args)

    monkeypatch.setattr(data_release, "_run", fake_run)
    result = data_release.restore(root=tmp_path, includes=["site/data"])

    assert result["removed_local"] == ["site/data/legacy-event.json"]
    assert not (site_data / "legacy-event.json").exists()
    assert (site_data / "market.json").exists()


def test_restore_of_one_public_file_does_not_clear_other_files(tmp_path, monkeypatch):
    site_data = tmp_path / "site" / "data"
    site_data.mkdir(parents=True)
    (site_data / "market.json").write_text("new", encoding="utf-8")
    (site_data / "legacy-event.json").write_text("old", encoding="utf-8")

    def fake_run(*args, check=True):
        if args[:2] == ("fetch", "origin"):
            return data_release.subprocess.CompletedProcess(args, 0, "", "")
        if args[0] == "ls-tree":
            return data_release.subprocess.CompletedProcess(args, 0, "site/data/market.json\n", "")
        if args[0] == "checkout":
            return data_release.subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError(args)

    monkeypatch.setattr(data_release, "_run", fake_run)
    result = data_release.restore(root=tmp_path, includes=["site/data/market.json"])

    assert result["removed_local"] == []
    assert (site_data / "legacy-event.json").exists()


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


def test_restore_dry_run_never_checks_out_files(tmp_path, monkeypatch):
    data_dir = tmp_path / "site" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "market.json").write_text("{}", encoding="utf-8")
    calls = []

    def fake_run(*args, check=True):
        calls.append(args)
        if args[:2] == ("fetch", "origin"):
            return data_release.subprocess.CompletedProcess(args, 0, "", "")
        if args[0] == "ls-tree":
            return data_release.subprocess.CompletedProcess(args, 0, "site/data/market.json\n", "")
        raise AssertionError(args)

    monkeypatch.setattr(data_release, "_run", fake_run)
    result = data_release.restore(root=tmp_path, dry_run=True)
    assert result == {
        "restored": False,
        "dry_run": True,
        "branch": "data-release",
        "planned_files": ["site/data/market.json"],
        "missing_remote": [],
    }
    assert not any(args and args[0] == "checkout" for args in calls)
