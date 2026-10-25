import json
from datetime import UTC, datetime, timedelta

from scripts import official_event_incidents as incidents


def _trace(status: str, *, detected: datetime, reason: str = "summary_semantics_incomplete") -> dict:
    return {
        "schema_version": "official-event-trace-v1",
        "workflow_run_id": "123",
        "workflow_sha": "a" * 40,
        "stages": {"scan": "success"},
        "events": [{
            "event_ref": "opaque-ref", "expected": True, "status": status,
            "reason": reason, "summary_contract_version": "public-summary-v4",
            "first_detected_at": detected.isoformat(),
            "candidate_recorded_at": detected.isoformat(),
            "last_progress_at": detected.isoformat(),
        }],
    }


def test_summary_incident_opens_only_after_ten_minutes_and_is_grouped(monkeypatch, tmp_path):
    now = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(json.dumps(_trace("summary_pending", detected=now - timedelta(minutes=9))), encoding="utf-8")
    monkeypatch.setattr(incidents, "_open_incidents", lambda *_args, **_kwargs: [])
    calls = []
    monkeypatch.setattr(incidents, "_request_json", lambda *args, **kwargs: calls.append((args, kwargs)) or {"number": 9})
    result = incidents.reconcile_incidents(
        api_url="https://api.github.com", repository="owner/repo", token="token",
        trace_path=trace_path, now=now,
    )
    assert result["opened_issue_numbers"] == []
    assert calls == []

    trace_path.write_text(json.dumps(_trace("summary_pending", detected=now - timedelta(minutes=11))), encoding="utf-8")
    result = incidents.reconcile_incidents(
        api_url="https://api.github.com", repository="owner/repo", token="token",
        trace_path=trace_path, now=now,
    )
    assert result["opened_issue_numbers"] == [9]
    payload = calls[0][0][5]
    assert payload["title"].startswith(incidents.EVENT_ISSUE_TITLE_PREFIX)
    assert "Root cause: priority_summary_timeout" in payload["body"]


def test_event_incident_reminder_and_recovery_are_separate_transitions(monkeypatch, tmp_path):
    now = datetime(2026, 10, 16, 4, 0, tzinfo=UTC)
    active_trace = _trace("partial", detected=now - timedelta(minutes=45), reason="recipient_receipt_partial")
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(json.dumps(active_trace), encoding="utf-8")
    key = incidents._incident_group("recipient_receipt_partial", "public-summary-v4")[1]
    issue = {
        "number": 11,
        "title": f"{incidents.EVENT_ISSUE_TITLE_PREFIX} / official_event_delivery",
        "body": (
            f"{incidents.EVENT_INCIDENT_MARKER}{key}\n"
            f"First failure: {(now - timedelta(minutes=45)).isoformat()}\n"
            f"Next reminder at: {(now - timedelta(seconds=1)).isoformat()}\n"
            "Affected event count: 1\n"
            "Event refs: opaque-ref\n"
            "Event refs complete: true"
        ),
    }
    monkeypatch.setattr(incidents, "_open_incidents", lambda *_args, **_kwargs: [issue])
    calls = []
    monkeypatch.setattr(incidents, "_request_json", lambda *args, **kwargs: calls.append((args, kwargs)) or {})
    result = incidents.reconcile_incidents(
        api_url="https://api.github.com", repository="owner/repo", token="token",
        trace_path=trace_path, now=now,
    )
    assert result["reminded_issue_numbers"] == [11]
    assert any(args[3] == "POST" and args[4] == "issues/11/comments" for args, _ in calls)

    trace_path.write_text(json.dumps({
        **active_trace,
        "events": [{
            **active_trace["events"][0],
            "status": "delivered",
            "reason": "recipient_receipt_verified",
        }],
    }), encoding="utf-8")
    calls.clear()
    result = incidents.reconcile_incidents(
        api_url="https://api.github.com", repository="owner/repo", token="token",
        trace_path=trace_path, now=now + timedelta(minutes=1),
    )
    assert result["recovered_issue_numbers"] == [11]
    assert any(args[3] == "PATCH" and args[4] == "issues/11" and args[5]["state"] == "closed" for args, _ in calls)


def test_empty_successful_scan_cannot_close_event_incident(monkeypatch, tmp_path):
    now = datetime(2026, 10, 16, 4, 0, tzinfo=UTC)
    path = tmp_path / "trace.json"
    path.write_text(json.dumps({**_trace("partial", detected=now), "events": []}), encoding="utf-8")
    key = incidents._incident_group("recipient_receipt_partial", "public-summary-v4")[1]
    issue = {
        "number": 22,
        "title": f"{incidents.EVENT_ISSUE_TITLE_PREFIX} / official_event_delivery",
        "body": (
            f"{incidents.EVENT_INCIDENT_MARKER}{key}\n"
            "Affected event count: 1\n"
            "Event refs: opaque-ref\n"
            "Event refs complete: true"
        ),
    }
    monkeypatch.setattr(incidents, "_open_incidents", lambda *_args, **_kwargs: [issue])
    calls = []
    monkeypatch.setattr(incidents, "_request_json", lambda *args, **kwargs: calls.append(args) or {})
    result = incidents.reconcile_incidents(
        api_url="https://api.github.com", repository="owner/repo", token="token",
        trace_path=path, now=now,
    )
    assert result["diagnostic_complete"] is True
    assert result["recovered_issue_numbers"] == []
    assert calls == []


def test_expired_event_is_not_recovery_evidence(monkeypatch, tmp_path):
    now = datetime(2026, 10, 16, 4, 0, tzinfo=UTC)
    trace = _trace("expired", detected=now - timedelta(minutes=45), reason="source_ttl_expired")
    assert "opaque-ref" not in incidents._resolved_event_refs(trace)

    trace_path = tmp_path / "trace.json"
    trace_path.write_text(json.dumps(trace), encoding="utf-8")
    key = incidents._incident_group("source_ttl_expired", "public-summary-v4")[1]
    issue = {
        "number": 25,
        "title": f"{incidents.EVENT_ISSUE_TITLE_PREFIX} / official_event_delivery",
        "body": (
            f"{incidents.EVENT_INCIDENT_MARKER}{key}\n"
            f"First failure: {now.isoformat()}\nNext reminder at: {(now + timedelta(minutes=30)).isoformat()}\n"
            "Affected event count: 1\nEvent refs: opaque-ref\nEvent refs complete: true"
        ),
    }
    monkeypatch.setattr(incidents, "_open_incidents", lambda *_args, **_kwargs: [issue])
    calls = []
    monkeypatch.setattr(incidents, "_request_json", lambda *args, **kwargs: calls.append(args) or {})
    result = incidents.reconcile_incidents(
        api_url="https://api.github.com", repository="owner/repo", token="token",
        trace_path=trace_path, now=now,
    )
    assert result["recovered_issue_numbers"] == []
    assert not any(
        len(call) > 5 and call[3] == "PATCH" and call[4] == "issues/25" and call[5].get("state") == "closed"
        for call in calls
    )


def test_expected_event_suppression_remains_an_incident(monkeypatch, tmp_path):
    now = datetime(2026, 10, 16, 4, 0, tzinfo=UTC)
    trace = _trace("suppressed", detected=now, reason="unrecognized_sender_suppression")
    active = incidents._active_incidents(trace, now)
    assert len(active) == 1
    assert next(iter(active.values()))["reason"] == "unrecognized_sender_suppression"


def test_active_issue_keeps_previous_event_refs_when_new_event_joins(monkeypatch, tmp_path):
    now = datetime(2026, 10, 16, 4, 0, tzinfo=UTC)
    trace = _trace("partial", detected=now - timedelta(minutes=2), reason="recipient_receipt_partial")
    path = tmp_path / "trace.json"
    path.write_text(json.dumps(trace), encoding="utf-8")
    key = incidents._incident_group("recipient_receipt_partial", "public-summary-v4")[1]
    issue = {
        "number": 24,
        "title": f"{incidents.EVENT_ISSUE_TITLE_PREFIX} / official_event_delivery",
        "body": (
            f"{incidents.EVENT_INCIDENT_MARKER}{key}\n"
            f"First failure: {(now - timedelta(minutes=5)).isoformat()}\n"
            f"Next reminder at: {(now + timedelta(minutes=20)).isoformat()}\n"
            "Affected event count: 1\nEvent refs: prior-ref\nEvent refs complete: true"
        ),
    }
    monkeypatch.setattr(incidents, "_open_incidents", lambda *_args, **_kwargs: [issue])
    calls = []
    monkeypatch.setattr(incidents, "_request_json", lambda *args, **kwargs: calls.append(args) or {})
    incidents.reconcile_incidents(
        api_url="https://api.github.com", repository="owner/repo", token="token",
        trace_path=path, now=now,
    )
    patch = next(args[5] for args in calls if args[3] == "PATCH" and args[4] == "issues/24")
    assert "Affected event count: 2" in patch["body"]
    assert "Event refs: prior-ref, opaque-ref" in patch["body"]


def test_multi_event_incident_closes_only_when_every_reference_is_terminal(monkeypatch, tmp_path):
    now = datetime(2026, 10, 16, 4, 0, tzinfo=UTC)
    key = incidents._incident_group("recipient_receipt_partial", "public-summary-v4")[1]
    issue = {
        "number": 23,
        "title": f"{incidents.EVENT_ISSUE_TITLE_PREFIX} / official_event_delivery",
        "body": (
            f"{incidents.EVENT_INCIDENT_MARKER}{key}\n"
            "Affected event count: 2\n"
            "Event refs: first-ref, second-ref\n"
            "Event refs complete: true"
        ),
    }
    monkeypatch.setattr(incidents, "_open_incidents", lambda *_args, **_kwargs: [issue])
    calls = []
    monkeypatch.setattr(incidents, "_request_json", lambda *args, **kwargs: calls.append(args) or {})
    trace = _trace("delivered", detected=now)
    trace["events"] = [dict(trace["events"][0], event_ref="first-ref", expected=True)]
    path = tmp_path / "trace.json"
    path.write_text(json.dumps(trace), encoding="utf-8")
    result = incidents.reconcile_incidents(
        api_url="https://api.github.com", repository="owner/repo", token="token",
        trace_path=path, now=now,
    )
    assert result["recovered_issue_numbers"] == []
    assert calls == []

    trace["events"].append(dict(trace["events"][0], event_ref="second-ref"))
    path.write_text(json.dumps(trace), encoding="utf-8")
    result = incidents.reconcile_incidents(
        api_url="https://api.github.com", repository="owner/repo", token="token",
        trace_path=path, now=now + timedelta(minutes=1),
    )
    assert result["recovered_issue_numbers"] == [23]
    assert any(args[3] == "PATCH" and args[4] == "issues/23" and args[5]["state"] == "closed" for args in calls)


def test_incomplete_scan_never_closes_existing_incident(monkeypatch, tmp_path):
    now = datetime(2026, 10, 16, 4, 0, tzinfo=UTC)
    trace = _trace("partial", detected=now - timedelta(minutes=45), reason="sender_failed")
    trace["stages"]["scan"] = "failure"
    path = tmp_path / "trace.json"
    path.write_text(json.dumps({**trace, "events": []}), encoding="utf-8")
    issue = {"number": 12, "title": f"{incidents.EVENT_ISSUE_TITLE_PREFIX} / x", "body": f"{incidents.EVENT_INCIDENT_MARKER}stale-key"}
    monkeypatch.setattr(incidents, "_open_incidents", lambda *_args, **_kwargs: [issue])
    calls = []
    monkeypatch.setattr(incidents, "_request_json", lambda *args, **kwargs: calls.append(args) or {})
    result = incidents.reconcile_incidents(
        api_url="https://api.github.com", repository="owner/repo", token="token", trace_path=path, now=now,
    )
    assert result["diagnostic_complete"] is False
    assert result["recovered_issue_numbers"] == []
    assert calls == []


def test_central_event_incident_keeps_cadence_due_until_alert_terminal(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    monkeypatch.delenv("GITHUB_RUN_ATTEMPT", raising=False)
    now = datetime(2026, 10, 24, 4, 0, tzinfo=UTC)
    trace = _trace("summary_pending", detected=now - timedelta(minutes=11))
    path = tmp_path / "trace.json"
    path.write_text(json.dumps(trace), encoding="utf-8")
    calls = []
    monkeypatch.setattr(incidents, "_open_incidents", lambda *_args, **_kwargs: [])

    def request(_api, _repo, _token, method, endpoint, payload=None, **_kwargs):
        calls.append((method, endpoint, payload))
        if method == "POST" and endpoint == "issues":
            return {"number": 91}
        raise AssertionError((method, endpoint, payload))

    monkeypatch.setattr(incidents, "_request_json", request)
    result = incidents.reconcile_incidents(
        api_url="https://api.github.com", repository="owner/repo", token="token",
        trace_path=path, now=now, defer_notification_cadence=True,
    )

    assert result["opened_issue_numbers"] == [91]
    assert result["notification_cadence_confirmations"][0]["issue_number"] == 91
    assert result["notification_cadence_confirmations"][0]["next_reminder_at"] == "2026-10-24T04:30:00+00:00"
    assert "Next reminder at: 2026-10-24T04:00:00+00:00" in calls[0][2]["body"]
    assert "Alert pending consumer: local" in calls[0][2]["body"]


def test_placeholder_event_refs_never_count_as_recovery_evidence():
    refs, complete = incidents._issue_event_refs(
        "Affected event count: 1\nEvent refs: not available\nEvent refs complete: true"
    )
    assert refs == []
    assert complete is False

    refs, complete = incidents._issue_event_refs(
        "Affected event count: 0\nEvent refs: unknown\nEvent refs complete: true"
    )
    assert refs == []
    assert complete is False
