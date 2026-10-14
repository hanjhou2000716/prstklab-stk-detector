import json
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

    def request(_api, _repo, _token, method, path, payload=None, *, response_headers=None, deadline_monotonic=None):
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

    opened_issue["body"] += f"\nNext reminder at: {(now + timedelta(minutes=30)).isoformat()}"

    def request(_api, _repo, _token, method, path, payload=None, *, response_headers=None, deadline_monotonic=None):
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

    def request(_api, _repo, _token, method, path, payload=None, *, response_headers=None, deadline_monotonic=None):
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
    patch = next(payload for method, path, payload in calls if method == "PATCH" and path == "issues/77")
    assert patch["state"] == "closed"
    assert patch["state_reason"] == "completed"
    assert "Recovered at:" in patch["body"]


def test_incomplete_job_pagination_fails_closed(monkeypatch):
    now = datetime(2026, 10, 13, 5, 0, tzinfo=UTC)
    run = _run(1234, now - timedelta(minutes=16))

    def request(_api, _repo, _token, method, path, payload=None, *, response_headers=None, deadline_monotonic=None):
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


def test_run_pagination_reads_linked_pages_with_ten_records(monkeypatch):
    calls: list[str] = []
    rows = [_run(index + 1, datetime(2026, 10, 13, tzinfo=UTC)) for index in range(12)]

    def request(_api, _repo, _token, method, path, payload=None, *, response_headers=None, deadline_monotonic=None):
        calls.append(path)
        page = int(path.rsplit("page=", 1)[1])
        start = (page - 1) * 10
        page_rows = rows[start:start + 10]
        if response_headers is not None and page == 1:
            response_headers["link"] = (
                '<https://api.github.com/repos/owner/repo/actions/workflows/'
                'official-event-monitor.yml/runs?per_page=10&branch=main&page=2>; rel="next"'
            )
        return {"total_count": len(rows), "workflow_runs": page_rows}

    monkeypatch.setattr(monitor_liveness, "_request_json", request)
    result = monitor_liveness._get_runs(
        "https://api.github.com", "owner/repo", "test-token",
        deadline_monotonic=monitor_liveness.time.monotonic() + 90,
    )

    assert len(result) == 12
    assert len(calls) == 2
    assert "per_page=10" in calls[0]


def test_run_pagination_rejects_cross_host_link():
    with pytest.raises(monitor_liveness.LivenessAuditError, match="pagination_identity_invalid"):
        monitor_liveness._next_link(
            '<https://attacker.example/repos/owner/repo/actions/workflows/official-event-monitor.yml/runs?per_page=10&page=2>; rel="next"',
            api_url="https://api.github.com",
            expected_path="/repos/owner/repo/actions/workflows/official-event-monitor.yml/runs",
            expected_page=2,
        )


def test_existing_incident_is_reminded_after_thirty_minutes(monkeypatch):
    now = datetime(2026, 10, 13, 6, 0, tzinfo=UTC)
    run = _run(5678, now - timedelta(minutes=16))
    issue = {
        "number": 77,
        "title": f"{monitor_liveness.ISSUE_TITLE_PREFIX} / main",
        "body": (
            f"{monitor_liveness.INCIDENT_MARKER}{monitor_liveness.INCIDENT_KEY}\n"
            f"Next reminder at: {(now - timedelta(seconds=1)).isoformat()}"
        ),
    }
    updates = []

    def request(_api, _repo, _token, method, path, payload=None, *, response_headers=None, deadline_monotonic=None):
        if path.startswith("actions/workflows/"):
            return {"workflow_runs": [run]}
        if path.startswith("actions/runs/5678/jobs?"):
            return {"total_count": 1, "jobs": [{"name": "monitor-send-deploy", "steps": []}]}
        if path.startswith("issues?"):
            return [issue]
        if method == "PATCH" and path == "issues/77":
            updates.append(payload)
            return {"number": 77}
        raise AssertionError((method, path, payload))

    monkeypatch.setattr(monitor_liveness, "_request_json", request)
    result = monitor_liveness.audit_liveness(
        api_url="https://api.github.com", repository="owner/repo", token="test-token", now=now,
    )

    assert result["incident_active"] is True
    assert result["reminder_sent"] is True
    assert len(updates) == 1
    assert f"Next reminder at: {(now + timedelta(minutes=30)).isoformat()}" in updates[0]["body"]


def test_liveness_audit_error_is_deduplicated_in_issue_without_failing_the_workflow(monkeypatch, tmp_path, capsys):
    issue_path = tmp_path / "liveness.json"
    calls: list[tuple[str, str, dict[str, object] | None]] = []
    monkeypatch.setenv("GITHUB_API_URL", "https://api.github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "private-test-token")
    monkeypatch.setenv("MONITOR_LIVENESS_RESULT_PATH", str(issue_path))
    monkeypatch.setattr(
        monitor_liveness, "audit_liveness",
        lambda **_kwargs: (_ for _ in ()).throw(monitor_liveness.LivenessAuditError("monitor_liveness_response_too_large")),
    )

    def request(_api, _repo, _token, method, path, payload=None, *, response_headers=None, deadline_monotonic=None):
        calls.append((method, path, payload))
        if path.startswith("issues?"):
            return []
        if method == "POST" and path == "issues":
            return {"number": 91, "title": f"{monitor_liveness.AUDIT_ISSUE_TITLE_PREFIX} / main"}
        raise AssertionError((method, path, payload))

    monkeypatch.setattr(monitor_liveness, "_request_json", request)

    assert monitor_liveness.main() == 0
    result = json.loads(issue_path.read_text(encoding="utf-8"))
    assert result["status"] == "degraded"
    assert result["incident_active"] is True
    assert result["incident_opened"] is True
    assert result["reason"] == "monitor_liveness_response_too_large"
    assert calls[-1][0:2] == ("POST", "issues")
    assert "private-test-token" not in capsys.readouterr().out


def test_repeated_liveness_audit_error_respects_thirty_minute_reminder(monkeypatch, tmp_path):
    issue_path = tmp_path / "liveness.json"
    later = datetime.now(UTC) + timedelta(minutes=20)
    issue = {
        "number": 91,
        "title": f"{monitor_liveness.AUDIT_ISSUE_TITLE_PREFIX} / main",
        "body": (
            f"{monitor_liveness.AUDIT_INCIDENT_MARKER}official-monitor-audit:monitor_liveness_response_too_large\n"
            f"Next reminder at: {later.isoformat()}"
        ),
    }
    calls: list[tuple[str, str]] = []
    monkeypatch.setenv("GITHUB_API_URL", "https://api.github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("MONITOR_LIVENESS_RESULT_PATH", str(issue_path))
    monkeypatch.setattr(
        monitor_liveness, "audit_liveness",
        lambda **_kwargs: (_ for _ in ()).throw(monitor_liveness.LivenessAuditError("monitor_liveness_response_too_large")),
    )

    def request(_api, _repo, _token, method, path, payload=None, *, response_headers=None, deadline_monotonic=None):
        calls.append((method, path))
        if path.startswith("issues?"):
            return [issue]
        raise AssertionError((method, path, payload))

    monkeypatch.setattr(monitor_liveness, "_request_json", request)

    assert monitor_liveness.main() == 0
    result = json.loads(issue_path.read_text(encoding="utf-8"))
    assert result["incident_active"] is True
    assert result["incident_opened"] is False
    assert result["reminder_sent"] is False
    assert len(calls) == 1
    assert calls[0][0] == "GET"
    assert calls[0][1].startswith("issues?")
