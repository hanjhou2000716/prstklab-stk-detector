import hashlib
import json
from pathlib import Path

import pytest

from src.alert_archive import AlertArchiveError, immutable_alert_url
from src.pages_budget import PagesBudgetError, measure_pages_tree, stage_pages_payload


def test_pages_budget_counts_regular_files_and_nested_content(tmp_path: Path):
    (tmp_path / "index.html").write_bytes(b"index")
    nested = tmp_path / "assets"
    nested.mkdir()
    (nested / "app.js").write_bytes(b"bundle")

    assert measure_pages_tree(tmp_path) == (11, 2)


def test_pages_budget_stops_at_configured_size(tmp_path: Path):
    (tmp_path / "large.bin").write_bytes(b"0123456789")

    with pytest.raises(PagesBudgetError, match="byte budget"):
        measure_pages_tree(tmp_path, max_bytes=9)


def test_pages_budget_rejects_non_positive_limit(tmp_path: Path):
    (tmp_path / "index.html").write_text("ok", encoding="utf-8")

    with pytest.raises(PagesBudgetError):
        measure_pages_tree(tmp_path, max_bytes=0)


def test_pages_budget_includes_package_overhead_in_the_shared_limit(tmp_path: Path):
    (tmp_path / "tiny.json").write_text("{}", encoding="utf-8")

    with pytest.raises(PagesBudgetError, match="packaged artifact"):
        measure_pages_tree(tmp_path, max_bytes=3500)


def test_pages_staging_pins_cold_history_and_keeps_source_immutable(tmp_path: Path):
    source = tmp_path / "site"
    data = source / "data"
    alerts = data / "alerts"
    alerts.mkdir(parents=True)
    current_body = json.dumps({
        "notification_id": "current", "release_id": "release-current", "snapshot_id": "snapshot-current",
    }, separators=(",", ":")).encode()
    cold_body = json.dumps({
        "notification_id": "cold", "release_id": "release-old", "snapshot_id": "snapshot-old",
    }, separators=(",", ":")).encode()
    retained_body = json.dumps({
        "notification_id": "pending", "release_id": "release-pending", "snapshot_id": "snapshot-pending",
    }, separators=(",", ":")).encode()
    (alerts / "current.json").write_bytes(current_body)
    (alerts / "cold.json").write_bytes(cold_body)
    (alerts / "pending.json").write_bytes(retained_body)
    rows = [
        {"notification_id": "current", "release_id": "release-current", "path": "alerts/current.json", "sha256": hashlib.sha256(current_body).hexdigest()},
        {"notification_id": "cold", "release_id": "release-old", "path": "alerts/cold.json", "sha256": hashlib.sha256(cold_body).hexdigest()},
        {"notification_id": "pending", "release_id": "release-pending", "path": "alerts/pending.json", "sha256": hashlib.sha256(retained_body).hexdigest(), "pending_receipt": True},
    ]
    index = {"coverage": "complete", "alerts": rows}
    index_bytes = (json.dumps(index, ensure_ascii=False, indent=2) + "\n").encode()
    (data / "alert-index.json").write_bytes(index_bytes)
    bootstrap = {
        "alert_index": {"coverage": "current_release", "alerts": [rows[0]]},
        "deferred_artifacts": {
            "paths": {"alert-index.json": "data/alert-index.json", "alerts/cold.json": "data/alerts/cold.json", "alerts/current.json": "data/alerts/current.json"},
            "hashes": {"alert-index.json": hashlib.sha256(index_bytes).hexdigest(), "alerts/cold.json": rows[1]["sha256"], "alerts/current.json": rows[0]["sha256"]},
        },
    }
    (data / "bootstrap.json").write_text(json.dumps(bootstrap), encoding="utf-8")
    manifest = {
        "release_id": "release-current",
        "artifact_paths": {
            "alert-index.json": "data/alert-index.json",
            "bootstrap.json": "data/bootstrap.json",
            "alerts/current.json": "data/alerts/current.json",
            "alerts/cold.json": "data/alerts/cold.json",
            "alerts/pending.json": "data/alerts/pending.json",
        },
        "artifact_hashes": {
            "alert-index.json": hashlib.sha256(index_bytes).hexdigest(),
            "bootstrap.json": hashlib.sha256((data / "bootstrap.json").read_bytes()).hexdigest(),
            "alerts/current.json": rows[0]["sha256"],
            "alerts/cold.json": rows[1]["sha256"],
            "alerts/pending.json": rows[2]["sha256"],
        },
        "deferred_artifacts": ["alert-index.json", "bootstrap.json", "alerts/current.json", "alerts/cold.json", "alerts/pending.json"],
        "alert_index": {"coverage": "complete", "alerts": rows},
    }
    (data / "release-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    source_cold_before = (alerts / "cold.json").read_bytes()
    output = tmp_path / "pages"

    total, files, archived = stage_pages_payload(
        source,
        output,
        source_commit="a" * 40,
    )

    staged_index = json.loads((output / "data" / "alert-index.json").read_text(encoding="utf-8"))
    staged_manifest = json.loads((output / "data" / "release-manifest.json").read_text(encoding="utf-8"))
    staged_bootstrap = json.loads((output / "data" / "bootstrap.json").read_text(encoding="utf-8"))
    cold_row = next(row for row in staged_index["alerts"] if row["notification_id"] == "cold")
    current_row = next(row for row in staged_index["alerts"] if row["notification_id"] == "current")

    assert archived == 1
    assert total > 0 and files > 0
    assert cold_row["source_commit"] == "a" * 40
    assert "source_commit" not in current_row
    assert not (output / "data" / "alerts" / "cold.json").exists()
    assert (output / "data" / "alerts" / "pending.json").is_file()
    assert (source / "data" / "alerts" / "cold.json").read_bytes() == source_cold_before
    assert staged_manifest["alert_index"]["alerts"] == staged_index["alerts"]
    assert "alerts/cold.json" not in staged_manifest["deferred_artifacts"]
    assert "alerts/cold.json" not in staged_bootstrap["deferred_artifacts"]["paths"]
    assert staged_manifest["artifact_hashes"]["alert-index.json"] == hashlib.sha256((output / "data" / "alert-index.json").read_bytes()).hexdigest()
    assert staged_manifest["artifact_hashes"]["bootstrap.json"] == hashlib.sha256((output / "data" / "bootstrap.json").read_bytes()).hexdigest()


def test_pages_staging_rejects_index_hash_mismatch_without_touching_source(tmp_path: Path):
    source = tmp_path / "site"
    alerts = source / "data" / "alerts"
    alerts.mkdir(parents=True)
    (alerts / "old.json").write_text("{}", encoding="utf-8")
    (source / "data" / "alert-index.json").write_text(json.dumps({"alerts": [{
        "notification_id": "old", "release_id": "release-current", "path": "alerts/old.json", "sha256": "0" * 64,
    }]}), encoding="utf-8")
    (source / "data" / "release-manifest.json").write_text(json.dumps({"release_id": "release-current", "artifact_paths": {}, "artifact_hashes": {}}), encoding="utf-8")
    with pytest.raises(PagesBudgetError, match="hash does not match"):
        stage_pages_payload(source, tmp_path / "pages", source_commit="b" * 40)
    assert (alerts / "old.json").is_file()


def test_pages_staging_archives_formal_scale_cold_history_without_reading_it(tmp_path: Path):
    source = tmp_path / "site"
    alerts = source / "data" / "alerts"
    alerts.mkdir(parents=True)
    detail = alerts / "cold.json"
    with detail.open("wb") as handle:
        handle.truncate(1_048_950_717)
    row = {
        "notification_id": "old-notification",
        "release_id": "old-release",
        "path": "alerts/cold.json",
        # A syntactically valid digest is enough at packaging time; the fixed
        # source will be authenticated against it when a reader requests it.
        "sha256": "a" * 64,
    }
    (source / "data" / "alert-index.json").write_text(
        json.dumps({"coverage": "complete", "alerts": [row]}), encoding="utf-8"
    )
    (source / "data" / "release-manifest.json").write_text(
        json.dumps({"release_id": "current-release", "artifact_paths": {}, "artifact_hashes": {}}),
        encoding="utf-8",
    )

    output = tmp_path / "pages"
    _total, _files, archived = stage_pages_payload(
        source, output, source_commit="b" * 40, max_bytes=1024 * 1024,
    )

    staged = json.loads((output / "data" / "alert-index.json").read_text(encoding="utf-8"))
    assert archived == 1
    assert staged["alerts"][0]["source_commit"] == "b" * 40
    assert not (output / "data" / "alerts" / "cold.json").exists()
    assert detail.stat().st_size == 1_048_950_717


@pytest.mark.parametrize("commit,path", [("not-a-commit", "alerts/a.json"), ("a" * 40, "../secret.json")])
def test_immutable_alert_url_rejects_untrusted_source(commit: str, path: str):
    with pytest.raises(AlertArchiveError):
        immutable_alert_url(commit, path)
