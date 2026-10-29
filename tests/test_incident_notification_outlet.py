import json
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


def test_prepare_groups_one_verified_consumer_into_one_window_notification(monkeypatch):
    issue = _issue()
    monkeypatch.setattr(outlet, "_open_incidents", lambda *a, **k: [issue])
    monkeypatch.setattr(outlet, "_load_verified_consumer", lambda **k: (
        {"head_sha": "a" * 40, "path": ".github/workflows/incident-reconciliation.yml"},
        {
            "notification_due": True,
            "notification_cadence_confirmations": [{
                "issue_number": 123,
                "marker": "official-event-delivery=0123456789abcdef01234567",
                "next_reminder_at": "2026-10-28T10:30:00+00:00",
            }],
        },
    ))
    result = outlet.prepare_outlet(
        repository="owner/repo", api_url="https://api.github.com", token="x",
        now=datetime(2026, 10, 28, 10, 0, tzinfo=UTC), deadline_monotonic=10**20,
    )
    assert result["notification_due"] is True
    assert result["notification_mode"] == "half_hour_digest"
    assert result["window_key"] == "2026-10-28T10:00:00+00:00"
    assert result["candidate_count"] == 1
    assert result["consumers"][0]["confirmations"][0]["issue_number"] == 123


def test_critical_identity_or_claim_incident_can_alert_immediately(monkeypatch):
    issue = _issue(root="notification_claim_state_conflict", due="2026-10-28T11:00:00+00:00")
    issue["body"] = issue["body"].replace("2026-10-28T09:30:00+00:00", "2026-10-28T10:10:00+00:00")
    issue["body"] += "\nObserved at: 2026-10-28T10:10:00+00:00"
    monkeypatch.setattr(outlet, "_open_incidents", lambda *a, **k: [issue])
    monkeypatch.setattr(outlet, "_load_verified_consumer", lambda **k: (
        {"head_sha": "b" * 40, "path": ".github/workflows/incident-reconciliation-health.yml"},
        {"notification_due": True, "notification_cadence_confirmations": [{
            "issue_number": 123,
            "marker": "official-event-delivery=0123456789abcdef01234567",
            "next_reminder_at": "2026-10-28T11:30:00+00:00",
        }]},
    ))
    result = outlet.prepare_outlet(
        repository="owner/repo", api_url="https://api.github.com", token="x",
        now=datetime(2026, 10, 28, 10, 12, tzinfo=UTC), deadline_monotonic=10**20,
    )
    assert result["notification_due"] is True
    assert result["notification_mode"] == "immediate_critical"
    assert result["consumers"][0]["confirmations"][0]["critical"] is True


def test_prepare_rejects_issue_without_source_artifact_confirmation(monkeypatch):
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


def test_finalize_updates_cadence_once_and_persists_window(tmp_path, monkeypatch):
    value = {
        "schema_version": outlet.OUTLET_SCHEMA,
        "status": "alert_pending",
        "notification_due": True,
        "window_key": "2026-10-28T10:00:00+00:00",
        "incident_fingerprint": "f" * 64,
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
    monkeypatch.setattr(outlet, "finalize_alert_cadence", lambda **kwargs: kwargs)
    calls = []
    def request(_api, _repo, _token, method, endpoint, payload=None, **_kwargs):
        calls.append((method, endpoint, payload))
        if method == "GET":
            return {"number": 123, "body": _issue()["body"]}
        return {"number": 123}
    monkeypatch.setattr(outlet, "_request_json", request)
    result = outlet.finalize_outlet(
        result_path=path, repository="owner/repo", api_url="https://api.github.com", token="x",
        alert_emitted=True, alert_step_outcome="failure",
        now=datetime(2026, 10, 28, 10, 1, tzinfo=UTC),
    )
    assert result["status"] == "alert_confirmed"
    assert result["alert_job"] == "failure_confirmed"
    patch = next(row[2] for row in calls if row[0] == "PATCH")
    assert "Last outlet window: 2026-10-28T10:00:00+00:00" in patch["body"]
