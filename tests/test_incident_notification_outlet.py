import json
from copy import deepcopy
from datetime import UTC, datetime

import pytest

from scripts import incident_notification_outlet as outlet
from scripts.monitor_liveness import LivenessAuditError


def _issue(*, root="transport_failed", due="2026-10-28T10:00:00+00:00"):
    return {
        "number": 123,
        "title": "Official event delivery degraded / official_event_delivery",
        "state": "open",
        "body": "\n".join((
            "official-event-delivery=0123456789abcdef01234567",
            "Component: official_event_delivery",
            f"Root cause: {root}",
            "First failure: 2026-10-28T09:30:00+00:00",
            f"Next reminder at: {due}",
            "Alert pending consumer: 456/1",
            "Alert pending since: 2026-10-28T09:30:00+00:00",
        )),
    }


def _stub_journal(monkeypatch, initial=None):
    control = {
        "number": 900,
        "title": outlet.CONTROL_ISSUE_TITLE,
        "body": outlet._journal_body(initial or outlet._default_journal("owner/repo")),
    }
    state = deepcopy(initial or outlet._default_journal("owner/repo"))

    def load(**_kwargs):
        control["body"] = outlet._journal_body(state)
        return control, deepcopy(state)

    def save(*, journal, expected_generation, **_kwargs):
        state.clear()
        state.update(deepcopy(journal))
        state["generation"] = expected_generation + 1
        control["body"] = outlet._journal_body(state)
        return deepcopy(state)

    monkeypatch.setattr(outlet, "_load_control_journal", load)
    monkeypatch.setattr(outlet, "_save_control_journal", save)
    return state


def _stub_verified_consumer(monkeypatch, issue_number=123):
    monkeypatch.setattr(outlet, "_load_verified_consumer", lambda **_k: (
        {"head_sha": "a" * 40, "path": ".github/workflows/incident-reconciliation.yml"},
        {
            "notification_due": True,
            "notification_cadence_confirmations": [{
                "issue_number": issue_number,
                "marker": "official-event-delivery=0123456789abcdef01234567",
                "next_reminder_at": "2026-10-28T10:30:00+00:00",
            }],
        },
    ))
    monkeypatch.setenv("GITHUB_RUN_ID", "789")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_SHA", "b" * 40)


def test_prepare_groups_one_verified_consumer_into_one_window_notification(monkeypatch):
    issue = _issue()
    journal = _stub_journal(monkeypatch)
    _stub_verified_consumer(monkeypatch)
    monkeypatch.setattr(outlet, "_open_incidents", lambda *a, **k: [issue])
    result = outlet.prepare_outlet(
        repository="owner/repo", api_url="https://api.github.com", token="x",
        now=datetime(2026, 10, 28, 10, 1, 37, tzinfo=UTC), deadline_monotonic=10**20,
    )
    assert result["notification_due"] is True
    assert result["notification_mode"] == "half_hour_digest"
    assert result["window_key"] == "2026-10-28T10:00:00+00:00"
    assert result["candidate_count"] == 1
    assert result["consumers"][0]["confirmations"][0]["issue_number"] == 123
    assert result["consumers"][0]["confirmations"][0]["next_reminder_at"] == "2026-10-28T10:30:00+00:00"
    assert result["journal_status"] == "pending_terminal_confirmation"
    assert journal["pending_decision"]["decision_id"] == result["decision_id"]
    control = {"number": 900}
    monkeypatch.setattr(outlet, "_verify_pending_alert_terminal", lambda *_a, **_k: "confirmed")
    monkeypatch.setattr(outlet, "_sync_incident_after_confirmed_alert", lambda *_a, **_k: None)
    resolved = outlet._resolve_pending_decision(
        control_issue=control, journal=deepcopy(journal), repository="owner/repo",
        api_url="https://api.github.com", token="x", deadline=10**20,
        now=datetime(2026, 10, 28, 10, 3, tzinfo=UTC),
    )
    assert resolved["pending_decision"] is None
    assert resolved["last_confirmed_window_key"] == "2026-10-28T10:00:00+00:00"
    duplicate = outlet.prepare_outlet(
        repository="owner/repo", api_url="https://api.github.com", token="x",
        now=datetime(2026, 10, 28, 10, 4, tzinfo=UTC), deadline_monotonic=10**20,
    )
    assert duplicate["notification_due"] is False


def test_historical_pending_issue_cannot_reuse_an_old_notification_reservation(monkeypatch):
    issue = _issue()
    _stub_journal(monkeypatch)
    issue["body"] += "\nLifecycle: historical_pending_verification"
    monkeypatch.setattr(outlet, "_open_incidents", lambda *a, **k: [issue])
    calls = []
    monkeypatch.setattr(outlet, "_load_verified_consumer", lambda **k: calls.append(k))
    result = outlet.prepare_outlet(
        repository="owner/repo", api_url="https://api.github.com", token="x",
        now=datetime(2026, 10, 28, 10, 0, tzinfo=UTC), deadline_monotonic=10**20,
    )
    assert result["notification_due"] is False
    assert result["candidate_count"] == 0
    assert calls == []


def test_critical_identity_or_claim_incident_can_alert_immediately(monkeypatch):
    issue = _issue(root="notification_claim_state_conflict", due="2026-10-28T11:00:00+00:00")
    issue["body"] = issue["body"].replace("2026-10-28T09:30:00+00:00", "2026-10-28T10:10:00+00:00")
    issue["body"] += "\nObserved at: 2026-10-28T10:10:00+00:00"
    _stub_journal(monkeypatch)
    _stub_verified_consumer(monkeypatch)
    monkeypatch.setattr(outlet, "_open_incidents", lambda *a, **k: [issue])
    result = outlet.prepare_outlet(
        repository="owner/repo", api_url="https://api.github.com", token="x",
        now=datetime(2026, 10, 28, 10, 12, tzinfo=UTC), deadline_monotonic=10**20,
    )
    assert result["notification_due"] is True
    assert result["notification_mode"] == "immediate_critical"
    assert result["consumers"][0]["confirmations"][0]["critical"] is True
    assert result["consumers"][0]["confirmations"][0]["next_reminder_at"] == "2026-10-28T10:30:00+00:00"


def test_prepare_rejects_issue_without_source_artifact_confirmation(monkeypatch):
    _stub_journal(monkeypatch)
    _stub_verified_consumer(monkeypatch)
    monkeypatch.setattr(outlet, "_open_incidents", lambda *a, **k: [_issue()])
    monkeypatch.setattr(outlet, "_load_verified_consumer", lambda **k: (
        {"head_sha": "a" * 40, "path": ".github/workflows/incident-reconciliation.yml"},
        {"notification_due": True, "notification_cadence_confirmations": []},
    ))
    with pytest.raises(LivenessAuditError, match="source_confirmation_missing"):
        outlet.prepare_outlet(
            repository="owner/repo", api_url="https://api.github.com", token="x",
            now=datetime(2026, 10, 28, 10, 0, tzinfo=UTC), deadline_monotonic=10**20,
        )


def test_finalize_keeps_decision_pending_until_exact_run_terminal_can_be_read(tmp_path, monkeypatch):
    value = {
        "schema_version": outlet.OUTLET_SCHEMA,
        "status": "alert_pending",
        "notification_due": True,
        "notification_mode": "half_hour_digest",
        "window_key": "2026-10-28T10:00:00+00:00",
        "incident_fingerprint": "f" * 64,
        "decision_id": "d" * 64,
        "outlet_run_id": 789,
        "outlet_attempt": 1,
        "outlet_sha": "b" * 40,
        "control_issue_number": 900,
        "consumers": [{
            "run_id": "456", "attempt": 1, "sha": "a" * 40,
            "confirmations": [{
                "issue_number": 123,
                "marker": "official-event-delivery=0123456789abcdef01234567",
                "critical": False,
            }],
        }],
    }
    path = tmp_path / "outlet.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    calls = []
    monkeypatch.setattr(outlet, "_request_json", lambda *a, **k: calls.append((a, k)))
    result = outlet.finalize_outlet(
        result_path=path, repository="owner/repo", api_url="https://api.github.com", token="x",
        alert_emitted=True, alert_step_outcome="failure",
        now=datetime(2026, 10, 28, 10, 1, tzinfo=UTC),
    )
    assert result["status"] == "alert_reported_pending_terminal_confirmation"
    assert result["alert_job"] == "reported_failure_pending_workflow_terminal"
    assert result["terminal_confirmation"] == "pending_exact_run_attempt_and_artifact_readback"
    assert calls == []


def test_same_confirmed_half_hour_window_suppresses_a_second_reminder(monkeypatch):
    journal = outlet._default_journal("owner/repo")
    journal["last_confirmed_window_key"] = "2026-10-28T10:00:00+00:00"
    _stub_journal(monkeypatch, journal)
    issue = _issue()
    monkeypatch.setattr(outlet, "_open_incidents", lambda *a, **k: [issue])
    consumer_calls = []
    monkeypatch.setattr(outlet, "_load_verified_consumer", lambda **k: consumer_calls.append(k))
    result = outlet.prepare_outlet(
        repository="owner/repo", api_url="https://api.github.com", token="x",
        now=datetime(2026, 10, 28, 10, 2, tzinfo=UTC), deadline_monotonic=10**20,
    )
    assert result["notification_due"] is False
    assert result["suppression_reason"] == "ordinary_window_already_confirmed"
    assert consumer_calls == []


def test_alert_terminal_requires_exact_completed_attempt_and_artifact(monkeypatch):
    pending = {
        "outlet_run_id": 789, "outlet_attempt": 1, "outlet_sha": "b" * 40,
        "decision_id": "d" * 64, "window_key": "2026-10-28T10:00:00+00:00",
        "incident_fingerprint": "f" * 64,
    }
    def request(_api, _repo, _token, _method, endpoint, **_kwargs):
        if endpoint == "actions/runs/789/attempts/1":
            return {
                "id": 789, "run_attempt": 1, "status": "completed", "path": outlet.OUTLET_WORKFLOW_PATH,
                "head_branch": "main", "head_sha": "b" * 40,
                "head_repository": {"full_name": "owner/repo"},
            }
        return {"jobs": [{"run_id": 789, "run_attempt": 1, "status": "completed", "steps": [{
            "name": outlet.ALERT_STEP_NAME, "status": "completed", "conclusion": "failure",
            "completed_at": "2026-10-28T10:01:00+00:00",
        }]}]}
    monkeypatch.setattr(outlet, "_request_json", request)
    decision = {
        "schema_version": outlet.OUTLET_SCHEMA, "notification_due": True,
        **pending,
    }
    monkeypatch.setattr(outlet, "_download_artifact_json", lambda **_k: json.dumps(decision).encode())
    assert outlet._verify_pending_alert_terminal(
        pending, repository="owner/repo", api_url="https://api.github.com", token="x", deadline=10**20,
    ) == "confirmed"


def test_control_journal_create_is_read_back_and_closed_identity_is_not_recreated(monkeypatch):
    created = {
        "number": 900, "title": outlet.CONTROL_ISSUE_TITLE, "state": "open",
        "body": outlet._journal_body(outlet._default_journal("owner/repo")),
    }
    calls = []
    monkeypatch.setattr(outlet, "_read_journal_issues", lambda **_k: [])

    def request(_api, _repo, _token, method, endpoint, payload=None, **_kwargs):
        calls.append((method, endpoint))
        if method == "POST":
            assert endpoint == "issues"
            assert payload["title"] == outlet.CONTROL_ISSUE_TITLE
            return {"number": 900, "title": outlet.CONTROL_ISSUE_TITLE}
        assert method == "GET" and endpoint == "issues/900"
        return created

    monkeypatch.setattr(outlet, "_request_json", request)
    issue, journal = outlet._load_control_journal(
        repository="owner/repo", api_url="https://api.github.com", token="x", deadline=10**20,
    )
    assert issue["number"] == 900
    assert journal["schema_version"] == outlet.JOURNAL_SCHEMA
    assert calls == [("POST", "issues"), ("GET", "issues/900")]

    monkeypatch.setattr(outlet, "_read_journal_issues", lambda **_k: [{**created, "state": "closed"}])
    with pytest.raises(LivenessAuditError, match="control_identity_invalid"):
        outlet._load_control_journal(
            repository="owner/repo", api_url="https://api.github.com", token="x", deadline=10**20,
        )
