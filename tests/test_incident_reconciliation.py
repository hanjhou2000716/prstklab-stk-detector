from __future__ import annotations

import io
import json
import time
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

import scripts.incident_reconciliation as incidents
from scripts.monitor_liveness import GitHubAPIHttpError, LivenessAuditError


def test_central_reconciliation_wakes_on_gmail_sync_completion():
    workflow = Path(__file__).parents[1] / ".github" / "workflows" / "incident-reconciliation.yml"
    text = workflow.read_text(encoding="utf-8")
    workflow_run = text.split("  workflow_run:", 1)[1].split("  schedule:", 1)[0]

    assert "Gmail history sync (Supabase)" in workflow_run
    assert "types: [completed]" in workflow_run


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


def test_stale_official_monitor_with_stable_terminal_jobs_is_reconciled_without_changing_run_status(monkeypatch):
    workflow_id = 320209983
    run_id = 39698088993
    sha = "cc40ba0401362f6214b540c70b5e1aa3100d5773"
    created_at = "2026-10-22T00:10:37Z"
    now = datetime(2026, 10, 25, 20, 0, tzinfo=UTC)
    run = {
        "id": run_id,
        "workflow_id": workflow_id,
        "run_attempt": 1,
        "created_at": created_at,
        "updated_at": "2026-10-22T00:14:51Z",
        "status": "in_progress",
        "head_branch": "main",
        "head_sha": sha,
        "head_repository": {"full_name": "owner/repo"},
    }
    jobs = [
        {
            "id": 119560307175,
            "name": "monitor-admission",
            "run_id": run_id,
            "run_attempt": 1,
            "status": "completed",
            "conclusion": "success",
            "started_at": "2026-10-22T00:10:39Z",
            "completed_at": "2026-10-22T00:10:44Z",
        },
        {
            "id": 119560351562,
            "name": "monitor-send-deploy",
            "run_id": run_id,
            "run_attempt": 1,
            "status": "completed",
            "conclusion": "success",
            "started_at": "2026-10-22T00:10:48Z",
            "completed_at": "2026-10-22T00:14:51Z",
        },
    ]

    def call(cursor, observed_at):
        def fake_request(_api, _repo, _token, _method, request_path, *, response_headers=None, deadline_monotonic=None):
            path = request_path.split("?", 1)[0]
            if path == f"actions/runs/{run_id}":
                return dict(run)
            if path == f"actions/runs/{run_id}/attempts/1/jobs":
                return {"total_count": len(jobs), "jobs": list(jobs)}
            if request_path.startswith(f"actions/workflows/{workflow_id}/runs?"):
                return {"total_count": 0, "workflow_runs": []}
            raise AssertionError(f"Unexpected GitHub API path: {request_path}")

        monkeypatch.setattr(incidents, "_request_json", fake_request)
        return incidents._workflow_runs_since(
            path=".github/workflows/official-event-monitor.yml",
            workflow_id=workflow_id,
            repository="owner/repo",
            api_url="https://api.github.com",
            token="test-token",
            cursor=cursor,
            now=observed_at,
            deadline=incidents.time.monotonic() + 30,
            repository_id=1309835643,
        )

    cursor = {
        "mode": "live",
        "created_at": "2026-10-22T00:00:00+00:00",
        "run_id": 0,
        "pending_runs": [{
            "run_id": run_id,
            "workflow_id": workflow_id,
            "created_at": "2026-10-22T00:10:37+00:00",
            "attempt": 1,
            "head_sha": sha,
        }],
    }

    first_rows, first_cursor, first_held = call(cursor, now)
    assert first_rows == []
    assert first_held is True
    first_observation = first_cursor["pending_runs"][0]["terminal_jobs_observation"]
    assert first_observation["observed_at"] == now.isoformat()

    second_rows, second_cursor, second_held = call(first_cursor, now + timedelta(seconds=1))
    assert second_rows == []
    assert second_held is True

    terminal_rows, terminal_cursor, terminal_held = call(second_cursor, now + timedelta(seconds=3))
    assert len(terminal_rows) == 1
    assert terminal_rows[0]["status"] == "in_progress"
    assert terminal_held is True  # Processing the pending result removes the hold in reconcile().
    evidence = terminal_rows[0]["_incident_source_terminal_evidence"]
    assert evidence["schema_version"] == "source-run-terminal-jobs-v1"
    assert evidence["resolution"] == "stable_complete_jobs_snapshot"
    assert evidence["workflow_contract"] == "official-event-monitor-cc40ba0-jobs-v1"
    assert evidence["job_names"] == ["monitor-admission", "monitor-send-deploy"]
    assert evidence["confirmed_at"] == (now + timedelta(seconds=3)).isoformat()
    assert terminal_cursor["pending_runs"][0]["terminal_jobs_observation"]["fingerprint"] == first_observation["fingerprint"]

    trace = {
        "events": [],
        "recorded_at": "2026-10-22T00:14:47.055504+00:00",
        "run_attempt": "1",
        "schema_version": "official-event-trace-v1",
        "stages": {
            "batch_failed_event_count": "0", "batch_partial_event_count": "0",
            "candidate_incident_count": "0", "candidate_incident_reason": "",
            "durable_receipt": "false", "notification_expected": "false",
            "notification_reason": "no_event", "prepare": "not_required",
            "public_gate": "false", "queue": "not_required", "receipt_callback": "skipped",
            "scan": "success", "sender": "skipped",
        },
        "workflow_run_id": str(run_id),
        "workflow_sha": sha,
    }
    monkeypatch.setattr(incidents, "_download_artifact_json", lambda **_kwargs: json.dumps(trace).encode("utf-8"))
    captured = {}

    def reconcile_trace(*, trace_path, **_kwargs):
        captured["trace"] = json.loads(Path(trace_path).read_text(encoding="utf-8"))
        return {"status": "no_notification", "diagnostic_complete": True, "incident_active": False}

    monkeypatch.setattr(incidents, "reconcile_official_events", reconcile_trace)
    source_result = incidents._reconcile_source_run(
        run=terminal_rows[0], workflow_name="Official event monitor",
        repository="owner/repo", api_url="https://api.github.com",
        token="test-token", now=now + timedelta(seconds=3),
        deadline=incidents.time.monotonic() + 30,
    )
    assert captured["trace"]["stages"]["notification_reason"] == "no_event"
    assert source_result["status"] == "no_notification"
    assert source_result["diagnostic_complete"] is True
    assert source_result["source_run_terminal_evidence"] == evidence


def test_stale_terminal_job_resolution_fails_closed_on_contract_mismatch(monkeypatch):
    run_id = 39698088993
    sha = "cc40ba0401362f6214b540c70b5e1aa3100d5773"
    run = {"id": run_id, "workflow_id": 320209983, "run_attempt": 1, "head_sha": sha}
    jobs = [{
        "id": 1, "name": "unexpected-job", "run_id": run_id, "run_attempt": 1,
        "status": "completed", "conclusion": "success",
        "started_at": "2026-10-22T00:10:39Z", "completed_at": "2026-10-22T00:10:44Z",
    }]

    def fake_request(_api, _repo, _token, _method, _request_path, *, response_headers=None, deadline_monotonic=None):
        return {"total_count": len(jobs), "jobs": jobs}

    monkeypatch.setattr(incidents, "_request_json", fake_request)
    with pytest.raises(LivenessAuditError, match="incident_source_pending_jobs_contract_mismatch"):
        incidents._read_source_job_snapshot(
            run=run,
            repository="owner/repo",
            repository_id=1309835643,
            api_url="https://api.github.com",
            token="test-token",
            deadline=incidents.time.monotonic() + 30,
            expected_jobs=frozenset({"monitor-admission", "monitor-send-deploy"}),
        )


def test_stale_terminal_job_snapshot_waits_for_active_contract_job(monkeypatch):
    run_id = 39698088993
    jobs = [
        {
            "id": 1, "name": "monitor-admission", "run_id": run_id, "run_attempt": 1,
            "status": "completed", "conclusion": "success",
            "started_at": "2026-10-22T00:10:39Z", "completed_at": "2026-10-22T00:10:44Z",
        },
        {
            "id": 2, "name": "monitor-send-deploy", "run_id": run_id, "run_attempt": 1,
            "status": "waiting", "conclusion": "",
            "started_at": "2026-10-22T00:10:48Z", "completed_at": "",
        },
    ]

    def fake_request(_api, _repo, _token, _method, _request_path, *, response_headers=None, deadline_monotonic=None):
        return {"total_count": len(jobs), "jobs": jobs}

    monkeypatch.setattr(incidents, "_request_json", fake_request)
    snapshot = incidents._read_source_job_snapshot(
        run={
            "id": run_id, "workflow_id": 320209983, "run_attempt": 1,
            "head_sha": "cc40ba0401362f6214b540c70b5e1aa3100d5773",
        },
        repository="owner/repo",
        repository_id=1309835643,
        api_url="https://api.github.com",
        token="test-token",
        deadline=incidents.time.monotonic() + 30,
        expected_jobs=frozenset({"monitor-admission", "monitor-send-deploy"}),
    )
    assert snapshot["all_completed"] is False


def test_stale_terminal_job_snapshot_rejects_truncated_jobs_page(monkeypatch):
    run_id = 39698088993
    jobs = [{
        "id": 1, "name": "monitor-admission", "run_id": run_id, "run_attempt": 1,
        "status": "completed", "conclusion": "success",
        "started_at": "2026-10-22T00:10:39Z", "completed_at": "2026-10-22T00:10:44Z",
    }]

    def fake_request(_api, _repo, _token, _method, _request_path, *, response_headers=None, deadline_monotonic=None):
        return {"total_count": 2, "jobs": jobs}

    monkeypatch.setattr(incidents, "_request_json", fake_request)
    with pytest.raises(LivenessAuditError, match="incident_source_pending_jobs_pagination_incomplete"):
        incidents._read_source_job_snapshot(
            run={
                "id": run_id, "workflow_id": 320209983, "run_attempt": 1,
                "head_sha": "cc40ba0401362f6214b540c70b5e1aa3100d5773",
            },
            repository="owner/repo",
            repository_id=1309835643,
            api_url="https://api.github.com",
            token="test-token",
            deadline=incidents.time.monotonic() + 30,
            expected_jobs=frozenset({"monitor-admission", "monitor-send-deploy"}),
        )


def test_stale_terminal_job_resolution_does_not_release_unknown_workflow_revision():
    assert incidents.SOURCE_TERMINAL_JOB_CONTRACTS.get((
        ".github/workflows/official-event-monitor.yml",
        "a" * 40,
    )) is None


def test_processed_terminal_job_run_advances_cursor_only_forward():
    path = ".github/workflows/official-event-monitor.yml"
    terminal_evidence = {"schema_version": "source-run-terminal-jobs-v1"}
    current = {path: {"created_at": "2026-10-25T20:00:00+00:00", "run_id": 100}}
    processed: dict[str, dict] = {}

    incidents._record_processed_checkpoint(
        processed_last=processed, cursors=current, path=path,
        created_at=datetime(2026, 10, 25, 20, 1, tzinfo=UTC), run_id=101,
        advance_cursor=False, terminal_evidence=terminal_evidence,
    )
    assert processed[path] == {"created_at": "2026-10-25T20:01:00+00:00", "run_id": 101}

    incidents._record_processed_checkpoint(
        processed_last=processed, cursors=current, path=path,
        created_at=datetime(2026, 10, 25, 19, 59, tzinfo=UTC), run_id=99,
        advance_cursor=False, terminal_evidence=terminal_evidence,
    )
    assert processed[path] == {"created_at": "2026-10-25T20:01:00+00:00", "run_id": 101}


def test_pending_run_without_terminal_evidence_cannot_advance_cursor():
    path = ".github/workflows/official-event-monitor.yml"
    processed: dict[str, dict] = {}
    incidents._record_processed_checkpoint(
        processed_last=processed,
        cursors={},
        path=path,
        created_at=datetime(2026, 10, 25, 20, 1, tzinfo=UTC),
        run_id=101,
        advance_cursor=False,
        terminal_evidence=None,
    )
    assert processed == {}


def test_reconcile_releases_only_stable_terminal_pending_run_and_recovers_next_cycle(monkeypatch, tmp_path):
    target_path = ".github/workflows/official-event-monitor.yml"
    workflow_ids = {
        target_path: 320209983,
        ".github/workflows/scheduled-brief.yml": 10,
        ".github/workflows/scheduled-brief-slot-audit.yml": 11,
        ".github/workflows/unified-research-report.yml": 12,
    }
    run_id = 39698088993
    run_sha = "cc40ba0401362f6214b540c70b5e1aa3100d5773"
    run = {
        "id": run_id,
        "workflow_id": workflow_ids[target_path],
        "run_attempt": 1,
        "created_at": "2026-10-22T00:10:37Z",
        "updated_at": "2026-10-22T00:14:51Z",
        "status": "in_progress",
        "head_branch": "main",
        "head_sha": run_sha,
        "head_repository": {"full_name": "owner/repo"},
    }
    jobs = [
        {
            "id": 119560307175,
            "name": "monitor-admission",
            "run_id": run_id,
            "run_attempt": 1,
            "status": "completed",
            "conclusion": "success",
            "started_at": "2026-10-22T00:10:39Z",
            "completed_at": "2026-10-22T00:10:44Z",
        },
        {
            "id": 119560351562,
            "name": "monitor-send-deploy",
            "run_id": run_id,
            "run_attempt": 1,
            "status": "completed",
            "conclusion": "success",
            "started_at": "2026-10-22T00:10:48Z",
            "completed_at": "2026-10-22T00:14:51Z",
        },
    ]
    cursor_state = {
        target_path: {
            "mode": "live",
            "created_at": "2026-10-22T00:00:00+00:00",
            "run_id": 0,
            "pending_runs": [{
                "run_id": run_id,
                "workflow_id": workflow_ids[target_path],
                "created_at": "2026-10-22T00:10:37+00:00",
                "attempt": 1,
                "head_sha": run_sha,
            }],
        },
    }
    monkeypatch.setattr(
        incidents,
        "_load_cursor_state",
        lambda **_kwargs: json.loads(json.dumps(cursor_state)),
    )
    monkeypatch.setattr(
        incidents,
        "_source_workflow_id",
        lambda *, path, **_kwargs: workflow_ids[path],
    )

    def fake_request(_api, _repo, _token, _method, request_path, *, response_headers=None, deadline_monotonic=None):
        if request_path == "https://api.github.com/repos/owner/repo":
            return {"id": 1309835643}
        if request_path == f"actions/runs/{run_id}":
            return dict(run)
        if request_path == f"actions/runs/{run_id}/attempts/1/jobs?per_page=100&page=1":
            return {"total_count": len(jobs), "jobs": list(jobs)}
        if request_path.startswith("actions/workflows/") and "/runs?" in request_path:
            return {"total_count": 0, "workflow_runs": []}
        raise AssertionError(f"Unexpected GitHub API path: {request_path}")

    monkeypatch.setattr(incidents, "_request_json", fake_request)
    monkeypatch.setattr(incidents, "_download_artifact_json", lambda **_kwargs: b"{}")
    monkeypatch.setattr(
        incidents,
        "reconcile_official_events",
        lambda **_kwargs: {
            "status": "no_notification",
            "diagnostic_complete": True,
            "incident_active": False,
        },
    )
    event_path = tmp_path / "event.json"
    event_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_run")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_API_URL", "https://api.github.com")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_RUN_ID", "999999")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_SHA", "d" * 40)
    monkeypatch.setenv("GITHUB_OUTPUT", "")

    result_path = tmp_path / "result.json"
    evidence_directory = tmp_path / "evidence"

    first = incidents.reconcile(result_path=result_path, evidence_directory=evidence_directory)
    first_pending = first["source_cursors"][target_path]["pending_runs"]
    assert len(first_pending) == 1
    assert "terminal_jobs_observation" in first_pending[0]
    cursor_state.update(first["source_cursors"])

    time.sleep(2.1)
    second = incidents.reconcile(result_path=result_path, evidence_directory=evidence_directory)
    assert second["source_cursors"][target_path]["pending_runs"] == []
    reconciled = next(row for row in second["results"] if row.get("source_run_id") == run_id)
    assert reconciled["source_run_terminal_evidence"]["resolution"] == "stable_complete_jobs_snapshot"
    assert second["coverage_status"] == "incomplete"  # The snapshot cycle remains conservatively held.
    cursor_state.update(second["source_cursors"])

    third = incidents.reconcile(result_path=result_path, evidence_directory=evidence_directory)
    assert third["source_cursors"][target_path]["pending_runs"] == []
    assert third["coverage_status"] == "complete"
    assert third["diagnostic_complete"] is True


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


def test_main_hands_off_bounded_get_404_with_durable_identity_bound_result(tmp_path, monkeypatch, capsys):
    result_path = tmp_path / "incident-reconciliation.json"
    output_path = tmp_path / "github-output.txt"
    summary_path = tmp_path / "step-summary.md"

    def fail_reconcile(*, result_path, evidence_directory):
        raise GitHubAPIHttpError(
            status_code=404, method="GET", endpoint_class="actions/runs/{run_id}",
            request_id="ABC:123", retry_count=3,
        )

    monkeypatch.setattr(incidents, "reconcile", fail_reconcile)
    monkeypatch.setattr(incidents.sys, "argv", ["scripts.incident_reconciliation"])
    monkeypatch.setenv("INCIDENT_RECONCILIATION_RESULT_PATH", str(result_path))
    monkeypatch.setenv("GITHUB_RUN_ID", "40183001117")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))

    assert incidents.main() == 0

    saved = json.loads(result_path.read_text(encoding="utf-8"))
    assert saved["consumer_run_id"] == "40183001117"
    assert saved["consumer_attempt"] == 2
    assert saved["consumer_sha"] == "a" * 40
    assert saved["business_status"] == "degraded"
    assert saved["diagnostic_complete"] is False
    assert saved["coverage_status"] == "incomplete"
    assert saved["incident_handoff_status"] == "incomplete"
    assert saved["failure_reason"] == "monitor_liveness_api_http_404"
    assert saved["failure_evidence"]["endpoint_class"] == "actions/runs/{run_id}"
    assert saved["failure_evidence"]["request_id"] == "ABC:123"
    assert "notification_due=false" in output_path.read_text(encoding="utf-8")
    assert "business_status=degraded" in output_path.read_text(encoding="utf-8")
    assert "alert owner: independent central health workflow" in summary_path.read_text(encoding="utf-8")
    assert "incident_reconciliation_failed:monitor_liveness_api_http_404" in capsys.readouterr().err


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


@pytest.mark.parametrize(
    ("completion_age", "expected"),
    [
        (timedelta(minutes=29, seconds=59), None),
        (timedelta(minutes=30), "advance_with_unknown"),
        (timedelta(minutes=31), "advance_with_unknown"),
    ],
)
def test_missing_artifact_cursor_resolution_waits_for_settle_window(completion_age, expected):
    now = datetime(2026, 10, 26, 0, 0, tzinfo=UTC)
    completed_at = now - completion_age
    result = incidents._settled_missing_artifact_resolution(
        {
            "status": "evidence_unavailable",
            "diagnostic_complete": False,
            "failure_reason": "incident_artifact_missing",
        },
        {
            "status": "completed",
            "created_at": (completed_at - timedelta(minutes=5)).isoformat(),
            "updated_at": completed_at.isoformat(),
        },
        now,
    )

    if expected is None:
        assert result is None
    else:
        assert result is not None
        assert result["cursor_resolution"] == expected
        assert result["evidence_gap"] == "artifact_missing_after_settle_window"
        assert result["source_completed_at"] == completed_at.isoformat()


def test_missing_artifact_without_trusted_completion_time_keeps_cursor_blocked():
    now = datetime(2026, 10, 26, 0, 0, tzinfo=UTC)
    result = incidents._settled_missing_artifact_resolution(
        {"diagnostic_complete": False, "failure_reason": "incident_artifact_missing"},
        {"status": "completed", "created_at": (now - timedelta(days=1)).isoformat()},
        now,
    )

    assert result is None


@pytest.mark.parametrize(
    "failure_reason",
    [
        "incident_artifact_identity_invalid",
        "incident_artifact_download_deadline_exceeded",
        "source_runs_pagination_incomplete",
    ],
)
def test_only_permanently_missing_artifact_can_advance_with_unknown(failure_reason):
    now = datetime(2026, 10, 26, 0, 0, tzinfo=UTC)
    completed_at = now - timedelta(hours=1)
    result = incidents._settled_missing_artifact_resolution(
        {"diagnostic_complete": False, "failure_reason": failure_reason},
        {
            "status": "completed",
            "created_at": (completed_at - timedelta(minutes=5)).isoformat(),
            "updated_at": completed_at.isoformat(),
        },
        now,
    )

    assert result is None
