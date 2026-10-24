import json
from datetime import datetime

import pytest

from scripts import scheduled_brief_incidents as incidents
from scripts.monitor_liveness import LivenessAuditError


def _event(*, run_id: str, attempt: int, sha: str, workflow: str) -> dict[str, str]:
    return {
        "repository": "hanjhou2000716/prstklab-stk-detector",
        "head_repository": "hanjhou2000716/prstklab-stk-detector",
        "workflow_name": workflow,
        "head_branch": "main",
        "run_id": run_id,
        "attempt": str(attempt),
        "head_sha": sha,
    }


def test_report_failure_and_audit_root_cause_merge_into_same_issue(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    monkeypatch.delenv("GITHUB_RUN_ATTEMPT", raising=False)
    report_dir = tmp_path / "report"
    audit_dir = tmp_path / "audit"
    report_dir.mkdir()
    audit_dir.mkdir()
    reason = "immutable_alert_artifact_identity_conflict"
    report = {
        "schema_version": "notification-terminal-v2",
        "run_id": "100",
        "run_attempt": 1,
        "workflow_sha": "a" * 40,
        "slot": "post_close",
        "scheduled_for_at": "2026-10-21T13:20:00+08:00",
        "expected": True,
        "status": "failed",
        "reason": "scheduled_notification_failed",
        "failure": True,
        "release_evidence": {
            "build": {
                "status": "failed", "evidence_status": "verified",
                "first_failure_reason": reason,
            },
        },
    }
    (report_dir / "scheduled-terminal-100-attempt-1.json").write_text(json.dumps(report), encoding="utf-8")
    audit = {
        "schema_version": "scheduled-slot-audit-result-v1",
        "run_id": "200",
        "attempt": 2,
        "workflow_sha": "b" * 40,
        "original_slot": {
            "slot": "post_close", "date": "2026-10-21",
            "anchor": "taiwan:2026-10-21:post_close",
        },
        "audited_at": "2026-10-21T07:05:00Z",
        "report_receipt_status": "missing_receipt",
        "diagnostic_complete": True,
        "first_failure_reason": "scheduled_anchor_claim_missing",
        "result": {
            "status": "missing_receipt",
            "reason": "scheduled_anchor_claim_missing",
            "slot": "post_close",
            "market_date": "2026-10-21",
            "anchor": "taiwan:2026-10-21:post_close",
            "run_diagnosis": {
                "terminal_reason": "scheduled_notification_failed",
                "terminal_schema_version": "notification-terminal-v2",
                "release_evidence": {
                    "build": {
                        "status": "failed", "evidence_status": "verified",
                        "first_failure_reason": reason,
                    },
                },
            },
        },
    }
    (audit_dir / "scheduled-slot-audit-200-2.json").write_text(json.dumps(audit), encoding="utf-8")

    issue_rows: list[dict[str, object]] = []
    requests: list[tuple[str, str, dict[str, object] | None]] = []

    def open_issues(*_args, **_kwargs):
        return list(issue_rows)

    def request_json(_api, _repo, _token, method, path, payload=None, **_kwargs):
        requests.append((method, path, payload))
        if method == "POST" and path == "issues":
            issue = {"number": 17, "title": payload["title"], "body": payload["body"]}
            issue_rows.append(issue)
            return {"number": 17}
        if method == "PATCH" and path == "issues/17":
            issue_rows[0]["body"] = payload["body"]
        return {}

    monkeypatch.setattr(incidents, "_open_incidents", open_issues)
    monkeypatch.setattr(incidents, "_request_json", request_json)
    repository = "hanjhou2000716/prstklab-stk-detector"
    now = datetime.fromisoformat("2026-10-21T08:00:00Z")

    first = incidents.reconcile(
        event=_event(run_id="100", attempt=1, sha="a" * 40, workflow="Scheduled market brief"),
        evidence_directory=report_dir, repository=repository,
        api_url="https://api.github.com", token="token", now=now,
        defer_notification_cadence=True,
    )
    second = incidents.reconcile(
        event=_event(run_id="200", attempt=2, sha="b" * 40, workflow="Scheduled brief slot receipt audit"),
        evidence_directory=audit_dir, repository=repository,
        api_url="https://api.github.com", token="token", now=now,
        defer_notification_cadence=True,
    )

    assert first["opened_issue_numbers"] == [17]
    assert second["opened_issue_numbers"] == []
    assert first["notification_cadence_confirmations"] == [{
        "issue_number": 17,
        "marker": f"{incidents.ISSUE_MARKER}{incidents._incident_key('scheduled_market_brief', reason, 'notification-terminal-v2')}",
        "next_reminder_at": "2026-10-21T08:30:00+00:00",
    }]
    assert second["reminded_issue_numbers"] == []
    assert len([call for call in requests if call[0] == "POST" and call[1] == "issues"]) == 1
    body = str(issue_rows[0]["body"])
    assert f"Root cause: {reason}" in body
    assert "Next reminder at: 2026-10-21T08:00:00+00:00" in body
    assert "Alert pending consumer: local" in body
    assert "post_close:2026-10-21" in body
    assert "Latest run: 200 attempt 2" in body


def test_audit_failure_reminds_after_thirty_minutes_and_verified_receipt_recovers(tmp_path, monkeypatch):
    directory = tmp_path / "evidence"
    directory.mkdir()
    incident_key = incidents._incident_key(
        "scheduled_market_brief", "scheduled_anchor_claim_missing", "notification-terminal-v2",
    )
    issue_body = "\n".join((
        f"{incidents.ISSUE_MARKER}{incident_key}",
        "Component: scheduled_market_brief",
        "Root cause: scheduled_anchor_claim_missing",
        "Contract: notification-terminal-v2",
        "Affected slot count: 1",
        "Affected slots: post_close:2026-10-20 (taiwan:2026-10-20:post_close)",
        "Affected slots complete: true",
        "First failure: 2026-10-20T07:00:00+00:00",
        "Latest evidence: missing_receipt",
        "Latest run: 99 attempt 1 (" + "c" * 40 + ")",
        "Observed at: 2026-10-20T07:00:00+00:00",
        "Next reminder at: 2026-10-20T07:30:00+00:00",
    ))
    issue = {"number": 23, "title": f"{incidents.ISSUE_TITLE_PREFIX} / scheduled_market_brief", "body": issue_body}
    calls: list[tuple[str, str, dict[str, object] | None]] = []
    monkeypatch.setattr(incidents, "_open_incidents", lambda *_args, **_kwargs: [issue])

    def request_json(_api, _repo, _token, method, path, payload=None, **_kwargs):
        calls.append((method, path, payload))
        if method == "PATCH" and path == "issues/23" and payload and "body" in payload:
            issue["body"] = payload["body"]
        return {}

    monkeypatch.setattr(incidents, "_request_json", request_json)
    audit_event = _event(run_id="300", attempt=1, sha="d" * 40, workflow="Scheduled brief slot receipt audit")
    missing = {
        "schema_version": "scheduled-slot-audit-result-v1", "run_id": "300", "attempt": 1,
        "workflow_sha": "d" * 40,
        "original_slot": {"slot": "post_close", "date": "2026-10-21", "anchor": "taiwan:2026-10-21:post_close"},
        "audited_at": "2026-10-21T08:00:00Z", "report_receipt_status": "missing_receipt",
        "diagnostic_complete": True, "result": {"status": "missing_receipt", "reason": "scheduled_anchor_claim_missing", "slot": "post_close", "market_date": "2026-10-21", "anchor": "taiwan:2026-10-21:post_close"},
    }
    (directory / "scheduled-slot-audit-300.json").write_text(json.dumps(missing), encoding="utf-8")
    result = incidents.reconcile(
        event=audit_event, evidence_directory=directory,
        repository="hanjhou2000716/prstklab-stk-detector",
        api_url="https://api.github.com", token="token",
        now=datetime.fromisoformat("2026-10-21T08:00:00Z"),
    )
    assert result["reminded_issue_numbers"] == [23]
    assert any(method == "POST" and path == "issues/23/comments" for method, path, _ in calls)

    calls.clear()
    recovered = {
        "schema_version": "scheduled-slot-audit-result-v1", "run_id": "301", "attempt": 1,
        "workflow_sha": "e" * 40,
        "original_slot": {"slot": "post_close", "date": "2026-10-21", "anchor": "taiwan:2026-10-21:post_close"},
        "audited_at": "2026-10-21T08:05:00Z", "report_receipt_status": "delivered",
        "diagnostic_complete": True, "result": {"status": "delivered", "slot": "post_close", "market_date": "2026-10-21", "anchor": "taiwan:2026-10-21:post_close"},
    }
    (directory / "scheduled-slot-audit-301.json").write_text(json.dumps(recovered), encoding="utf-8")
    recovery_result = incidents.reconcile(
        event=_event(run_id="301", attempt=1, sha="e" * 40, workflow="Scheduled brief slot receipt audit"),
        evidence_directory=directory, repository="hanjhou2000716/prstklab-stk-detector",
        api_url="https://api.github.com", token="token",
        now=datetime.fromisoformat("2026-10-21T08:05:00Z"),
    )
    assert recovery_result["recovered_issue_numbers"] == [23]
    assert any(method == "PATCH" and path == "issues/23" and payload == {"state": "closed", "state_reason": "completed"} for method, path, payload in calls)


def test_incident_consumer_rejects_untrusted_branch_before_issue_api(tmp_path):
    with pytest.raises(LivenessAuditError, match="trigger_branch_not_trusted"):
        incidents.reconcile(
            event={**_event(run_id="1", attempt=1, sha="f" * 40, workflow="Scheduled market brief"), "head_branch": "pull/1"},
            evidence_directory=tmp_path,
            repository="hanjhou2000716/prstklab-stk-detector",
            api_url="https://api.github.com", token="token",
        )


def test_handoff_artifact_binds_source_and_consumer_runs(monkeypatch):
    event = _event(run_id="100", attempt=2, sha="a" * 40, workflow="Scheduled market brief")
    monkeypatch.setenv("GITHUB_RUN_ID", "200")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_SHA", "b" * 40)
    result = {
        "diagnostic_complete": True,
        "incident_active": True,
        "opened_issue_numbers": [17],
        "reminded_issue_numbers": [],
        "recovered_issue_numbers": [],
        "evidence_kind": "report",
        "evidence_status": "failed",
    }

    record = incidents._handoff_result(event=event, result=result)

    assert record["schema_version"] == "scheduled-brief-incident-handoff-v1"
    assert record["consumer_run_id"] == "200"
    assert record["source_run_id"] == "100"
    assert record["source_attempt"] == 2
    assert record["source_sha"] == "a" * 40
    assert record["incident_handoff_status"] == "accepted"
    assert record["opened_issue_numbers"] == [17]
