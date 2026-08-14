"""P0-29 backup, rollback and disaster-recovery contract tests."""

import json
from pathlib import Path

import pytest

from src import data_release
from src.artifact_contract import validate_manifest
from src.release_manifest import build_release_manifest, verify_release_files, write_release_manifest


def _minimal_artifacts(root: Path) -> None:
    data = root / "site" / "data"
    data.mkdir(parents=True)
    (data / "market.json").write_text(
        json.dumps({"snapshot_id": "market-12345678", "generated_at": "2026-08-14T09:00:00+08:00", "indices": [], "quotes": [], "source_health": {}}),
        encoding="utf-8",
    )
    (data / "research-report.json").write_text(
        json.dumps({"schema_version": "2.0", "snapshot_id": "research-12345678", "generated_at": "2026-08-14T09:00:00+08:00", "sources": [], "candidates": [], "health": {}}),
        encoding="utf-8",
    )
    (data / "event-ledger.json").write_text(
        json.dumps({"schema_version": 1, "retention_days": 30, "events": {}}),
        encoding="utf-8",
    )


def test_dry_run_is_non_mutating_and_reports_release_files(tmp_path, monkeypatch):
    data = tmp_path / "site" / "data"
    data.mkdir(parents=True)
    (data / "market.json").write_text("{}", encoding="utf-8")
    before = (data / "market.json").read_bytes()
    monkeypatch.setattr(data_release, "_fetch_branch", lambda _branch: pytest.fail("dry-run must not fetch or push"))

    result = data_release.publish(root=tmp_path, includes=["site/data"], dry_run=True)

    assert result == {
        "published": False,
        "dry_run": True,
        "branch": "data-release",
        "files": ["site/data/market.json"],
    }
    assert (data / "market.json").read_bytes() == before


def test_restore_missing_branch_is_explicit_and_non_destructive(tmp_path, monkeypatch):
    target = tmp_path / "site" / "data" / "market.json"
    target.parent.mkdir(parents=True)
    target.write_text("old", encoding="utf-8")
    monkeypatch.setattr(data_release, "_fetch_branch", lambda _branch: False)

    result = data_release.restore(root=tmp_path, includes=["site/data"])

    assert result == {"restored": False, "branch": "data-release", "reason": "branch_missing"}
    assert target.read_text(encoding="utf-8") == "old"


def test_restore_drill_only_checks_paths_present_in_previous_release(tmp_path, monkeypatch):
    site_data = tmp_path / "site" / "data"
    site_data.mkdir(parents=True)
    (site_data / "market.json").write_text("new", encoding="utf-8")
    optional = tmp_path / "data" / "optional-cache.json"
    optional.parent.mkdir(parents=True)
    optional.write_text("cache", encoding="utf-8")
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
    result = data_release.restore(root=tmp_path, includes=["site/data", "data/optional-cache.json"])

    assert result["restored"] is True
    assert result["files"] == ["site/data/market.json"]
    assert result["missing_remote"] == ["data/optional-cache.json"]
    assert "data/optional-cache.json" not in next(args for args in calls if args[0] == "checkout")


def test_manifest_rollback_identity_and_tamper_check_are_fail_closed(tmp_path):
    _minimal_artifacts(tmp_path)
    manifest = build_release_manifest(root=tmp_path)
    write_release_manifest(manifest, tmp_path / "site" / "data" / "release-manifest.json")
    assert verify_release_files(manifest, root=tmp_path / "site") == []

    rolled_back = {**manifest, "status": "rolled_back", "rollback_release_id": "release-previous"}
    assert validate_manifest(rolled_back) == []
    assert validate_manifest({**manifest, "status": "rolled_back"})

    (tmp_path / "site" / "data" / "market.json").write_text("tampered", encoding="utf-8")
    assert any("hash mismatch" in error for error in verify_release_files(manifest, root=tmp_path / "site"))


def test_manifest_ready_release_cannot_carry_rollback_state():
    assert any(
        "ready manifest cannot declare rollback_release_id" in error
        for error in validate_manifest({"status": "ready", "rollback_release_id": "release-old"})
    )
