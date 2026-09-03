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


def test_validate_rejects_candidate_when_delivery_gate_reports_stale_research(tmp_path, monkeypatch):
    class Result:
        def __init__(self, returncode, stdout, stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    responses = iter(
        [
            Result(0, '{"status":"ready","release_id":"release-stale"}\n'),
            Result(
                1,
                "allowed=false\nrelease_id=release-stale\n"
                "errors=production release research is older than 24 hours\n",
            ),
        ]
    )
    monkeypatch.setattr("src.pages_release.subprocess.run", lambda *args, **kwargs: next(responses))

    ready, payload = _validate(tmp_path, require_production_research=True)

    assert ready is False
    assert payload["status"] == "invalid"
    assert payload["validation_errors"] == ["production release research is older than 24 hours"]


def test_pages_workflow_preserves_previous_release_when_no_candidate_is_valid():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "deploy-pages.yml"
    ).read_text(encoding="utf-8")
    assert "python -m src.pages_release" in workflow
    assert "steps.release.outputs.publish == 'true'" in workflow
    assert "no_valid_production_release" in workflow
    assert "steps.release.outputs.preserved_public" in workflow
    assert "python -m src.release_gate --manifest site/data/release-manifest.json" in workflow


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
    def validate_and_rebuild_manifest(root, **_kwargs):
        (Path(root) / "site" / "data" / "release-manifest.json").write_text(
            json.dumps({"status": "ready", "release_id": "release-derived"}), encoding="utf-8"
        )
        return True, {"status": "ready"}

    monkeypatch.setattr("src.pages_release._validate", validate_and_rebuild_manifest)
    (tmp_path / "site" / "data").mkdir(parents=True)
    (tmp_path / "site" / "data" / "old.json").write_text("old", encoding="utf-8")

    result = restore_public_release(root=tmp_path, public_url="https://example.test")

    assert result["release_id"] == "release-last-good"
    assert not (tmp_path / "site" / "data" / "old.json").exists()
    assert (tmp_path / "site" / "data" / "market.json").read_bytes() == body
    restored_manifest = json.loads(
        (tmp_path / "site" / "data" / "release-manifest.json").read_text(encoding="utf-8")
    )
    assert restored_manifest["release_id"] == "release-last-good"


def test_restore_public_release_restores_alert_bytes_after_builder_validation(tmp_path, monkeypatch):
    alert_path = "data/alerts/alert-release-last-good.json"
    market_path = "data/market.json"
    manifest = {
        "status": "ready",
        "release_id": "release-last-good",
        "market_snapshot_id": "market-last-good",
        "artifact_paths": {
            "market.json": market_path,
            "alerts/alert-release-last-good.json": alert_path,
        },
    }
    market_body = b'{"snapshot_id":"market-last-good"}'
    alert_body = b'{"release_id":"release-last-good","notification_id":"alert-1"}'
    manifest["artifact_hashes"] = {
        "market.json": hashlib.sha256(market_body).hexdigest(),
        "alerts/alert-release-last-good.json": hashlib.sha256(alert_body).hexdigest(),
    }

    class Response:
        def __init__(self, content):
            self.content = content

        def raise_for_status(self):
            return None

        def json(self):
            return json.loads(self.content.decode("utf-8"))

    def get(url, **_kwargs):
        if url.endswith("release-manifest.json?pages_restore=1"):
            return Response(json.dumps(manifest).encode())
        return Response(alert_body if url.endswith(alert_path) else market_body)

    monkeypatch.setattr("src.pages_release.requests.get", get)

    def validate_and_rebuild(root, **_kwargs):
        data_root = Path(root) / "site" / "data"
        (data_root / "market.json").write_bytes(b'{"snapshot_id":"derived"}')
        (data_root / "alerts" / "alert-release-derived.json").parent.mkdir(parents=True, exist_ok=True)
        (data_root / "alerts" / "alert-release-derived.json").write_bytes(
            b'{"release_id":"release-derived"}'
        )
        return True, {"status": "ready"}

    monkeypatch.setattr("src.pages_release._validate", validate_and_rebuild)

    result = restore_public_release(root=tmp_path, public_url="https://example.test")

    assert result["release_id"] == "release-last-good"
    assert (tmp_path / "site" / "data" / "market.json").read_bytes() == market_body
    assert (tmp_path / "site" / "data" / "alerts" / "alert-release-last-good.json").read_bytes() == alert_body
    assert not (tmp_path / "site" / "data" / "alerts" / "alert-release-derived.json").exists()


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


def test_restore_latest_valid_restores_immutable_manifest_identity_after_validation(tmp_path, monkeypatch):
    data_root = tmp_path / "site" / "data"
    data_root.mkdir(parents=True)
    immutable = {"status": "ready", "release_id": "release-immutable", "market_snapshot_id": "market-1"}
    manifest_path = data_root / "release-manifest.json"

    monkeypatch.setattr("src.pages_release._commits", lambda *args, **kwargs: ["good"])

    def restore_archive(*args, **kwargs):
        manifest_path.write_text(json.dumps(immutable), encoding="utf-8")
        return True

    monkeypatch.setattr("src.pages_release._restore_archive", restore_archive)

    def validate_and_rebuild(root, **kwargs):
        manifest_path.write_text(
            json.dumps({"status": "ready", "release_id": "release-derived"}),
            encoding="utf-8",
        )
        return True, {"status": "ready", "release_id": "release-derived"}

    monkeypatch.setattr("src.pages_release._validate", validate_and_rebuild)

    result = restore_latest_valid(root=tmp_path)

    assert result["publish"] is True
    assert result["release_id"] == "release-immutable"
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["release_id"] == "release-immutable"


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
