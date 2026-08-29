import hashlib
import json
from pathlib import Path

from src.pages_release import PagesReleaseError, _validate, restore_latest_valid, restore_public_release


def test_validate_requires_ready_manifest_and_zero_exit(monkeypatch):
    class Result:
        returncode = 0
        stdout = '{"status":"ready","release_id":"release-good"}\n'
        stderr = ""

    monkeypatch.setattr("src.pages_release.subprocess.run", lambda *args, **kwargs: Result())
    ready, payload = _validate(Path("."), require_production_research=True)
    assert ready is True
    assert payload["release_id"] == "release-good"


def test_validate_rejects_invalid_manifest_even_with_zero_exit(monkeypatch):
    class Result:
        returncode = 0
        stdout = '{"status":"invalid","validation_errors":["stale"]}\n'
        stderr = ""

    monkeypatch.setattr("src.pages_release.subprocess.run", lambda *args, **kwargs: Result())
    ready, payload = _validate(Path("."), require_production_research=True)
    assert ready is False
    assert payload["status"] == "invalid"


def test_pages_workflow_preserves_previous_release_when_no_candidate_is_valid():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "deploy-pages.yml"
    ).read_text(encoding="utf-8")
    assert "python -m src.pages_release" in workflow
    assert "steps.release.outputs.publish == 'true'" in workflow
    assert "no_valid_production_release" in workflow


def test_restore_public_release_verifies_hashes_before_replacing_data(tmp_path, monkeypatch):
    manifest = {
        "status": "ready",
        "release_id": "release-last-good",
        "market_snapshot_id": "market-last-good",
        "artifact_paths": {"market.json": "data/market.json"},
    }
    body = b'{"snapshot_id":"market-last-good"}'
    manifest["artifact_hashes"] = {"market.json": hashlib.sha256(body).hexdigest()}

    class Response:
        def __init__(self, content):
            self.content = content

        def raise_for_status(self):
            return None

        def json(self):
            return json.loads(self.content.decode("utf-8"))

    def get(url, **_kwargs):
        return Response(json.dumps(manifest).encode() if url.endswith("release-manifest.json?pages_restore=1") else body)

    monkeypatch.setattr("src.pages_release.requests.get", get)
    monkeypatch.setattr("src.pages_release._validate", lambda *args, **kwargs: (True, {"status": "ready"}))
    (tmp_path / "site" / "data").mkdir(parents=True)
    (tmp_path / "site" / "data" / "old.json").write_text("old", encoding="utf-8")

    result = restore_public_release(root=tmp_path, public_url="https://example.test")

    assert result["release_id"] == "release-last-good"
    assert not (tmp_path / "site" / "data" / "old.json").exists()
    assert (tmp_path / "site" / "data" / "market.json").read_bytes() == body


def test_restore_latest_valid_preserves_public_release_when_data_branch_has_no_valid_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr("src.pages_release._commits", lambda *args, **kwargs: ["bad"])
    monkeypatch.setattr("src.pages_release._restore_archive", lambda *args, **kwargs: True)
    monkeypatch.setattr("src.pages_release._validate", lambda *args, **kwargs: (False, {"status": "invalid"}))
    preserved = {"release_id": "release-last-good", "snapshot_id": "market-last-good", "artifact_count": 7}
    monkeypatch.setattr("src.pages_release.restore_public_release", lambda **kwargs: preserved)

    result = restore_latest_valid(root=tmp_path, preserve_public_url="https://example.test")

    assert result["publish"] is True
    assert result["preserved_public"] is True
    assert result["release_id"] == "release-last-good"


def test_restore_latest_valid_remains_fail_closed_when_public_preservation_fails(tmp_path, monkeypatch):
    monkeypatch.setattr("src.pages_release._commits", lambda *args, **kwargs: ["bad"])
    monkeypatch.setattr("src.pages_release._restore_archive", lambda *args, **kwargs: True)
    monkeypatch.setattr("src.pages_release._validate", lambda *args, **kwargs: (False, {"status": "invalid"}))
    monkeypatch.setattr(
        "src.pages_release.restore_public_release",
        lambda **kwargs: (_ for _ in ()).throw(PagesReleaseError("unexpected")),
    )

    result = restore_latest_valid(root=tmp_path, preserve_public_url="https://example.test")

    assert result["publish"] is False
