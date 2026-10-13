from datetime import UTC, datetime, timedelta

import pytest

from scripts import monitor_liveness


def _run(run_id: int, created_at: datetime, *, status: str = "queued") -> dict[str, object]:
    return {
        "id": run_id,
        "head_branch": "main",
        "created_at": created_at.isoformat(),
        "status": status,
    }


def test_unstarted_job_with_populated_started_at_opens_one_incident(monkeypatch):
    now = datetime(2026, 10, 13, 5, 0, tzinfo=UTC)
    run = _run(1234, now - timedelta(minutes=16))
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def request(_api, _repo, _token, method, path, payload=None):
        calls.append((method, path, payload))
        if path.startswith("actions/workflows/"):
            return {"workflow_runs": [run]}
        if path.startswith("actions/runs/1234/jobs?"):
            return {
                "total_count": 1,
                "jobs": [{
                    "name": "monitor-send-deploy",
                    "status": "queued",
                    "runner_id": None,
                    "started_at": now.isoformat(),
                    "steps": [],
                }],
            }
        if path.startswith("issues?"):
            return []
        if path == "issues":
            return {"number": 77, "title": f"{monitor_liveness.ISSUE_TITLE_PREFIX} / main"}
        raise AssertionError(path)

    monkeypatch.setattr(monitor_liveness, "_request_json", request)
    result = monitor_liveness.audit_liveness(
        api_url="https://api.github.com", repository="owner/repo", token="test-token", now=now,
    )

    assert result["status"] == "stalled"
    assert result["incident_opened"] is True
    assert result["stalled_run_id"] == 1234
    assert calls[-1][0:2] == ("POST", "issues")
    assert "test-token" not in repr(result)


def test_existing_incident_is_not_reopened_or_duplicated(monkeypatch):
    now = datetime(2026, 10, 13, 5, 0, tzinfo=UTC)
    run = _run(5678, now - timedelta(minutes=16))
    opened_issue = {
        "number": 77,
        "title": f"{monitor_liveness.ISSUE_TITLE_PREFIX} / main",
        "body": f"{monitor_liveness.INCIDENT_MARKER}{monitor_liveness.INCIDENT_KEY}",
    }
    called_paths: list[str] = []

    def request(_api, _repo, _token, method, path, payload=None):
        called_paths.append(path)
        if path.startswith("actions/workflows/"):
            return {"workflow_runs": [run]}
        if path.startswith("actions/runs/5678/jobs?"):
            return {"total_count": 1, "jobs": [{"name": "monitor-send-deploy", "steps": []}]}
        if path.startswith("issues?"):
            return [opened_issue]
        raise AssertionError((method, path, payload))

    monkeypatch.setattr(monitor_liveness, "_request_json", request)
    result = monitor_liveness.audit_liveness(
        api_url="https://api.github.com", repository="owner/repo", token="test-token", now=now,
    )

    assert result["incident_active"] is True
    assert result["incident_opened"] is False
    assert result["incident_key"] == monitor_liveness.INCIDENT_KEY
    assert result["stalled_run_id"] == 5678
    assert "issues" not in called_paths


def test_real_monitor_step_start_closes_open_incident(monkeypatch):
    now = datetime(2026, 10, 13, 5, 0, tzinfo=UTC)
    run = _run(5678, now - timedelta(minutes=3), status="in_progress")
    open_issue = {
        "number": 77,
        "title": f"{monitor_liveness.ISSUE_TITLE_PREFIX} / 1234",
        "body": f"{monitor_liveness.INCIDENT_MARKER}{monitor_liveness.INCIDENT_KEY}",
    }
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def request(_api, _repo, _token, method, path, payload=None):
        calls.append((method, path, payload))
        if path.startswith("actions/workflows/"):
            return {"workflow_runs": [run]}
        if path.startswith("actions/runs/5678/jobs?"):
            return {
                "total_count": 1,
                "jobs": [{
                    "name": "monitor-send-deploy",
                    "runner_id": 21,
                    "steps": [{"name": "Checkout", "started_at": (now - timedelta(minutes=2)).isoformat()}],
                }],
            }
        if path.startswith("issues?"):
            return [open_issue]
        if path == "issues/77":
            return {"number": 77, "state": "closed"}
        raise AssertionError((method, path))

    monkeypatch.setattr(monitor_liveness, "_request_json", request)
    result = monitor_liveness.audit_liveness(
        api_url="https://api.github.com", repository="owner/repo", token="test-token", now=now,
    )

    assert result["status"] == "healthy"
    assert result["closed_issue_numbers"] == [77]
    assert ("PATCH", "issues/77", {"state": "closed", "state_reason": "completed"}) in calls


def test_incomplete_job_pagination_fails_closed(monkeypatch):
    now = datetime(2026, 10, 13, 5, 0, tzinfo=UTC)
    run = _run(1234, now - timedelta(minutes=16))

    def request(_api, _repo, _token, method, path, payload=None):
        if path.startswith("actions/workflows/"):
            return {"workflow_runs": [run]}
        if path.startswith("actions/runs/1234/jobs?"):
            return {"total_count": 2, "jobs": [{"name": "monitor-send-deploy", "steps": []}]}
        raise AssertionError((method, path, payload))

    monkeypatch.setattr(monitor_liveness, "_request_json", request)
    with pytest.raises(monitor_liveness.LivenessAuditError, match="jobs_response_incomplete"):
        monitor_liveness.audit_liveness(
            api_url="https://api.github.com", repository="owner/repo", token="test-token", now=now,
        )
