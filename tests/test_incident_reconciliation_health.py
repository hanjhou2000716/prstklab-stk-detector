from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from scripts import incident_reconciliation as reconciliation
from scripts import incident_reconciliation_health as health
from scripts.monitor_liveness import LivenessAuditError


def test_pending_terminal_state_failure_has_specific_incident_root():
    assert health._safe_root("source_pending_terminal_state_unverified") == "central_reconciliation_source_run_unresolved"
    assert health._safe_root("workflow_contract_unknown_for_fixed_sha") == "central_reconciliation_source_run_unresolved"


def _run(run_id: int, created: str, sha: str | None = None) -> dict:
    return {
        "id": run_id,
        "workflow_id": 777,
        "path": health.CENTRAL_WORKFLOW_PATH,
        "run_attempt": 1,
        "head_branch": "main",
        "head_sha": sha or f"{run_id:040x}",
        "head_repository": {"full_name": "owner/repo"},
        "created_at": created,
        "run_started_at": created,
        "status": "completed",
        "conclusion": "success",
    }


def _result(run: dict, *, complete: bool = True) -> dict:
    return {
        "schema_version": "incident-reconciliation-v1",
        "consumer_run_id": str(run["id"]),
        "consumer_attempt": run["run_attempt"],
        "consumer_sha": run["head_sha"],
        "business_status": "healthy" if complete else "unknown",
        "diagnostic_complete": complete,
        "coverage_status": "complete" if complete else "incomplete",
        "incident_handoff_status": "accepted" if complete else "incomplete",
        "notification_due": False,
        "alert_terminal": {"status": "not_due"},
        "cadence_finalization": {"status": "not_due"},
        "source_cursors": {
            path: {"mode": "live", "scan_complete": True, "created_at": "2026-10-25T00:00:00+00:00", "run_id": run["id"]}
            for path in health.SOURCE_WORKFLOWS
        },
        "observed_at": run["created_at"],
    }


def _arrange(monkeypatch, runs, *, complete=True, issues=None, calls=None):
    calls = calls if calls is not None else []
    issues = issues if issues is not None else []

    def request(_api, _repository, _token, method, path, payload=None, **_kwargs):
        calls.append((method, path, payload))
        if path.endswith("incident-reconciliation.yml"):
            return {"id": 777, "path": health.CENTRAL_WORKFLOW_PATH, "state": "active"}
        if path.startswith("actions/workflows/777/runs?"):
            # The real Actions API silently returns zero rows for status=all.
            if "status=all" in path:
                return {"workflow_runs": []}
            return {"workflow_runs": runs}
        if method == "POST" and path == "issues":
            issue = {"number": 901, "title": payload["title"], "body": payload["body"], "state": "open"}
            issues.append(issue)
            return issue
        if method == "PATCH" and path.startswith("issues/"):
            number = int(path.split("/")[1])
            issue = next(item for item in issues if item["number"] == number)
            issue.update(payload)
            return issue
        if method == "POST" and path.endswith("/comments"):
            return {"id": 1}
        raise AssertionError((method, path, payload))

    def download(*, run, **_kwargs):
        return json.dumps(_result(run, complete=complete)).encode()

    monkeypatch.setattr(health, "_request_json", request)
    monkeypatch.setattr(health, "_download_artifact_json", download)
    monkeypatch.setattr(health, "_open_incidents", lambda *_args, **_kwargs: list(issues))
    return issues, calls


def test_health_watcher_opens_one_incident_for_incomplete_central_evidence(monkeypatch):
    now = datetime(2026, 10, 25, 2, 0, tzinfo=UTC)
    run = _run(501, now.isoformat())
    issues, calls = _arrange(monkeypatch, [run], complete=False)

    result = health.reconcile_health(
        repository="owner/repo", api_url="https://api.github.com", token="token",
        consumer_run_id="900", consumer_attempt=1, consumer_sha="f" * 40, now=now,
    )

    assert result["health_status"] == "degraded"
    assert result["failure_reason"] == "central_reconciliation_coverage_incomplete"
    assert result["latest_central_run_id"] == run["id"]
    assert result["notification_due"] is True
    assert result["incident_handoff_status"] == "accepted"
    assert len(issues) == 1
    assert issues[0]["title"].startswith(health.ISSUE_TITLE_PREFIX)
    assert "Root cause: central_reconciliation_coverage_incomplete" in issues[0]["body"]
    assert any(method == "POST" and path == "issues" for method, path, _ in calls)
    list_request = next(path for method, path, _ in calls if method == "GET" and path.startswith("actions/workflows/777/runs?"))
    assert "status=all" not in list_request


def test_health_watcher_preserves_source_http_failure_without_cursor_state(monkeypatch):
    now = datetime(2026, 10, 25, 2, 0, tzinfo=UTC)
    run = _run(502, now.isoformat())
    issues, calls = _arrange(monkeypatch, [run], complete=False)
    result_artifact = _result(run, complete=False)
    result_artifact.pop("source_cursors")
    result_artifact["failure_reason"] = "monitor_liveness_api_http_404"
    result_artifact["failure_evidence"] = {
        "method": "GET", "endpoint_class": "actions/runs/{run_id}", "http_status": 404,
        "request_id": "ABC:123", "retry_count": 3,
    }
    monkeypatch.setattr(health, "_download_artifact_json", lambda **_kwargs: json.dumps(result_artifact).encode())

    result = health.reconcile_health(
        repository="owner/repo", api_url="https://api.github.com", token="token",
        consumer_run_id="901", consumer_attempt=1, consumer_sha="f" * 40, now=now,
    )

    expected_root = "central_reconciliation_api_http_404"
    assert result["health_status"] == "degraded"
    assert result["failure_reason"] == expected_root
    assert len(issues) == 1
    assert f"Root cause: {expected_root}" in issues[0]["body"]
    assert any(method == "POST" and path == "issues" for method, path, _ in calls)


def test_health_watcher_consolidates_duplicate_matching_incidents(monkeypatch):
    now = datetime(2026, 10, 25, 2, 0, tzinfo=UTC)
    root = "central_reconciliation_coverage_incomplete"
    marker = health._marker(root)
    issues = [
        {
            "number": number,
            "title": f"{health.ISSUE_TITLE_PREFIX} / {root}",
            "state": "open",
            "body": (
                f"{marker}\nComponent: central_incident_reconciliation\n"
                f"Root cause: {root}\nContract: {health.CONTRACT}\n"
                f"First failure: {now.isoformat()}\n"
                f"Next reminder at: {(now + timedelta(minutes=30)).isoformat()}"
            ),
        }
        for number in (1068, 1073)
    ]
    issues, calls = _arrange(monkeypatch, [_run(501, now.isoformat())], complete=False, issues=issues)

    result = health.reconcile_health(
        repository="owner/repo", api_url="https://api.github.com", token="token",
        consumer_run_id="900", consumer_attempt=1, consumer_sha="f" * 40, now=now,
    )

    assert result["consolidated_issue_numbers"] == [1073]
    assert issues[0]["state"] == "open"
    assert issues[1]["state"] == "closed"
    assert any(
        method == "PATCH" and path == "issues/1073"
        and payload == {"state": "closed", "state_reason": "duplicate"}
        for method, path, payload in calls
    )
    assert any(method == "POST" and path == "issues/1073/comments" for method, path, _ in calls)


def test_health_watcher_resolves_workflow_run_event_when_listing_lags(monkeypatch):
    now = datetime(2026, 10, 25, 10, 1, tzinfo=UTC)
    event_run = _run(40183001117, "2026-10-25T10:00:46+00:00", "2f588ed42fd51e3c078745ed7e5952b94d10c0d8")
    calls = []
    issues = []

    def request(_api, _repository, _token, method, path, payload=None, **_kwargs):
        calls.append((method, path, payload))
        if path.endswith("incident-reconciliation.yml"):
            return {"id": 777, "path": health.CENTRAL_WORKFLOW_PATH, "state": "active"}
        if path.startswith("actions/workflows/777/runs?"):
            return {"workflow_runs": []}
        if path == f"actions/runs/{event_run['id']}":
            return event_run
        if method == "POST" and path == "issues":
            issue = {"number": 901, "title": payload["title"], "body": payload["body"], "state": "open"}
            issues.append(issue)
            return issue
        raise AssertionError((method, path, payload))

    monkeypatch.setattr(health, "_request_json", request)
    monkeypatch.setattr(health, "_download_artifact_json", lambda *, run, **_kwargs: json.dumps(_result(run, complete=False)).encode())
    monkeypatch.setattr(health, "_open_incidents", lambda *_args, **_kwargs: list(issues))

    result = health.reconcile_health(
        repository="owner/repo", api_url="https://api.github.com", token="token",
        consumer_run_id="900", consumer_attempt=1, consumer_sha="f" * 40, now=now,
        triggered_run_id=str(event_run["id"]), triggered_run_attempt="1",
        triggered_run_sha=event_run["head_sha"],
    )

    assert result["health_status"] == "degraded"
    assert result["failure_reason"] == "central_reconciliation_coverage_incomplete"
    assert len(issues) == 1
    assert "Latest run: 40183001117" in issues[0]["body"]
    assert any(method == "GET" and path == f"actions/runs/{event_run['id']}" for method, path, _ in calls)
    assert not any("run_missing" in str(payload) for _method, _path, payload in calls)


def test_health_watcher_retries_transient_trigger_run_404(monkeypatch):
    event_run = _run(40183001117, "2026-10-25T10:00:46+00:00", "2f588ed42fd51e3c078745ed7e5952b94d10c0d8")
    calls = []

    def request(_api, _repository, _token, method, path, payload=None, **_kwargs):
        calls.append((method, path, payload))
        if path.endswith("incident-reconciliation.yml"):
            return {"id": 777, "path": health.CENTRAL_WORKFLOW_PATH, "state": "active"}
        if path.startswith("actions/workflows/777/runs?"):
            return {"workflow_runs": []}
        if path == f"actions/runs/{event_run['id']}":
            if sum(item[1] == path for item in calls) < 3:
                raise LivenessAuditError("monitor_liveness_api_http_404")
            return event_run
        if method == "POST" and path == "issues":
            return {"number": 901, "title": payload["title"], "body": payload["body"], "state": "open"}
        raise AssertionError((method, path, payload))

    monkeypatch.setattr(health, "_request_json", request)
    monkeypatch.setattr(health.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(health, "_download_artifact_json", lambda *, run, **_kwargs: json.dumps(_result(run, complete=False)).encode())
    monkeypatch.setattr(health, "_open_incidents", lambda *_args, **_kwargs: [])

    result = health.reconcile_health(
        repository="owner/repo", api_url="https://api.github.com", token="token",
        consumer_run_id="900", consumer_attempt=1, consumer_sha="f" * 40,
        triggered_run_id=str(event_run["id"]), triggered_run_attempt="1",
        triggered_run_sha=event_run["head_sha"],
    )

    assert result["failure_reason"] == "central_reconciliation_coverage_incomplete"
    assert sum(path == f"actions/runs/{event_run['id']}" for _method, path, _payload in calls) == 3


def test_health_watcher_rejects_mismatched_triggered_run_identity(monkeypatch):
    event_run = _run(40183001117, "2026-10-25T10:00:46+00:00", "2f588ed42fd51e3c078745ed7e5952b94d10c0d8")

    def request(_api, _repository, _token, method, path, payload=None, **_kwargs):
        if path.endswith("incident-reconciliation.yml"):
            return {"id": 777, "path": health.CENTRAL_WORKFLOW_PATH, "state": "active"}
        if path.startswith("actions/workflows/777/runs?"):
            return {"workflow_runs": []}
        if path == f"actions/runs/{event_run['id']}":
            return {**event_run, "head_sha": "e" * 40}
        raise AssertionError((method, path, payload))

    monkeypatch.setattr(health, "_request_json", request)

    try:
        health._read_runs(
            repository="owner/repo", api_url="https://api.github.com", token="token",
            deadline=10**9, triggered_run_id=str(event_run["id"]),
            triggered_run_attempt="1", triggered_run_sha=event_run["head_sha"],
        )
    except LivenessAuditError as exc:
        assert str(exc) == "central_health_trigger_run_identity_mismatch"
    else:
        raise AssertionError("mismatched workflow_run event identity was accepted")


def test_health_watcher_does_not_close_on_one_good_run_and_recovers_after_two(monkeypatch):
    now = datetime(2026, 10, 25, 2, 0, tzinfo=UTC)
    marker = health._marker("central_reconciliation_coverage_incomplete")
    issue = {
        "number": 901,
        "title": f"{health.ISSUE_TITLE_PREFIX} / coverage",
        "state": "open",
        "body": (
            f"{marker}\nComponent: central_incident_reconciliation\n"
            f"Root cause: central_reconciliation_coverage_incomplete\n"
            f"Contract: {health.CONTRACT}\nFirst failure: {now.isoformat()}"
        ),
    }
    issues, calls = _arrange(monkeypatch, [_run(502, now.isoformat())], issues=[issue])
    first = health.reconcile_health(
        repository="owner/repo", api_url="https://api.github.com", token="token",
        consumer_run_id="901", consumer_attempt=1, consumer_sha="f" * 40, now=now,
    )
    assert first["health_status"] == "recovery_pending"
    assert not any(method == "PATCH" and payload and payload.get("state") == "closed" for method, _path, payload in calls)

    calls.clear()
    monkeypatch.setattr(health, "_read_runs", lambda **_kwargs: (777, [_run(503, now.isoformat()), _run(502, now.isoformat())]))
    second = health.reconcile_health(
        repository="owner/repo", api_url="https://api.github.com", token="token",
        consumer_run_id="902", consumer_attempt=1, consumer_sha="e" * 40, now=now + timedelta(minutes=5),
    )
    assert second["health_status"] == "recovered"
    assert second["recovered_issue_numbers"] == [901]
    assert any(method == "PATCH" and payload and payload.get("state") == "closed" for method, _path, payload in calls)


def test_health_watcher_fails_closed_for_missing_artifact_and_does_not_recover(monkeypatch):
    now = datetime(2026, 10, 25, 2, 0, tzinfo=UTC)
    issue = {
        "number": 901,
        "title": f"{health.ISSUE_TITLE_PREFIX} / result",
        "state": "open",
        "body": f"{health._marker('central_reconciliation_result_unavailable')}\nContract: {health.CONTRACT}\nFirst failure: {now.isoformat()}\nNext reminder at: {(now + timedelta(minutes=30)).isoformat()}",
    }
    _arrange(monkeypatch, [_run(504, now.isoformat())], issues=[issue])
    monkeypatch.setattr(health, "_download_artifact_json", lambda **_kwargs: (_ for _ in ()).throw(LivenessAuditError("incident_artifact_missing")))

    result = health.reconcile_health(
        repository="owner/repo", api_url="https://api.github.com", token="token",
        consumer_run_id="903", consumer_attempt=1, consumer_sha="d" * 40, now=now,
    )

    assert result["health_status"] == "degraded"
    assert result["notification_due"] is False
    assert "recovered_issue_numbers" not in result


def test_health_watcher_rejects_cursor_that_did_not_complete_source_scan():
    run = _run(510, "2026-10-25T02:00:00+00:00")
    result = _result(run)
    first_source = next(iter(health.SOURCE_WORKFLOWS))
    result["source_cursors"][first_source]["scan_complete"] = False

    complete, root, _fingerprint = health._result_is_complete(result)

    assert complete is False
    assert root == "central_reconciliation_coverage_incomplete"


def test_health_watcher_rejects_invalid_cursor_mode_and_identity():
    run = _run(511, "2026-10-25T02:00:00+00:00")
    result = _result(run)
    first_source = next(iter(health.SOURCE_WORKFLOWS))
    result["source_cursors"][first_source]["mode"] = "unknown"

    complete, root, _fingerprint = health._result_is_complete(result)

    assert complete is False
    assert root == "central_reconciliation_coverage_incomplete"


def test_health_watcher_accepts_complete_backfill_window_at_zero_run_id():
    run = _run(512, "2026-10-25T02:00:00+00:00")
    result = _result(run)
    first_source = next(iter(health.SOURCE_WORKFLOWS))
    result["source_cursors"][first_source].update({
        "mode": "backfill",
        "run_id": 0,
        "window_start": "2026-10-24T00:00:00+00:00",
        "window_end": "2026-10-24T05:59:59+00:00",
    })

    complete, root, _fingerprint = health._result_is_complete(result)

    assert complete is True
    assert root == ""


def test_health_watcher_rejects_due_alert_without_confirmed_cadence_finalization():
    run = _run(513, "2026-10-25T02:00:00+00:00")
    result = _result(run)
    result["notification_due"] = True
    result["alert_terminal"] = {"status": "confirmed"}
    result["cadence_finalization"] = {"status": "failed"}

    complete, root, _fingerprint = health._result_is_complete(result)

    assert complete is False
    assert root == "central_reconciliation_alert_handoff_incomplete"


def test_health_watcher_throttles_reminders_to_thirty_minutes(monkeypatch):
    now = datetime(2026, 10, 25, 2, 30, tzinfo=UTC)
    marker = health._marker("central_reconciliation_coverage_incomplete")
    issue = {
        "number": 901,
        "title": f"{health.ISSUE_TITLE_PREFIX} / coverage",
        "state": "open",
        "body": (
            f"{marker}\nComponent: central_incident_reconciliation\n"
            "Root cause: central_reconciliation_coverage_incomplete\n"
            f"Contract: {health.CONTRACT}\nFirst failure: {now.isoformat()}\n"
            f"Next reminder at: {(now - timedelta(seconds=1)).isoformat()}"
        ),
    }
    issues, calls = _arrange(monkeypatch, [_run(505, now.isoformat())], complete=False, issues=[issue])
    result = health.reconcile_health(
        repository="owner/repo", api_url="https://api.github.com", token="token",
        consumer_run_id="904", consumer_attempt=1, consumer_sha="c" * 40, now=now,
    )

    assert result["notification_due"] is True
    assert result["notification_cadence_confirmations"] == [{
        "issue_number": 901,
        "marker": marker,
        "next_reminder_at": (now + timedelta(minutes=30)).isoformat(),
    }]
    assert "Alert pending consumer: 904/1" in issues[0]["body"]
    calls.clear()
    next_result = health.reconcile_health(
        repository="owner/repo", api_url="https://api.github.com", token="token",
        consumer_run_id="905", consumer_attempt=1, consumer_sha="b" * 40, now=now + timedelta(minutes=5),
    )
    assert next_result["notification_due"] is False
    assert not any(method == "POST" and path.endswith("/comments") for method, path, _ in calls)


def test_health_watcher_waits_ten_minutes_before_classifying_running_reconcile_as_stalled(monkeypatch):
    now = datetime(2026, 10, 25, 2, 0, tzinfo=UTC)
    run = _run(506, now.isoformat())
    run["status"] = "in_progress"
    run["run_started_at"] = (now - timedelta(minutes=9)).isoformat()
    issues, _calls = _arrange(monkeypatch, [run])
    result = health.reconcile_health(
        repository="owner/repo", api_url="https://api.github.com", token="token",
        consumer_run_id="906", consumer_attempt=1, consumer_sha="a" * 40, now=now,
    )
    assert result["health_status"] == "pending"
    assert result["business_status"] == "unknown"
    assert issues == []


def test_health_workflow_is_independent_and_alerts_only_from_health_decision():
    from pathlib import Path

    root = Path(__file__).parents[1]
    workflow = (root / ".github/workflows/incident-reconciliation-health.yml").read_text(encoding="utf-8")
    assert 'cron: "*/5 * * * *"' in workflow
    assert "Central incident reconciliation" in workflow
    assert "prstk-central-incident-health" in workflow
    assert "steps.inspect.outputs.notification_due == 'true'" in workflow
    assert "finalize-alert-cadence" in workflow
    assert "workflow_dispatch" in workflow
    assert "TRIGGERED_CENTRAL_RUN_ID" in workflow
    assert "TRIGGERED_CENTRAL_RUN_ATTEMPT" in workflow
    assert "TRIGGERED_CENTRAL_RUN_SHA" in workflow


def test_health_marker_is_accepted_by_shared_cadence_contract():
    assert reconciliation._cadence_marker_valid(health._marker("central_reconciliation_stalled"))
    assert not reconciliation._cadence_marker_valid(f"{reconciliation.CENTRAL_HEALTH_MARKER}not-a-digest")
