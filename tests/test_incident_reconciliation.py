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
import scripts.scheduled_brief_incidents as scheduled_incidents
from scripts.monitor_liveness import GitHubAPIHttpError, LivenessAuditError, _safe_endpoint_class


def _legacy_audit_log(*, run_id=39828958057, status="missing_receipt", trigger="schedule"):
    if trigger == "repository_dispatch":
        created_at = "2026-10-22T22:45:19Z"
        started_at = "2026-10-22T22:46:02Z"
        printed_at = "2026-10-22T22:46:04Z"
    else:
        created_at = "2026-10-22T18:09:59Z"
        started_at = "2026-10-22T18:10:47Z"
        printed_at = "2026-10-22T18:10:50Z"
    ledger_sha = "f" * 40
    result = {
        "status": status,
        "executionStatus": "COMPLETED",
        "dataStatus": "UNHEALTHY" if status == "missing_receipt" else "PASS",
        "completionStatus": "INCOMPLETE" if status == "missing_receipt" else "EXPECTED_SKIP",
        "reason": "scheduled_anchor_claim_missing" if status == "missing_receipt" else "schedule_candidate_not_applicable",
        "reasonCodes": ["scheduled_anchor_claim_missing"] if status == "missing_receipt" else ["schedule_candidate_not_applicable"],
        "ledger_source": "data-release",
        "ledger_commit_sha": ledger_sha,
        "audit_started_at": started_at,
        "trigger_source": trigger,
        "read_only": True,
        "slot": "us_premarket" if status == "missing_receipt" else "",
        "market_date": "2026-10-22" if status == "missing_receipt" else "",
        "anchor": "us:2026-10-22:us_premarket" if status == "missing_receipt" else "",
        "scheduled_slot_at": "2026-10-22T09:00:00-04:00" if status == "missing_receipt" else "",
        "audit_due_at": "2026-10-22T09:45:00-04:00" if status == "missing_receipt" else "",
        "recipient_set_version": "recipients-test" if status == "missing_receipt" else "unknown",
    }
    lines = [
        f"{started_at}   GITHUB_RUN_ID: {run_id}",
    ]
    if trigger == "repository_dispatch":
        lines.extend([
            "2026-10-22T22:45:25Z ##[group]Run python -m src.scheduled_slot_audit --wait-until-due --slot morning",
            "2026-10-22T22:45:25Z env:",
            "2026-10-22T22:45:25Z   AUDIT_SLOT: morning",
            "2026-10-22T22:45:25Z ##[endgroup]",
        ])
    lines.extend([
        f"{started_at} ##[group]Run python -m src.scheduled_slot_audit --ledger receipt-ledger/site/data/event-ledger.json",
        f"{started_at} env:",
        f"{started_at}   RUN_CREATED_AT: {created_at}",
        f"{started_at}   GITHUB_REPOSITORY: owner/repo",
        f"{started_at}   TRIGGER_SOURCE: {trigger}",
        f"{started_at}   AUDIT_STARTED_AT: {started_at}",
        f"{started_at}   LEDGER_COMMIT_SHA: {ledger_sha}",
        f"{started_at} ##[endgroup]",
        f"{printed_at} {json.dumps(result, sort_keys=True)}",
    ])
    return "\n".join(lines).encode("utf-8"), result, created_at, started_at, printed_at, ledger_sha


def test_central_reconciliation_wakes_on_gmail_sync_completion():
    workflow = Path(__file__).parents[1] / ".github" / "workflows" / "incident-reconciliation.yml"
    text = workflow.read_text(encoding="utf-8")
    workflow_run = text.split("  workflow_run:", 1)[1].split("  schedule:", 1)[0]

    assert "Gmail history sync (Supabase)" in workflow_run
    assert "types: [completed]" in workflow_run


@pytest.mark.parametrize(
    ("status", "trigger"),
    [("missing_receipt", "schedule"), ("not_applicable", "schedule"), ("missing_receipt", "repository_dispatch")],
)
def test_verified_legacy_scheduled_audit_log_is_bound_to_run_job_and_ledger(monkeypatch, status, trigger):
    run_id = 39828958057
    sha = "cc40ba0401362f6214b540c70b5e1aa3100d5773"
    raw_log, result, created_at, _started_at, printed_at, ledger_sha = _legacy_audit_log(
        run_id=run_id, status=status, trigger=trigger,
    )
    completed_at = "2026-10-22T22:46:08Z" if trigger == "repository_dispatch" else "2026-10-22T18:10:54Z"
    run = {
        "id": run_id,
        "workflow_id": 367335737,
        "run_attempt": 1,
        "path": ".github/workflows/scheduled-brief-slot-audit.yml",
        "head_branch": "main",
        "head_sha": sha,
        "head_repository": {"full_name": "owner/repo"},
        "event": trigger,
        "created_at": created_at,
        "completed_at": completed_at,
        "status": "completed",
        "conclusion": "success",
    }
    event = incidents._source_event_from_run(
        run, workflow_name="Scheduled brief slot receipt audit", repository="owner/repo",
    )
    job = {
        "id": 119999679309,
        "run_id": run_id,
        "run_attempt": 1,
        "name": "Verify scheduled slot receipt (read-only)",
        "status": "completed",
        "conclusion": "success",
        "steps": [{
            "name": "Audit scheduled slot receipt without dispatch or mutation",
            "status": "completed",
            "conclusion": "success",
        }],
    }

    def request(_api, _repo, _token, method, path, **_kwargs):
        assert method == "GET"
        assert path == f"actions/runs/{run_id}/attempts/1/jobs?per_page=100&page=1"
        return {"total_count": 1, "jobs": [job]}

    monkeypatch.setattr(incidents, "_request_json", request)
    monkeypatch.setattr(incidents, "_open_artifact_url", lambda request, **_kwargs: io.BytesIO(raw_log))
    envelope, job_id, digest = incidents._download_legacy_audit_result_from_job_log(
        run=run, event=event, repository="owner/repo", api_url="https://api.github.com",
        token="test-token", deadline=incidents.time.monotonic() + 30,
    )

    assert envelope["schema_version"] == "scheduled-slot-audit-result-v1"
    assert envelope["run_id"] == str(run_id)
    assert envelope["attempt"] == 1
    assert envelope["workflow_sha"] == sha
    assert envelope["ledger_sha"] == ledger_sha
    assert envelope["audited_at"] == incidents._parse_time(printed_at).isoformat()
    assert envelope["result"]["status"] == result["status"]
    assert envelope["result"]["reason"] == result["reason"]
    assert envelope["report_receipt_status"] == status
    assert envelope["evidence_source"]["kind"] == "verified_legacy_job_log"
    assert envelope["evidence_source"]["job_id"] == job_id == 119999679309
    assert envelope["evidence_source"]["log_sha256"] == digest


def test_legacy_audit_log_fallback_uses_normal_incident_contract(monkeypatch):
    run_id = 39828958057
    sha = "cc40ba0401362f6214b540c70b5e1aa3100d5773"
    raw_log, result, created_at, _started_at, _printed_at, _ledger_sha = _legacy_audit_log(run_id=run_id)
    run = {
        "id": run_id, "workflow_id": 367335737, "run_attempt": 1,
        "path": ".github/workflows/scheduled-brief-slot-audit.yml",
        "head_branch": "main", "head_sha": sha,
        "head_repository": {"full_name": "owner/repo"}, "event": "schedule",
        "created_at": created_at, "completed_at": "2026-10-22T18:10:54Z",
        "status": "completed", "conclusion": "success",
    }
    job = {
        "id": 119999679309, "run_id": run_id, "run_attempt": 1,
        "name": "Verify scheduled slot receipt (read-only)", "status": "completed", "conclusion": "success",
        "steps": [{"name": incidents.LEGACY_AUDIT_STEP_NAME, "status": "completed", "conclusion": "success"}],
    }
    monkeypatch.setattr(
        incidents, "_download_artifact_json",
        lambda **_kwargs: (_ for _ in ()).throw(LivenessAuditError("incident_artifact_missing")),
    )
    monkeypatch.setattr(incidents, "_request_json", lambda *_args, **_kwargs: {"total_count": 1, "jobs": [job]})
    monkeypatch.setattr(incidents, "_open_artifact_url", lambda request, **_kwargs: io.BytesIO(raw_log))
    captured = {}

    def reconcile_brief(*, event, evidence_directory, **_kwargs):
        captured["evidence"] = scheduled_incidents._validated_evidence(event, evidence_directory)
        return {"status": "incident_active", "diagnostic_complete": True}

    monkeypatch.setattr(incidents, "reconcile_scheduled_brief", reconcile_brief)
    source_result = incidents._reconcile_source_run(
        run=run, workflow_name="Scheduled brief slot receipt audit", repository="owner/repo",
        api_url="https://api.github.com", token="test-token",
        now=datetime.fromisoformat("2026-10-22T19:00:00+00:00"),
        deadline=incidents.time.monotonic() + 30,
    )
    assert captured["evidence"]["valid"] is True
    assert captured["evidence"]["result"]["status"] == result["status"]
    assert captured["evidence"]["result"]["reason"] == result["reason"]
    assert source_result["source_evidence_kind"] == "verified_legacy_job_log"
    assert source_result["source_job_id"] == 119999679309


def test_legacy_audit_log_recovery_is_sha_pinned_and_rejects_mismatched_job(monkeypatch):
    run_id = 39828958057
    run = {
        "id": run_id, "workflow_id": 367335737, "run_attempt": 1,
        "path": ".github/workflows/scheduled-brief-slot-audit.yml",
        "head_branch": "main", "head_sha": "a" * 40,
        "head_repository": {"full_name": "owner/repo"}, "event": "schedule",
        "created_at": "2026-10-22T18:09:59Z", "completed_at": "2026-10-22T18:10:54Z",
        "status": "completed", "conclusion": "success",
    }
    event = incidents._source_event_from_run(
        run, workflow_name="Scheduled brief slot receipt audit", repository="owner/repo",
    )
    monkeypatch.setattr(incidents, "_request_json", lambda *_args, **_kwargs: pytest.fail("unknown SHA must not fetch logs"))
    assert incidents._download_legacy_audit_result_from_job_log(
        run=run, event=event, repository="owner/repo", api_url="https://api.github.com",
        token="test-token", deadline=incidents.time.monotonic() + 30,
    ) is None

    raw_log, _result, _created_at, _started_at, _printed_at, _ledger_sha = _legacy_audit_log(run_id=run_id)
    run["head_sha"] = "cc40ba0401362f6214b540c70b5e1aa3100d5773"
    event = incidents._source_event_from_run(
        run, workflow_name="Scheduled brief slot receipt audit", repository="owner/repo",
    )
    job = {
        "id": 119999679309, "run_id": run_id + 1, "run_attempt": 1,
        "name": "Verify scheduled slot receipt (read-only)", "status": "completed", "conclusion": "success",
        "steps": [{"name": incidents.LEGACY_AUDIT_STEP_NAME, "status": "completed", "conclusion": "success"}],
    }
    monkeypatch.setattr(incidents, "_request_json", lambda *_args, **_kwargs: {"total_count": 1, "jobs": [job]})
    monkeypatch.setattr(incidents, "_open_artifact_url", lambda request, **_kwargs: io.BytesIO(raw_log))
    with pytest.raises(LivenessAuditError, match="legacy_audit_job_identity_invalid"):
        incidents._download_legacy_audit_result_from_job_log(
            run=run, event=event, repository="owner/repo", api_url="https://api.github.com",
            token="test-token", deadline=incidents.time.monotonic() + 30,
        )


def test_legacy_audit_recovery_queue_is_pinned_and_migrates_once():
    path = ".github/workflows/scheduled-brief-slot-audit.yml"
    queued = incidents._validated_legacy_audit_recoveries(
        None, workflow_path=path, workflow_id=367335737,
    )
    assert [row["run_id"] for row in queued] == [39828958057, 39834814908, 39867216973]
    assert all(row["state"] == "pending" for row in queued)

    resolved = dict(queued[0])
    resolved.update({
        "state": "reconciled",
        "result_status": "missing_receipt",
        "resolved_at": "2026-10-26T01:00:00+00:00",
        "evidence_kind": "verified_legacy_job_log",
        "job_id": 119999679309,
        "log_sha256": "a" * 64,
    })
    round_tripped = incidents._validated_legacy_audit_recoveries(
        [resolved, *queued[1:]], workflow_path=path, workflow_id=367335737,
    )
    assert round_tripped[0]["state"] == "reconciled"
    with pytest.raises(LivenessAuditError, match="incident_legacy_audit_recovery_identity_invalid"):
        incidents._validated_legacy_audit_recoveries(
            [{**queued[0], "sha": "b" * 40}, *queued[1:]],
            workflow_path=path, workflow_id=367335737,
        )


def test_reconcile_replays_pinned_legacy_audit_runs_after_source_cursor_advanced(monkeypatch, tmp_path):
    audit_path = ".github/workflows/scheduled-brief-slot-audit.yml"
    workflow_ids = {
        ".github/workflows/scheduled-brief.yml": 1,
        audit_path: 367335737,
        ".github/workflows/official-event-monitor.yml": 3,
        ".github/workflows/unified-research-report.yml": 4,
    }
    sha = "cc40ba0401362f6214b540c70b5e1aa3100d5773"
    run_details = {}
    expected_outcomes = {
        39828958057: ("missing_receipt", "schedule"),
        39834814908: ("not_applicable", "schedule"),
        39867216973: ("missing_receipt", "repository_dispatch"),
    }
    for run_id, (status, trigger) in expected_outcomes.items():
        _raw, _result, created_at, _started, printed_at, _ledger = _legacy_audit_log(
            run_id=run_id, status=status, trigger=trigger,
        )
        completed_at = (
            "2026-10-22T22:46:08Z"
            if trigger == "repository_dispatch" else "2026-10-22T18:10:54Z"
        )
        run_details[run_id] = {
            "id": run_id,
            "workflow_id": workflow_ids[audit_path],
            "run_attempt": 1,
            "path": audit_path,
            "head_branch": "main",
            "head_sha": sha,
            "head_repository": {"full_name": "owner/repo"},
            "event": trigger,
            "created_at": created_at,
            "completed_at": completed_at,
            "updated_at": completed_at,
            "status": "completed",
            "conclusion": "success",
        }

    monkeypatch.setattr(incidents, "_load_cursor_state", lambda **_kwargs: {})
    monkeypatch.setattr(
        incidents, "_source_workflow_id",
        lambda *, path, **_kwargs: workflow_ids[path],
    )

    def runs_since(*, path, workflow_id, cursor, **_kwargs):
        return [], {
            "mode": "live",
            "created_at": "2026-10-26T00:00:00+00:00",
            "run_id": 999999,
            "source_evidence_gaps": [],
            "legacy_audit_recoveries": incidents._validated_legacy_audit_recoveries(
                cursor.get("legacy_audit_recoveries"),
                workflow_path=path,
                workflow_id=workflow_id,
            ),
            "pending_runs": [],
            "pending_run_diagnostics": [],
            "scan_complete": True,
        }, False

    monkeypatch.setattr(incidents, "_workflow_runs_since", runs_since)

    def request_json(_api, _repo, _token, _method, path, **_kwargs):
        if path.endswith("/repos/owner/repo"):
            return {"id": 1309835643}
        if path.startswith("actions/runs/"):
            run_id = int(path.rsplit("/", 1)[-1])
            return run_details[run_id]
        pytest.fail(f"unexpected API request: {path}")

    monkeypatch.setattr(incidents, "_request_json", request_json)

    def reconcile_run(*, run, **_kwargs):
        audit_status, _trigger = expected_outcomes[run["id"]]
        return {
            "status": "incident_active" if audit_status == "missing_receipt" else "no_notification",
            "diagnostic_complete": True,
            "incident_active": audit_status == "missing_receipt",
            "evidence_status": audit_status,
            "source_evidence_kind": "verified_legacy_job_log",
            "source_job_id": 120000000000 + run["id"],
            "source_log_sha256": "c" * 64,
        }

    monkeypatch.setattr(incidents, "_reconcile_source_run", reconcile_run)
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(tmp_path / "event.json"))
    (tmp_path / "event.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_run")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_API_URL", "https://api.github.com")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_RUN_ID", "999999")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_SHA", "d" * 40)
    monkeypatch.setenv("GITHUB_OUTPUT", "")

    result = incidents.reconcile(
        result_path=tmp_path / "result.json", evidence_directory=tmp_path / "evidence",
    )

    assert {row["source_run_id"] for row in result["results"]} == set(expected_outcomes)
    assert result["coverage_status"] == "complete"
    assert result["diagnostic_complete"] is True
    assert result["business_status"] == "degraded"
    assert result["legacy_audit_recovery_pending"] == []
    stored = result["source_cursors"][audit_path]["legacy_audit_recoveries"]
    assert {row["state"] for row in stored} == {"reconciled"}
    assert {row["result_status"] for row in stored} == {"missing_receipt", "not_applicable"}


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
    assert cursor["pending_runs"][0] == {
        "run_id": 10, "workflow_id": workflow_id,
        "created_at": "2026-10-24T03:50:00+00:00", "attempt": 1,
        "head_sha": "a" * 40,
        "terminal_jobs_check": {
            "status": "unverified",
            "reason": "workflow_contract_unknown_for_fixed_sha",
            "workflow_sha": "a" * 40,
        },
    }
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


def test_newly_discovered_stale_run_is_probed_and_fixed_after_second_stable_read(monkeypatch):
    workflow_id = 320209983
    run_id = 39698088993
    sha = "cc40ba0401362f6214b540c70b5e1aa3100d5773"
    run = {
        "id": run_id,
        "workflow_id": workflow_id,
        "run_attempt": 1,
        "created_at": "2026-10-22T00:10:37Z",
        "updated_at": "2026-10-22T00:10:48Z",
        "status": "in_progress",
        "head_branch": "main",
        "head_sha": sha,
        "head_repository": {"full_name": "owner/repo"},
    }
    # De-identified capture of the official Jobs API response. GitHub's job
    # objects include runner/steps fields in production, but the contract uses
    # only stable identity and terminal fields.
    jobs = [
        {
            "id": 119560307175, "run_id": run_id, "run_attempt": 1,
            "name": "monitor-admission", "status": "completed", "conclusion": "success",
            "started_at": "2026-10-22T00:10:39Z", "completed_at": "2026-10-22T00:10:44Z",
        },
        {
            "id": 119560351562, "run_id": run_id, "run_attempt": 1,
            "name": "monitor-send-deploy", "status": "completed", "conclusion": "success",
            "started_at": "2026-10-22T00:10:48Z", "completed_at": "2026-10-22T00:14:51Z",
        },
    ]
    now = datetime(2026, 10, 25, 20, 0, tzinfo=UTC)

    def call(cursor, observed_at):
        def request(_api, _repo, _token, _method, path, *, response_headers=None, deadline_monotonic=None):
            if path.startswith(f"actions/workflows/{workflow_id}/runs?"):
                return {"total_count": 1, "workflow_runs": [dict(run)]}
            if path.startswith(f"actions/runs/{run_id}/attempts/1/jobs?"):
                return {"total_count": 2, "jobs": list(jobs)}
            if path == f"actions/runs/{run_id}":
                return dict(run)
            raise AssertionError(f"Unexpected GitHub API path: {path}")

        monkeypatch.setattr(incidents, "_request_json", request)
        return incidents._workflow_runs_since(
            path=".github/workflows/official-event-monitor.yml",
            workflow_id=workflow_id, repository="owner/repo", api_url="https://api.github.com",
            token="test-token", cursor=cursor, now=observed_at,
            deadline=incidents.time.monotonic() + 30, repository_id=1309835643,
        )

    first_rows, first_cursor, first_held = call({
        "mode": "backfill",
        "window_start": "2026-10-22T00:00:00+00:00",
        "window_end": "2026-10-22T05:59:59+00:00",
        "created_at": "2026-10-22T00:00:00+00:00",
        "run_id": 0,
        "pending_runs": [],
    }, now)
    assert first_rows == []
    assert first_held is True
    first_pending = first_cursor["pending_runs"][0]
    assert first_pending["terminal_jobs_check"]["status"] == "awaiting_confirmation"
    assert first_pending["terminal_jobs_check"]["jobs"][1]["name"] == "monitor-send-deploy"

    second_rows, second_cursor, second_held = call(first_cursor, now + timedelta(seconds=3))
    assert len(second_rows) == 1
    assert second_rows[0]["_incident_source_terminal_evidence"]["resolution"] == "stable_complete_jobs_snapshot"
    assert second_cursor["pending_runs"][0]["terminal_jobs_check"]["status"] == "confirmed_complete"
    assert second_held is True


def test_terminal_job_observation_from_another_attempt_cannot_confirm_current_attempt(monkeypatch):
    run_id = 39698088993
    sha = "cc40ba0401362f6214b540c70b5e1aa3100d5773"
    now = datetime(2026, 10, 25, 20, 0, tzinfo=UTC)
    snapshot = {
        "fingerprint": "b" * 64,
        "job_ids": [1, 2],
        "job_names": ["monitor-admission", "monitor-send-deploy"],
        "jobs": [
            {"completed_at": "2026-10-22T00:10:44+00:00"},
            {"completed_at": "2026-10-22T00:14:51+00:00"},
        ],
        "all_completed": True,
    }
    monkeypatch.setattr(incidents, "_read_source_job_snapshot", lambda **_kwargs: snapshot)

    observation, evidence, check = incidents._observe_terminal_jobs(
        run={
            "id": run_id,
            "workflow_id": 320209983,
            "run_attempt": 2,
            "created_at": "2026-10-22T00:10:37Z",
            "status": "in_progress",
            "head_sha": sha,
        },
        path=".github/workflows/official-event-monitor.yml",
        repository="owner/repo",
        repository_id=1309835643,
        api_url="https://api.github.com",
        token="test-token",
        deadline=incidents.time.monotonic() + 30,
        now=now,
        previous={
            "run_id": run_id,
            "attempt": 1,
            "fingerprint": snapshot["fingerprint"],
            "observed_at": (now - timedelta(seconds=3)).isoformat(),
        },
    )

    assert observation == {
        "run_id": run_id,
        "attempt": 2,
        "fingerprint": snapshot["fingerprint"],
        "observed_at": now.isoformat(),
    }
    assert evidence is None
    assert check["status"] == "awaiting_confirmation"


def test_stale_job_probe_404_is_durable_and_reports_safe_endpoint(monkeypatch):
    workflow_id = 320209983
    run_id = 39698088993
    run = {
        "id": run_id, "workflow_id": workflow_id, "run_attempt": 1,
        "created_at": "2026-10-22T00:10:37Z", "status": "in_progress",
        "head_branch": "main", "head_sha": "cc40ba0401362f6214b540c70b5e1aa3100d5773",
        "head_repository": {"full_name": "owner/repo"},
    }

    def request(_api, _repo, _token, _method, path, *, response_headers=None, deadline_monotonic=None):
        if path == f"actions/runs/{run_id}":
            return dict(run)
        if path.startswith(f"actions/runs/{run_id}/attempts/1/jobs?"):
            raise GitHubAPIHttpError(
                status_code=404, method="GET",
                endpoint_class="actions/runs/{run_id}/attempts/{attempt}/jobs",
                request_id="SAFE:123", retry_count=3,
            )
        if path.startswith(f"actions/workflows/{workflow_id}/runs?"):
            return {"total_count": 0, "workflow_runs": []}
        raise AssertionError(f"Unexpected GitHub API path: {path}")

    monkeypatch.setattr(incidents, "_request_json", request)
    _rows, cursor, held = incidents._workflow_runs_since(
        path=".github/workflows/official-event-monitor.yml",
        workflow_id=workflow_id, repository="owner/repo", api_url="https://api.github.com",
        token="test-token", cursor={
            "mode": "live", "created_at": "2026-10-22T00:00:00+00:00", "run_id": 0,
            "pending_runs": [{
                "run_id": run_id, "workflow_id": workflow_id,
                "created_at": "2026-10-22T00:10:37+00:00", "attempt": 1,
                "head_sha": run["head_sha"],
            }],
        }, now=datetime(2026, 10, 25, 20, 0, tzinfo=UTC),
        deadline=incidents.time.monotonic() + 30, repository_id=1309835643,
    )

    check = cursor["pending_runs"][0]["terminal_jobs_check"]
    assert held is True
    assert check["status"] == "unavailable"
    assert check["failure_evidence"]["endpoint_class"] == "actions/runs/{run_id}/attempts/{attempt}/jobs"
    assert check["failure_evidence"]["http_status"] == 404


def test_attempt_jobs_endpoint_class_is_safe_and_identifiable():
    assert _safe_endpoint_class(
        "https://api.github.com/repos/owner/repo/actions/runs/39698088993/attempts/1/jobs",
        api_url="https://api.github.com", repository="owner/repo",
    ) == "actions/runs/{run_id}/attempts/{attempt}/jobs"


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


def test_reconcile_completes_diagnostics_for_settled_pre_scan_gap_and_keeps_gap_degraded(monkeypatch, tmp_path):
    target_path = ".github/workflows/official-event-monitor.yml"
    workflow_ids = {
        target_path: 320209983,
        ".github/workflows/scheduled-brief.yml": 10,
        ".github/workflows/scheduled-brief-slot-audit.yml": 367335737,
        ".github/workflows/unified-research-report.yml": 12,
    }
    now = datetime.now(UTC).replace(microsecond=0)
    stuck_id = 39793445128
    stuck_sha = "cc40ba0401362f6214b540c70b5e1aa3100d5773"
    stuck_created = now - timedelta(minutes=55)
    terminal_at = now - timedelta(minutes=36)
    trace_at = now - timedelta(minutes=35)
    stuck_run = {
        "id": stuck_id, "workflow_id": workflow_ids[target_path], "run_attempt": 1,
        "created_at": stuck_created.isoformat().replace("+00:00", "Z"),
        "updated_at": terminal_at.isoformat().replace("+00:00", "Z"),
        "status": "in_progress", "head_branch": "main", "head_sha": stuck_sha,
        "head_repository": {"full_name": "owner/repo"},
    }
    jobs = [
        {
            "id": 119560307175, "name": "monitor-admission", "run_id": stuck_id,
            "run_attempt": 1, "status": "completed", "conclusion": "success",
            "started_at": (stuck_created + timedelta(seconds=2)).isoformat().replace("+00:00", "Z"),
            "completed_at": (stuck_created + timedelta(seconds=7)).isoformat().replace("+00:00", "Z"),
        },
        {
            "id": 119560351562, "name": "monitor-send-deploy", "run_id": stuck_id,
            "run_attempt": 1, "status": "completed", "conclusion": "cancelled",
            "started_at": (stuck_created + timedelta(seconds=11)).isoformat().replace("+00:00", "Z"),
            "completed_at": terminal_at.isoformat().replace("+00:00", "Z"),
        },
    ]
    later_id = 40249999999
    later_created = now - timedelta(minutes=25)
    later_sha = "b" * 40
    later_run = {
        "id": later_id, "workflow_id": workflow_ids[target_path], "run_attempt": 1,
        "created_at": later_created.isoformat().replace("+00:00", "Z"),
        "updated_at": (later_created + timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
        "status": "completed", "conclusion": "success", "head_branch": "main",
        "head_sha": later_sha, "head_repository": {"full_name": "owner/repo"},
    }

    def fake_request(_api, _repo, _token, _method, request_path, *, response_headers=None, deadline_monotonic=None):
        if request_path == "https://api.github.com/repos/owner/repo":
            return {"id": 1309835643}
        if request_path == f"actions/runs/{stuck_id}":
            return dict(stuck_run)
        if request_path == f"actions/runs/{stuck_id}/attempts/1/jobs?per_page=100&page=1":
            return {"total_count": len(jobs), "jobs": list(jobs)}
        if request_path.startswith("actions/workflows/") and "/runs?" in request_path:
            workflow_id = int(request_path.split("actions/workflows/", 1)[1].split("/", 1)[0])
            rows = [dict(later_run), dict(stuck_run)] if workflow_id == workflow_ids[target_path] else []
            return {"total_count": len(rows), "workflow_runs": rows}
        raise AssertionError(f"Unexpected GitHub API path: {request_path}")

    monkeypatch.setattr(incidents, "_request_json", fake_request)
    snapshot = incidents._read_source_job_snapshot(
        run=stuck_run, repository="owner/repo", repository_id=1309835643,
        api_url="https://api.github.com", token="test-token",
        deadline=incidents.time.monotonic() + 30,
        expected_jobs=incidents.SOURCE_TERMINAL_JOB_CONTRACTS[(
            target_path, stuck_sha,
        )]["jobs"],
    )
    stuck_observation = {
        "run_id": stuck_id, "attempt": 1, "fingerprint": snapshot["fingerprint"],
        "observed_at": (now - timedelta(seconds=5)).isoformat(),
    }
    cursor_state = {
        target_path: {
            "mode": "live", "created_at": (now - timedelta(hours=1)).isoformat(), "run_id": 0,
            "pending_runs": [{
                "run_id": stuck_id, "workflow_id": workflow_ids[target_path],
                "created_at": stuck_created.isoformat(), "attempt": 1, "head_sha": stuck_sha,
                "terminal_jobs_observation": stuck_observation,
            }],
        },
    }
    audit_path = ".github/workflows/scheduled-brief-slot-audit.yml"
    cursor_state[audit_path] = {
        "mode": "live", "created_at": (now - timedelta(hours=1)).isoformat(), "run_id": 0,
        "legacy_audit_recoveries": [
            {
                "schema_version": incidents.LEGACY_AUDIT_RECOVERY_SCHEMA,
                "run_id": run_id,
                "attempt": expected["attempt"],
                "sha": expected["sha"],
                "state": "reconciled",
                "result_status": "missing_receipt",
                "resolved_at": now.isoformat(),
                "evidence_kind": "verified_legacy_job_log",
                "job_id": 120000000000 + run_id,
                "log_sha256": "e" * 64,
            }
            for run_id, expected in incidents.LEGACY_AUDIT_LOG_RECOVERY_RUNS.items()
        ],
    }
    monkeypatch.setattr(
        incidents, "_load_cursor_state",
        lambda **_kwargs: json.loads(json.dumps(cursor_state)),
    )
    monkeypatch.setattr(
        incidents, "_source_workflow_id",
        lambda *, path, **_kwargs: workflow_ids[path],
    )
    skipped_trace = {
        "events": [], "recorded_at": trace_at.isoformat(), "run_attempt": "1",
        "schema_version": "official-event-trace-v1", "workflow_run_id": str(stuck_id),
        "workflow_sha": stuck_sha,
        "stages": {
            "batch_failed_event_count": "0", "batch_partial_event_count": "0",
            "candidate_incident_count": "0", "durable_receipt": "false",
            "notification_expected": "false", "notification_reason": "not_attempted",
            "prepare": "not_required", "public_gate": "false", "queue": "not_required",
            "receipt_callback": "skipped", "scan": "skipped", "sender": "skipped",
        },
    }
    completed_trace = {
        "events": [], "recorded_at": now.isoformat(), "run_attempt": "1",
        "schema_version": "official-event-trace-v1", "workflow_run_id": str(later_id),
        "workflow_sha": later_sha,
        "stages": {
            "batch_failed_event_count": "0", "batch_partial_event_count": "0",
            "candidate_incident_count": "0", "durable_receipt": "false",
            "notification_expected": "false", "notification_reason": "no_event",
            "prepare": "not_required", "public_gate": "false", "queue": "not_required",
            "receipt_callback": "skipped", "scan": "success", "sender": "skipped",
        },
    }

    def artifact_bytes(*, run, **_kwargs):
        trace = skipped_trace if _safe_run_id(run) == stuck_id else completed_trace
        return json.dumps(trace, sort_keys=True).encode("utf-8")

    def reconcile_trace(*, trace_path, **_kwargs):
        trace = json.loads(Path(trace_path).read_text(encoding="utf-8"))
        if trace["workflow_run_id"] == str(stuck_id):
            return {"status": "evidence_unavailable", "diagnostic_complete": False, "incident_active": False}
        return {"status": "no_notification", "diagnostic_complete": True, "incident_active": False}

    def _safe_run_id(run):
        return int(run["id"])

    monkeypatch.setattr(incidents, "_download_artifact_json", artifact_bytes)
    monkeypatch.setattr(incidents, "reconcile_official_events", reconcile_trace)
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

    result = incidents.reconcile(
        result_path=tmp_path / "result.json", evidence_directory=tmp_path / "evidence",
    )
    resolved = next(row for row in result["results"] if row.get("source_run_id") == stuck_id)
    later = next(row for row in result["results"] if row.get("source_run_id") == later_id)
    assert resolved["failure_reason"] == "official_scan_never_started"
    assert resolved["diagnostic_complete"] is True
    assert resolved["cursor_resolution"] == "advance_with_unknown"
    assert later["diagnostic_complete"] is True
    assert result["business_status"] == "degraded"
    assert result["source_evidence_gaps"][0]["run_id"] == stuck_id
    assert result["source_scan_holds"] == [target_path]
    assert result["coverage_status"] == "incomplete"
    assert result["diagnostic_complete"] is False
    assert result["incident_handoff_status"] == "incomplete"
    cursor_state.update(result["source_cursors"])

    following = incidents.reconcile(
        result_path=tmp_path / "result.json", evidence_directory=tmp_path / "evidence",
    )
    assert following["source_evidence_gaps"] == result["source_evidence_gaps"]
    assert following["coverage_status"] == "complete"
    assert following["diagnostic_complete"] is True
    assert following["business_status"] == "degraded"
    assert following["incident_handoff_status"] == "accepted"


def test_reconcile_preserves_terminal_job_observation_when_source_failure_rolls_back_cursor(monkeypatch, tmp_path):
    target_path = ".github/workflows/official-event-monitor.yml"
    workflow_ids = {
        target_path: 320209983,
        ".github/workflows/scheduled-brief.yml": 10,
        ".github/workflows/scheduled-brief-slot-audit.yml": 11,
        ".github/workflows/unified-research-report.yml": 12,
    }
    now = datetime.now(UTC).replace(microsecond=0)
    pending_id = 39698088993
    pending_sha = "cc40ba0401362f6214b540c70b5e1aa3100d5773"
    pending_created = now - timedelta(minutes=20)
    run = {
        "id": pending_id,
        "workflow_id": workflow_ids[target_path],
        "run_attempt": 1,
        "created_at": pending_created.isoformat().replace("+00:00", "Z"),
        "updated_at": (now - timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
        "status": "in_progress",
        "head_branch": "main",
        "head_sha": pending_sha,
        "head_repository": {"full_name": "owner/repo"},
    }
    jobs = [
        {
            "id": 119560307175,
            "name": "monitor-admission",
            "run_id": pending_id,
            "run_attempt": 1,
            "status": "completed",
            "conclusion": "success",
            "started_at": (now - timedelta(minutes=11)).isoformat().replace("+00:00", "Z"),
            "completed_at": (now - timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
        },
        {
            "id": 119560351562,
            "name": "monitor-send-deploy",
            "run_id": pending_id,
            "run_attempt": 1,
            "status": "completed",
            "conclusion": "success",
            "started_at": (now - timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
            "completed_at": (now - timedelta(minutes=9)).isoformat().replace("+00:00", "Z"),
        },
    ]
    unrelated_run = {
        "id": 40249999999,
        "workflow_id": workflow_ids[target_path],
        "run_attempt": 1,
        "created_at": (now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
        "head_branch": "main",
        "head_sha": "a" * 40,
        "head_repository": {"full_name": "owner/repo"},
        "status": "completed",
        "conclusion": "failure",
    }
    cursor_state = {
        target_path: {
            "mode": "live",
            "created_at": (now - timedelta(minutes=25)).isoformat(),
            "run_id": 0,
            "pending_runs": [{
                "run_id": pending_id,
                "workflow_id": workflow_ids[target_path],
                "created_at": pending_created.isoformat(),
                "attempt": 1,
                "head_sha": pending_sha,
            }],
        },
    }
    monkeypatch.setattr(
        incidents,
        "_load_cursor_state",
        lambda **_kwargs: json.loads(json.dumps(cursor_state)),
    )
    monkeypatch.setattr(incidents, "_source_workflow_id", lambda *, path, **_kwargs: workflow_ids[path])

    def fake_request(_api, _repo, _token, _method, request_path, *, response_headers=None, deadline_monotonic=None):
        if request_path == "https://api.github.com/repos/owner/repo":
            return {"id": 1309835643}
        if request_path == f"actions/runs/{pending_id}":
            return dict(run)
        if request_path == f"actions/runs/{pending_id}/attempts/1/jobs?per_page=100&page=1":
            return {"total_count": len(jobs), "jobs": list(jobs)}
        if request_path.startswith(f"actions/workflows/{workflow_ids[target_path]}/runs?"):
            return {"total_count": 1, "workflow_runs": [dict(unrelated_run)]}
        if request_path.startswith("actions/workflows/") and "/runs?" in request_path:
            return {"total_count": 0, "workflow_runs": []}
        raise AssertionError(f"Unexpected GitHub API path: {request_path}")

    monkeypatch.setattr(incidents, "_request_json", fake_request)

    def missing_artifact(**_kwargs):
        raise LivenessAuditError("incident_artifact_missing")

    monkeypatch.setattr(incidents, "_download_artifact_json", missing_artifact)
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

    result = incidents.reconcile(
        result_path=tmp_path / "result.json",
        evidence_directory=tmp_path / "evidence",
    )

    cursor = result["source_cursors"][target_path]
    pending = next(item for item in cursor["pending_runs"] if item["run_id"] == pending_id)
    assert pending["terminal_jobs_observation"]["fingerprint"] == cursor["pending_run_diagnostics"][0]["fingerprint"]
    assert pending["terminal_jobs_observation"]["observed_at"]
    assert cursor["pending_run_diagnostics"][0]["status"] == "awaiting_confirmation"
    assert result["failure_reason"] == "source_pending_terminal_state_unverified"


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


def test_main_preserves_safe_unexpected_exception_stage_in_result(tmp_path, monkeypatch):
    result_path = tmp_path / "incident-reconciliation.json"

    def fail_reconcile(*, result_path, evidence_directory):
        raise RuntimeError("response body must not be copied to evidence")

    monkeypatch.setattr(incidents, "reconcile", fail_reconcile)
    monkeypatch.setattr(incidents.sys, "argv", ["scripts.incident_reconciliation"])
    monkeypatch.setenv("INCIDENT_RECONCILIATION_RESULT_PATH", str(result_path))
    monkeypatch.setenv("INCIDENT_EVIDENCE_DIR", str(tmp_path / "evidence"))
    monkeypatch.setenv("GITHUB_RUN_ID", "40183001117")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)

    assert incidents.main() == 1
    saved = json.loads(result_path.read_text(encoding="utf-8"))
    assert saved["failure_reason"] == "incident_reconciliation_unexpected_RuntimeError"
    assert saved["failure_stage"] == "reconcile"
    assert "response body" not in json.dumps(saved)


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
    ("completion_age", "expected"),
    [
        (timedelta(minutes=29, seconds=59), None),
        (timedelta(minutes=30), "advance_with_unknown"),
    ],
)
def test_terminal_job_evidence_settles_missing_artifact_for_stuck_run(completion_age, expected):
    now = datetime(2026, 10, 26, 0, 0, tzinfo=UTC)
    completed_at = now - completion_age
    sha = "a" * 40
    result = incidents._settled_missing_artifact_resolution(
        {
            "status": "evidence_unavailable",
            "diagnostic_complete": False,
            "failure_reason": "incident_artifact_missing",
        },
        {
            "id": 39698088993,
            "run_attempt": 1,
            "head_sha": sha,
            "status": "in_progress",
            "created_at": (completed_at - timedelta(minutes=5)).isoformat(),
            "_incident_source_terminal_evidence": {
                "schema_version": "source-run-terminal-jobs-v1",
                "resolution": "stable_complete_jobs_snapshot",
                "run_id": 39698088993,
                "attempt": 1,
                "workflow_sha": sha,
                "job_fingerprint": "b" * 64,
                "terminal_jobs_completed_at": completed_at.isoformat(),
            },
        },
        now,
    )

    if expected is None:
        assert result is None
    else:
        assert result is not None
        assert result["cursor_resolution"] == expected
        assert result["source_completed_at"] == completed_at.isoformat()


def test_terminal_job_evidence_cannot_settle_another_attempt_or_sha():
    now = datetime(2026, 10, 26, 0, 0, tzinfo=UTC)
    completed_at = now - timedelta(hours=1)
    sha = "a" * 40
    run = {
        "id": 39698088993,
        "run_attempt": 2,
        "head_sha": sha,
        "status": "in_progress",
        "created_at": (completed_at - timedelta(minutes=5)).isoformat(),
        "_incident_source_terminal_evidence": {
            "schema_version": "source-run-terminal-jobs-v1",
            "resolution": "stable_complete_jobs_snapshot",
            "run_id": 39698088993,
            "attempt": 1,
            "workflow_sha": sha,
            "job_fingerprint": "b" * 64,
            "terminal_jobs_completed_at": completed_at.isoformat(),
        },
    }

    result = incidents._settled_missing_artifact_resolution(
        {"diagnostic_complete": False, "failure_reason": "incident_artifact_missing"},
        run,
        now,
    )

    assert result is None


def test_pre_scan_trace_resolution_requires_exact_bound_trace_and_terminal_cancellation():
    now = datetime(2026, 10, 26, 0, 0, tzinfo=UTC)
    run_id = 39793445128
    attempt = 1
    workflow_id = 320209983
    sha = "cc40ba0401362f6214b540c70b5e1aa3100d5773"
    created_at = now - timedelta(hours=1)
    terminal_at = now - timedelta(minutes=31)
    trace_at = now - timedelta(minutes=30, seconds=30)
    raw_trace = json.dumps({
        "events": [], "recorded_at": trace_at.isoformat(), "run_attempt": str(attempt),
        "schema_version": "official-event-trace-v1", "workflow_run_id": str(run_id),
        "workflow_sha": sha,
        "stages": {
            "batch_failed_event_count": "0", "batch_partial_event_count": "0",
            "candidate_incident_count": "0", "durable_receipt": "false",
            "candidate_incident_reason": "", "notification_expected": "false",
            "notification_reason": "not_attempted", "prepare": "not_required",
            "public_gate": "false", "queue": "not_required", "receipt_callback": "skipped",
            "scan": "skipped", "sender": "skipped",
        },
    }, sort_keys=True).encode("utf-8")
    run = {
        "id": run_id, "workflow_id": workflow_id, "run_attempt": attempt,
        "created_at": created_at.isoformat(), "status": "in_progress", "head_sha": sha,
    }
    job_rows = [
        {"id": 100, "name": "monitor-admission", "status": "completed", "conclusion": "success"},
        {"id": 101, "name": "monitor-send-deploy", "status": "completed", "conclusion": "cancelled"},
    ]
    terminal = {
        "schema_version": "source-run-terminal-jobs-v1",
        "resolution": "stable_complete_jobs_snapshot",
        "workflow_contract": "official-event-monitor-cc40ba0-jobs-v1",
        "workflow_sha": sha, "run_id": run_id, "attempt": attempt,
        "job_fingerprint": "a" * 64,
        "jobs": job_rows,
        "terminal_jobs_completed_at": terminal_at.isoformat(),
    }
    proof = incidents._pre_scan_trace_evidence(
        content=raw_trace, run=run,
        workflow_path=".github/workflows/official-event-monitor.yml",
    )
    assert proof is not None
    trace_payload = json.loads(raw_trace)
    trace_payload["stages"]["scan"] = "success"
    assert incidents._pre_scan_trace_evidence(
        content=json.dumps(trace_payload).encode("utf-8"), run=run,
        workflow_path=".github/workflows/official-event-monitor.yml",
    ) is None
    trace_payload = json.loads(raw_trace)
    trace_payload["events"] = [{"event_ref": "unexpected"}]
    assert incidents._pre_scan_trace_evidence(
        content=json.dumps(trace_payload).encode("utf-8"), run=run,
        workflow_path=".github/workflows/official-event-monitor.yml",
    ) is None
    assert incidents._settled_pre_scan_gap_resolution(
        {"diagnostic_complete": False, "pre_scan_trace_evidence": proof},
        {**run, "_incident_source_terminal_evidence": terminal}, now,
    ) is not None
    boundary_proof = dict(
        proof,
        trace_recorded_at=(now - incidents.MISSING_ARTIFACT_SETTLE_WINDOW).isoformat(),
    )
    assert incidents._settled_pre_scan_gap_resolution(
        {"diagnostic_complete": False, "pre_scan_trace_evidence": boundary_proof},
        {**run, "_incident_source_terminal_evidence": terminal}, now,
    ) is not None
    too_recent_proof = dict(
        proof,
        trace_recorded_at=(now - incidents.MISSING_ARTIFACT_SETTLE_WINDOW + timedelta(seconds=1)).isoformat(),
    )
    assert incidents._settled_pre_scan_gap_resolution(
        {"diagnostic_complete": False, "pre_scan_trace_evidence": too_recent_proof},
        {**run, "_incident_source_terminal_evidence": terminal}, now,
    ) is None

    wrong_attempt = dict(proof, attempt=2)
    assert incidents._settled_pre_scan_gap_resolution(
        {"diagnostic_complete": False, "pre_scan_trace_evidence": wrong_attempt},
        {**run, "_incident_source_terminal_evidence": terminal}, now,
    ) is None
    wrong_sha = dict(terminal, workflow_sha="b" * 40)
    assert incidents._settled_pre_scan_gap_resolution(
        {"diagnostic_complete": False, "pre_scan_trace_evidence": proof},
        {**run, "_incident_source_terminal_evidence": wrong_sha}, now,
    ) is None
    wrong_attempt_evidence = dict(terminal, attempt=2)
    assert incidents._settled_pre_scan_gap_resolution(
        {"diagnostic_complete": False, "pre_scan_trace_evidence": proof},
        {**run, "_incident_source_terminal_evidence": wrong_attempt_evidence}, now,
    ) is None
    still_running = dict(terminal, jobs=[job_rows[0], dict(job_rows[1], conclusion="success")])
    assert incidents._settled_pre_scan_gap_resolution(
        {"diagnostic_complete": False, "pre_scan_trace_evidence": proof},
        {**run, "_incident_source_terminal_evidence": still_running}, now,
    ) is None
    before_settle = dict(proof, trace_recorded_at=(now - timedelta(minutes=5)).isoformat())
    assert incidents._settled_pre_scan_gap_resolution(
        {"diagnostic_complete": False, "pre_scan_trace_evidence": before_settle},
        {**run, "_incident_source_terminal_evidence": terminal}, now,
    ) is None


def test_source_evidence_gap_cursor_rejects_identity_conflicts_and_preserves_valid_gap():
    gap = {
        "schema_version": "incident-source-evidence-gap-v1",
        "workflow_path": ".github/workflows/official-event-monitor.yml",
        "workflow_id": 320209983,
        "run_id": 39793445128,
        "attempt": 1,
        "sha": "cc40ba0401362f6214b540c70b5e1aa3100d5773",
        "reason": "official_scan_never_started",
        "source_created_at": "2026-10-25T22:00:00+00:00",
        "source_terminal_at": "2026-10-25T22:30:00+00:00",
        "trace_recorded_at": "2026-10-25T22:30:00+00:00",
        "trace_sha256": "a" * 64,
        "settled_at": "2026-10-25T23:00:00+00:00",
        "recorded_at": "2026-10-25T23:01:00+00:00",
    }
    validated = incidents._validated_source_evidence_gaps(
        [gap], workflow_path=".github/workflows/official-event-monitor.yml",
        workflow_id=320209983,
    )
    assert validated == [gap]
    with pytest.raises(LivenessAuditError, match="source_evidence_gap_identity_invalid"):
        incidents._validated_source_evidence_gaps(
            [dict(gap, workflow_id=99)],
            workflow_path=".github/workflows/official-event-monitor.yml",
            workflow_id=320209983,
        )
    with pytest.raises(LivenessAuditError, match="source_evidence_gap_duplicated"):
        incidents._validated_source_evidence_gaps(
            [gap, gap], workflow_path=".github/workflows/official-event-monitor.yml",
            workflow_id=320209983,
        )


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
