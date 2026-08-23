from pathlib import Path

from src.pages_release import _validate


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
