from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

import scripts.incident_reconciliation as incidents
from scripts.monitor_liveness import LivenessAuditError


def test_source_run_identity_is_bound_to_main_and_same_repository():
    event = incidents._source_event_from_run({
        "id": 123,
        "workflow_id": 319283753,
        "run_attempt": 2,
        "head_branch": "main",
        "head_sha": "a" * 40,
        "head_repository": {"full_name": "owner/repo"},
        "conclusion": "failure",
    }, workflow_name="Unified Taiwan-US research report", repository="owner/repo")

    assert event["run_id"] == "123"
    assert event["attempt"] == "2"
    assert event["conclusion"] == "failure"

    with pytest.raises(LivenessAuditError, match="source_run_identity_invalid"):
        incidents._source_event_from_run({
            "id": 123,
            "workflow_id": 319283753,
            "run_attempt": 1,
            "head_branch": "feature/untrusted",
            "head_sha": "a" * 40,
            "head_repository": {"full_name": "owner/repo"},
        }, workflow_name="Unified Taiwan-US research report", repository="owner/repo")


def test_source_runs_cursor_advances_past_active_run_and_persists_it(monkeypatch):
    workflow_id = 319283753
    path = ".github/workflows/unified-research-report.yml"
    now = datetime(2026, 10, 24, 4, 0, tzinfo=UTC)
    active = {
        "id": 10, "workflow_id": workflow_id, "created_at": "2026-10-24T03:50:00Z",
        "head_branch": "main", "head_sha": "a" * 40,
        "head_repository": {"full_name": "owner/repo"},
        "run_attempt": 1, "status": "in_progress",
    }
    completed = {
        "id": 11, "workflow_id": workflow_id, "created_at": "2026-10-24T03:55:00Z",
        "head_branch": "main", "head_sha": "b" * 40,
        "head_repository": {"full_name": "owner/repo"},
        "run_attempt": 1, "status": "completed", "conclusion": "failure",
    }

    def fake_request(_api, _repo, _token, _method, _url, *, response_headers=None, deadline_monotonic=None):
        return {"total_count": 2, "workflow_runs": [completed, active]}

    monkeypatch.setattr(incidents, "_request_json", fake_request)
    rows, cursor, held = incidents._workflow_runs_since(
        path=path, workflow_id=workflow_id, repository="owner/repo",
        api_url="https://api.github.com", token="token",
        cursor={"mode": "live", "created_at": "2026-10-24T03:45:00+00:00", "run_id": 0, "pending_runs": []},
        now=now, deadline=incidents.time.monotonic() + 10, repository_id=123,
    )

    assert [row["id"] for row in rows] == [11]
    assert cursor["created_at"] == "2026-10-24T03:55:00+00:00"
    assert cursor["run_id"] == 11
    assert cursor["pending_runs"] == [{
        "run_id": 10, "workflow_id": workflow_id,
        "created_at": "2026-10-24T03:50:00+00:00", "attempt": 1,
        "head_sha": "a" * 40,
    }]
    assert held is True


def test_official_monitor_backfill_accepts_github_numeric_repo_link(monkeypatch):
    workflow_id = 320209983
    path = ".github/workflows/official-event-monitor.yml"
    now = datetime(2026, 10, 21, 6, 30, tzinfo=UTC)
    created_filter = "2026-10-21T00:00:00Z..2026-10-21T05:59:59Z"
    rows = [
        {
            "id": 100 + index,
            "workflow_id": workflow_id,
            "created_at": f"2026-10-21T01:{index:02d}:00Z",
            "head_branch": "main",
            "head_sha": f"{index + 1:040x}",
            "head_repository": {"full_name": "owner/repo"},
            "run_attempt": 1,
            "status": "completed",
            "conclusion": "success",
        }
        for index in range(12)
    ]
    calls: list[str] = []

    def request(_api, _repo, _token, _method, request_path, *, response_headers=None, deadline_monotonic=None):
        calls.append(request_path)
        query = parse_qs(urlsplit(f"https://api.github.com/{request_path}").query)
        page = int(query["page"][0])
        if page == 1:
            assert query["branch"] == ["main"]
            assert query["created"] == [created_filter]
            assert query["per_page"] == [str(incidents.SOURCE_PAGE_SIZE)]
            assert response_headers is not None
            response_headers["link"] = (
                "<https://api.github.com/repositories/1309835643/actions/workflows/"
                f"{workflow_id}/runs?{urlencode({'branch': 'main', 'created': created_filter, 'per_page': incidents.SOURCE_PAGE_SIZE, 'page': 2})}>; rel=\"next\""
            )
        start = (page - 1) * incidents.SOURCE_PAGE_SIZE
        return {
            "total_count": len(rows),
            "workflow_runs": rows[start:start + incidents.SOURCE_PAGE_SIZE],
        }

    monkeypatch.setattr(incidents, "_request_json", request)
    selected, cursor, held = incidents._workflow_runs_since(
        path=path,
        workflow_id=workflow_id,
        repository="owner/repo",
        api_url="https://api.github.com",
        token="test-token",
        cursor={
            "mode": "backfill",
            "window_start": incidents.INITIAL_BACKFILL_AT.isoformat(),
            "created_at": incidents.INITIAL_BACKFILL_AT.isoformat(),
            "run_id": 0,
            "pending_runs": [],
        },
        now=now,
        deadline=incidents.time.monotonic() + 10,
        repository_id=1309835643,
    )

    assert [row["id"] for row in selected] == [row["id"] for row in rows]
    assert len(calls) == 2
    assert cursor["scan_complete"] is True
    assert held is False


def test_main_hands_off_durable_incomplete_backlog_without_repeating_failure_email(tmp_path, monkeypatch, capsys):
    result_path = tmp_path / "incident-reconciliation.json"
    output_path = tmp_path / "github-output.txt"
    summary_path = tmp_path / "step-summary.md"
    result = {
        "schema_version": "incident-reconciliation-v1",
        "consumer_run_id": "900",
        "consumer_attempt": 1,
        "consumer_sha": "a" * 40,
        "business_status": "unknown",
        "diagnostic_complete": False,
        "coverage_status": "incomplete",
        "incident_handoff_status": "incomplete",
        "notification_due": False,
        "unprocessed_source_runs": [{"workflow": "Official event monitor", "run_id": 123, "attempt": 1}],
        "source_cursors": {},
        "observed_at": "2026-10-25T09:00:00+00:00",
    }

    def fake_reconcile(*, result_path, evidence_directory):
        result_path.write_text(json.dumps(result), encoding="utf-8")
        with open(incidents.os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write("notification_due=false\n")
            output.write("business_status=unknown\n")
        return result

    monkeypatch.setattr(incidents, "reconcile", fake_reconcile)
    monkeypatch.setattr(incidents.sys, "argv", ["scripts.incident_reconciliation"])
    monkeypatch.setenv("INCIDENT_RECONCILIATION_RESULT_PATH", str(result_path))
    monkeypatch.setenv("INCIDENT_EVIDENCE_DIR", str(tmp_path / "evidence"))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))

    assert incidents.main() == 0

    saved = json.loads(result_path.read_text(encoding="utf-8"))
    assert saved == result
    assert saved["coverage_status"] == "incomplete"
    assert saved["diagnostic_complete"] is False
    assert saved["incident_handoff_status"] == "incomplete"
    assert saved["unprocessed_source_runs"]
    assert "business_status: unknown" in summary_path.read_text(encoding="utf-8")
    assert "unprocessed_source_runs: 1" in summary_path.read_text(encoding="utf-8")
    assert "business_status=unknown" in output_path.read_text(encoding="utf-8")
    assert "unknown" in capsys.readouterr().out


def test_main_keeps_reconciliation_failures_nonzero(tmp_path, monkeypatch):
    result_path = tmp_path / "incident-reconciliation.json"

    def fail_reconcile(*, result_path, evidence_directory):
        raise LivenessAuditError("source_artifact_identity_invalid")

    monkeypatch.setattr(incidents, "reconcile", fail_reconcile)
    monkeypatch.setattr(incidents.sys, "argv", ["scripts.incident_reconciliation"])
    monkeypatch.setenv("INCIDENT_RECONCILIATION_RESULT_PATH", str(result_path))
    monkeypatch.setenv("INCIDENT_EVIDENCE_DIR", str(tmp_path / "evidence"))

    assert incidents.main() == 1
    saved = json.loads(result_path.read_text(encoding="utf-8"))
    assert saved["incident_handoff_status"] == "failed"
    assert saved["diagnostic_complete"] is False
    assert saved["failure_reason"] == "source_artifact_identity_invalid"


def test_download_artifact_verifies_run_sha_and_bounded_zip_member(monkeypatch):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("scheduled-terminal-77-attempt-3.json", b'{"schema_version":"notification-terminal-v2"}')

    def fake_request(_api, _repo, _token, _method, _path, **_kwargs):
        return {
            "total_count": 1,
            "artifacts": [{
                "id": 999,
                "name": "scheduled-terminal-77-attempt-3",
                "expired": False,
                "workflow_run": {"id": 77, "head_sha": "b" * 40},
            }],
        }

    monkeypatch.setattr(incidents, "_request_json", fake_request)
    monkeypatch.setattr(incidents, "_open_artifact_url", lambda *_args, **_kwargs: io.BytesIO(buffer.getvalue()))
    data = incidents._download_artifact_json(
        run={"id": 77, "run_attempt": 3, "head_sha": "b" * 40},
        expected_artifact_name="scheduled-terminal-77-attempt-3",
        expected_member="scheduled-terminal-77-attempt-3.json",
        repository="owner/repo", api_url="https://api.github.com", token="secret",
        deadline=incidents.time.monotonic() + 10,
    )
    assert json.loads(data)["schema_version"] == "notification-terminal-v2"


def test_research_incident_uses_open_reminder_and_recovery_policy(monkeypatch):
    now = datetime(2026, 10, 24, 4, 0, tzinfo=UTC)
    event = {
        "run_id": "77", "attempt": "2", "head_sha": "c" * 40,
        "workflow_id": 319283753, "conclusion": "failure",
    }
    calls = []
    issues = []
    monkeypatch.setattr(incidents, "_open_incidents", lambda *_a, **_k: list(issues))

    def fake_request(_api, _repo, _token, method, path, body, **_kwargs):
        calls.append((method, path, body))
        if method == "POST" and path == "issues":
            issue = {"number": 900, "title": body["title"], "body": body["body"]}
            issues.append(issue)
            return issue
        if method == "PATCH" and path == "issues/900":
            if "body" in body:
                issues[0]["body"] = body["body"]
            return issues[0]
        return {}

    monkeypatch.setattr(incidents, "_request_json", fake_request)
    first = incidents._research_incident(
        event=event, repository="owner/repo", api_url="https://api.github.com", token="token", now=now,
    )
    assert first["opened_issue_numbers"] == [900]

    issues[0]["body"] = issues[0]["body"].replace(
        "Next reminder at: 2026-10-24T04:30:00+00:00",
        "Next reminder at: 2026-10-24T03:59:00+00:00",
    )
    reminder = incidents._research_incident(
        event=event, repository="owner/repo", api_url="https://api.github.com", token="token", now=now,
    )
    assert reminder["reminded_issue_numbers"] == [900]

    event["conclusion"] = "success"
    still_degraded = incidents._research_incident(
        event=event, repository="owner/repo", api_url="https://api.github.com", token="token", now=now,
        terminal={
            "schema_version": "unified-research-terminal-v1", "run_id": 77, "attempt": 2,
            "sha": "c" * 40, "production_run": True,
            "business_status": "degraded", "reason": "writer_queue_timeout",
        },
    )
    assert still_degraded["status"] == "degraded"
    assert not any(body.get("state") == "closed" for method, _path, body in calls)

    recovered = incidents._research_incident(
        event=event, repository="owner/repo", api_url="https://api.github.com", token="token", now=now,
        terminal={
            "schema_version": "unified-research-terminal-v1", "run_id": 77, "attempt": 2,
            "sha": "c" * 40, "production_run": True,
            "business_status": "healthy", "reason": "",
        },
    )
    assert recovered["recovered_issue_numbers"] == [900]


def test_research_smoke_run_cannot_close_production_incident():
    result = incidents._research_incident(
        event={
            "run_id": "77", "attempt": "2", "head_sha": "c" * 40,
            "workflow_id": 319283753, "conclusion": "success",
        },
        repository="owner/repo", api_url="https://api.github.com", token="token",
        now=datetime(2026, 10, 24, 4, 0, tzinfo=UTC),
        terminal={
            "schema_version": "unified-research-terminal-v1", "run_id": 77, "attempt": 2,
            "sha": "c" * 40, "production_run": False,
            "business_status": "not_applicable", "reason": "non_production_scan",
        },
    )
    assert result["status"] == "not_applicable"


def test_recovery_is_recorded_without_failure_notification_reason():
    assert incidents._notification_reasons([{
        "recovered_issue_numbers": [1057],
        "closed_issue_numbers": [1059, 1060],
        "audit_incident_recovered": True,
    }]) == []
    assert incidents._notification_reasons([{
        "opened_issue_numbers": [1057],
    }]) == ["opened_issue_numbers"]
    assert incidents._notification_reasons([{
        "reminded_issue_numbers": [1057],
    }]) == ["reminded_issue_numbers"]


def test_research_workflow_run_uses_attempt_bound_terminal_artifact(monkeypatch):
    now = datetime(2026, 10, 24, 4, 0, tzinfo=UTC)
    run = {
        "id": 77, "run_attempt": 2, "workflow_id": 319283753,
        "head_branch": "main", "head_sha": "c" * 40,
        "head_repository": {"full_name": "owner/repo"}, "conclusion": "success",
    }
    artifact = {
        "schema_version": "unified-research-terminal-v1", "run_id": 77,
        "attempt": 2, "sha": "c" * 40, "production_run": True,
        "business_status": "degraded", "reason": "writer_queue_timeout",
    }
    fetched = []
    monkeypatch.setattr(
        incidents, "_download_artifact_json",
        lambda **kwargs: fetched.append(kwargs) or json.dumps(artifact).encode(),
    )
    monkeypatch.setattr(incidents, "_open_incidents", lambda *_a, **_k: [])
    monkeypatch.setattr(incidents, "_request_json", lambda *_a, **_k: {"number": 901})

    result = incidents._reconcile_source_run(
        run=run, workflow_name="Unified Taiwan-US research report",
        repository="owner/repo", api_url="https://api.github.com", token="token",
        now=now, deadline=incidents.time.monotonic() + 10,
    )

    assert result["status"] == "degraded"
    assert result["opened_issue_numbers"] == [901]
    assert fetched[0]["expected_artifact_name"] == "unified-research-terminal-77-attempt-2"
    assert fetched[0]["expected_member"] == "unified-research-terminal.json"


def test_source_run_reader_rejects_truncated_short_page(monkeypatch):
    now = datetime(2026, 10, 24, 4, 0, tzinfo=UTC)
    workflow_id = 319283753

    def fake_request(_api, _repo, _token, _method, _url, *, response_headers=None, deadline_monotonic=None):
        return {
            "total_count": 2,
            "workflow_runs": [{
                "id": 10, "workflow_id": workflow_id, "created_at": "2026-10-24T03:55:00Z",
                "head_branch": "main", "head_sha": "a" * 40,
                "head_repository": {"full_name": "owner/repo"}, "run_attempt": 1,
                "status": "completed", "conclusion": "failure",
            }],
        }

    monkeypatch.setattr(incidents, "_request_json", fake_request)
    with pytest.raises(LivenessAuditError, match="source_runs_pagination_incomplete"):
        incidents._workflow_runs_since(
            path=".github/workflows/unified-research-report.yml", workflow_id=workflow_id,
            repository="owner/repo", api_url="https://api.github.com", token="token",
            cursor={"mode": "live", "created_at": "2026-10-24T03:45:00+00:00", "run_id": 0, "pending_runs": []},
            now=now, deadline=incidents.time.monotonic() + 10, repository_id=123,
        )


def test_cursor_artifact_must_bind_to_exact_consumer_run_and_revision(monkeypatch):
    central_id = 777
    sha = "a" * 40
    run = {
        "id": 501, "run_attempt": 2, "workflow_id": central_id,
        "path": incidents.CENTRAL_WORKFLOW_PATH, "head_branch": "main",
        "head_sha": sha, "head_repository": {"full_name": "owner/repo"},
    }

    def fake_request(_api, _repo, _token, _method, path, **_kwargs):
        if path.endswith("incident-reconciliation.yml"):
            return {"id": central_id, "path": incidents.CENTRAL_WORKFLOW_PATH, "state": "active"}
        return {"workflow_runs": [run]}

    monkeypatch.setattr(incidents, "_request_json", fake_request)
    monkeypatch.setattr(incidents, "_download_artifact_json", lambda **_kwargs: json.dumps({
        "schema_version": "incident-reconciliation-v1",
        "consumer_run_id": "999", "consumer_attempt": 2, "consumer_sha": sha,
        "source_cursors": {"workflow.yml": {"created_at": "2026-10-24T03:50:00Z", "run_id": 9}},
    }).encode())

    assert incidents._load_cursor_state(
        repository="owner/repo", api_url="https://api.github.com", token="token",
        current_run_id=700, deadline=incidents.time.monotonic() + 10,
    ) == {}


def test_repository_metadata_uses_canonical_api_url_without_duplicate_repos_prefix(monkeypatch):
    captured = []

    class Response:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return b'{"id":1309835643}'

    def fake_urlopen(request, timeout):
        captured.append((request.full_url, timeout))
        return Response()

    monkeypatch.setattr("scripts.monitor_liveness.urlopen", fake_urlopen)
    payload = incidents._request_json(
        "https://api.github.com", "owner/repo", "token", "GET",
        "https://api.github.com/repos/owner/repo",
    )

    assert payload["id"] == 1309835643
    assert captured[0][0] == "https://api.github.com/repos/owner/repo"
    assert "/repos/owner/repo/repos/" not in captured[0][0]


def test_legacy_official_event_incident_marker_is_accepted_for_cadence():
    assert incidents._cadence_marker_valid(f"{incidents.EVENT_INCIDENT_MARKER}{'a' * 24}")
    assert not incidents._cadence_marker_valid(f"{incidents.EVENT_INCIDENT_MARKER}{'a' * 32}")


def _cadence_result(path, *, run_id="700", attempt=2, sha="a" * 40, issue_number=901, closed=False):
    now = datetime(2026, 10, 24, 4, 0, tzinfo=UTC)
    marker = f"{incidents.SCHEDULED_INCIDENT_MARKER}{'b' * 32}"
    result = {
        "schema_version": "incident-reconciliation-v1",
        "consumer_run_id": run_id,
        "consumer_attempt": attempt,
        "consumer_sha": sha,
        "notification_due": True,
        "notification_cadence_confirmations": [{
            "issue_number": issue_number,
            "marker": marker,
            "next_reminder_at": "2026-10-24T04:30:00+00:00",
        }],
        "results": [],
    }
    path.write_text(json.dumps(result), encoding="utf-8")
    issue = {
        "number": issue_number,
        "state": "closed" if closed else "open",
        "body": (
            f"{marker}\nNext reminder at: {now.isoformat()}\n"
            f"Alert pending consumer: {run_id}/{attempt}\nAlert pending since: {now.isoformat()}"
        ),
    }
    return now, marker, issue


def test_alert_cadence_advances_only_after_confirmed_native_alert(tmp_path, monkeypatch):
    result_path = tmp_path / "decision.json"
    now, marker, issue = _cadence_result(result_path)
    calls = []

    def fake_request(_api, _repo, _token, method, path, payload=None, **_kwargs):
        calls.append((method, path, payload))
        if method == "GET" and path == "issues/901":
            return issue
        if method == "PATCH" and path == "issues/901":
            issue["body"] = payload["body"]
            return issue
        raise AssertionError((method, path, payload))

    monkeypatch.setattr(incidents, "_request_json", fake_request)
    result = incidents.finalize_alert_cadence(
        result_path=result_path, repository="owner/repo", api_url="https://api.github.com",
        token="token", consumer_run_id="700", consumer_attempt=2, consumer_sha="a" * 40,
        alert_emitted=True, alert_step_outcome="failure", now=now,
    )

    assert result["cadence_finalization"]["status"] == "completed"
    assert result["cadence_finalization"]["updated_issue_numbers"] == [901]
    assert "Next reminder at: 2026-10-24T04:30:00+00:00" in issue["body"]
    assert issue["body"].splitlines().count(marker) == 1
    assert "Alert pending consumer:" not in issue["body"]
    assert "Alert pending since:" not in issue["body"]
    assert [call[:2] for call in calls] == [("GET", "issues/901"), ("PATCH", "issues/901")]


def test_alert_cadence_does_not_advance_without_expected_failure_marker(tmp_path, monkeypatch):
    result_path = tmp_path / "decision.json"
    now, _marker, _issue = _cadence_result(result_path)
    calls = []
    monkeypatch.setattr(incidents, "_request_json", lambda *args, **kwargs: calls.append(args))

    with pytest.raises(LivenessAuditError, match="alert_terminal_unconfirmed"):
        incidents.finalize_alert_cadence(
            result_path=result_path, repository="owner/repo", api_url="https://api.github.com",
            token="token", consumer_run_id="700", consumer_attempt=2, consumer_sha="a" * 40,
            alert_emitted=False, alert_step_outcome="success", now=now,
        )

    saved = json.loads(result_path.read_text(encoding="utf-8"))
    assert saved["cadence_finalization"]["status"] == "failed"
    assert calls == []


def test_alert_cadence_marks_recovered_issue_as_superseded(tmp_path, monkeypatch):
    result_path = tmp_path / "decision.json"
    now, _marker, issue = _cadence_result(result_path, closed=True)
    calls = []
    monkeypatch.setattr(
        incidents, "_request_json",
        lambda _api, _repo, _token, method, path, *_args, **_kwargs: calls.append((method, path)) or issue,
    )

    result = incidents.finalize_alert_cadence(
        result_path=result_path, repository="owner/repo", api_url="https://api.github.com",
        token="token", consumer_run_id="700", consumer_attempt=2, consumer_sha="a" * 40,
        alert_emitted=True, alert_step_outcome="failure", now=now,
    )

    assert result["cadence_finalization"]["status"] == "completed"
    assert result["cadence_finalization"]["updated_issue_numbers"] == []
    assert result["cadence_finalization"]["superseded_by_recovery_issue_numbers"] == [901]
    assert calls == [("GET", "issues/901")]


def test_alert_cadence_requires_the_same_issue_reservation_consumer(tmp_path, monkeypatch):
    result_path = tmp_path / "decision.json"
    now, _marker, issue = _cadence_result(result_path)
    issue["body"] = issue["body"].replace("Alert pending consumer: 700/2", "Alert pending consumer: 701/1")
    monkeypatch.setattr(incidents, "_request_json", lambda *_args, **_kwargs: issue)

    with pytest.raises(LivenessAuditError, match="reservation_mismatch"):
        incidents.finalize_alert_cadence(
            result_path=result_path, repository="owner/repo", api_url="https://api.github.com",
            token="token", consumer_run_id="700", consumer_attempt=2, consumer_sha="a" * 40,
            alert_emitted=True, alert_step_outcome="failure", now=now,
        )


def test_alert_cadence_rejects_invalid_pending_reservation_time(tmp_path, monkeypatch):
    result_path = tmp_path / "decision.json"
    now, _marker, issue = _cadence_result(result_path)
    issue["body"] = issue["body"].replace(
        f"Alert pending since: {now.isoformat()}",
        "Alert pending since: invalid",
    )
    monkeypatch.setattr(incidents, "_request_json", lambda *_args, **_kwargs: issue)

    with pytest.raises(LivenessAuditError, match="reservation_mismatch"):
        incidents.finalize_alert_cadence(
            result_path=result_path, repository="owner/repo", api_url="https://api.github.com",
            token="token", consumer_run_id="700", consumer_attempt=2, consumer_sha="a" * 40,
            alert_emitted=True, alert_step_outcome="failure", now=now,
        )


def test_alert_cadence_rejects_duplicate_issue_and_consumer_mismatch(tmp_path, monkeypatch):
    result_path = tmp_path / "decision.json"
    now, _marker, _issue = _cadence_result(result_path)
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["notification_cadence_confirmations"].append(payload["notification_cadence_confirmations"][0])
    result_path.write_text(json.dumps(payload), encoding="utf-8")
    calls = []
    monkeypatch.setattr(incidents, "_request_json", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(LivenessAuditError, match="cadence_confirmation_invalid"):
        incidents.finalize_alert_cadence(
            result_path=result_path, repository="owner/repo", api_url="https://api.github.com",
            token="token", consumer_run_id="700", consumer_attempt=2, consumer_sha="a" * 40,
            alert_emitted=True, alert_step_outcome="failure", now=now,
        )
    assert calls == []

    payload["notification_cadence_confirmations"] = payload["notification_cadence_confirmations"][:1]
    result_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(LivenessAuditError, match="consumer_identity_mismatch"):
        incidents.finalize_alert_cadence(
            result_path=result_path, repository="owner/repo", api_url="https://api.github.com",
            token="token", consumer_run_id="701", consumer_attempt=2, consumer_sha="a" * 40,
            alert_emitted=True, alert_step_outcome="failure", now=now,
        )
    assert calls == []
