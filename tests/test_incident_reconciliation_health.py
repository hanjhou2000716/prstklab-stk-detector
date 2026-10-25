from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from scripts import incident_reconciliation as reconciliation
from scripts import incident_reconciliation_health as health
from scripts.monitor_liveness import LivenessAuditError


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
    assert result["notification_due"] is True
    assert result["incident_handoff_status"] == "accepted"
    assert len(issues) == 1
    assert issues[0]["title"].startswith(health.ISSUE_TITLE_PREFIX)
    assert "Root cause: central_reconciliation_coverage_incomplete" in issues[0]["body"]
    assert any(method == "POST" and path == "issues" for method, path, _ in calls)


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


def test_health_marker_is_accepted_by_shared_cadence_contract():
    assert reconciliation._cadence_marker_valid(health._marker("central_reconciliation_stalled"))
    assert not reconciliation._cadence_marker_valid(f"{reconciliation.CENTRAL_HEALTH_MARKER}not-a-digest")
