import json
from datetime import UTC, datetime, timedelta

import pytest

from scripts import official_event_incidents as incidents


def _trace(status: str, *, detected: datetime, reason: str = "summary_semantics_incomplete") -> dict:
    return {
        "schema_version": "official-event-trace-v1",
        "workflow_run_id": "123",
        "workflow_sha": "a" * 40,
        "stages": {"scan": "success"},
        "events": [{
            "event_ref": "opaque-ref", "expected": True, "status": status,
            "source_type": "financialjuice",
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


def test_ordinary_content_incomplete_is_never_reclassified_as_fj_timeout(monkeypatch, tmp_path):
    now = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)
    trace = _trace("content_incomplete", detected=now - timedelta(hours=1))
    trace["events"][0]["source_type"] = "mops"
    trace["events"][0]["reason"] = "content_incomplete"
    path = tmp_path / "trace.json"
    path.write_text(json.dumps(trace), encoding="utf-8")
    monkeypatch.setattr(incidents, "_open_incidents", lambda *_args, **_kwargs: [])
    calls = []
    monkeypatch.setattr(incidents, "_request_json", lambda *args, **kwargs: calls.append((args, kwargs)) or {"number": 98})

    incidents.reconcile_incidents(
        api_url="https://api.github.com", repository="owner/repo", token="token",
        trace_path=path, now=now,
    )

    assert calls
    assert "Root cause: content_incomplete" in calls[0][0][5]["body"]
    assert "priority_summary_timeout" not in calls[0][0][5]["body"]


def test_non_fj_summary_wait_keeps_original_reason_after_ten_minutes():
    now = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)
    trace = _trace("summary_pending", detected=now - timedelta(minutes=20), reason="summary_semantics_incomplete")
    trace["events"][0]["source_type"] = "mops"
    grouped = incidents._active_incidents(trace, now)
    assert len(grouped) == 1
    assert next(iter(grouped.values()))["reason"] == "summary_semantics_incomplete"


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
    assert not any(args[3] == "POST" and args[4].endswith("/comments") for args, _ in calls)
    assert any(args[3] == "PATCH" and args[4] == "issues/11" for args, _ in calls)

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


def test_duplicate_incident_issues_are_consolidated_without_losing_unknown_evidence(monkeypatch, tmp_path):
    now = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
    reason = "recipient_receipt_partial"
    contract = "public-summary-v4"
    key = incidents._incident_group(reason, contract)[1]
    older = {
        "number": 39,
        "created_at": "2026-10-26T07:50:57Z",
        "title": f"{incidents.EVENT_ISSUE_TITLE_PREFIX} / official_event_delivery",
        "body": (
            f"{incidents.EVENT_INCIDENT_MARKER}{key}\n"
            "Component: official_event_delivery\n"
            f"Root cause: {reason}\nSummary contract: {contract}\n"
            "Affected event count: 0\nEvent refs: not available\nEvent refs complete: false\n"
            "First failure: 2026-10-25T15:20:18+00:00\n"
            "Latest run: 40206088425 (e" + "0" * 39 + ")"
        ),
    }
    newer = {
        "number": 40,
        "created_at": "2026-10-26T07:51:03Z",
        "title": older["title"],
        "body": (
            f"{incidents.EVENT_INCIDENT_MARKER}{key}\n"
            "Component: official_event_delivery\n"
            f"Root cause: {reason}\nSummary contract: {contract}\n"
            "Affected event count: 0\nEvent refs: not available\nEvent refs complete: false\n"
            "First failure: 2026-10-25T15:46:08+00:00\n"
            "Latest run: 40207665385 (e" + "0" * 39 + ")"
        ),
    }
    path = tmp_path / "trace.json"
    path.write_text(json.dumps(_trace("partial", detected=now - timedelta(minutes=45), reason=reason)), encoding="utf-8")
    monkeypatch.setattr(incidents, "_open_incidents", lambda *_args, **_kwargs: [newer, older])
    calls = []

    def request(_api, _repo, _token, method, endpoint, payload=None, **_kwargs):
        calls.append((method, endpoint, payload))
        return {}

    monkeypatch.setattr(incidents, "_request_json", request)
    result = incidents.reconcile_incidents(
        api_url="https://api.github.com", repository="owner/repo", token="token",
        trace_path=path, now=now,
    )

    assert result["diagnostic_complete"] is True
    assert result["incident_active"] is True
    assert result["consolidated_issue_groups"] == [{
        "marker": key,
        "canonical_issue_number": 39,
        "duplicate_issue_numbers": [40],
        "source_run_ids": ["40206088425", "40207665385"],
        "event_refs_complete": False,
    }]
    duplicate_body = next(payload["body"] for method, endpoint, payload in calls if method == "PATCH" and endpoint == "issues/40" and "body" in payload)
    assert "Duplicate of: #39" in duplicate_body
    assert "Event refs: not available" in duplicate_body
    assert any(
        method == "PATCH" and endpoint == "issues/40"
        and payload == {"state": "closed", "state_reason": "not_planned"}
        for method, endpoint, payload in calls
    )
    canonical_body = next(payload["body"] for method, endpoint, payload in calls if method == "PATCH" and endpoint == "issues/39" and "body" in payload)
    assert "Consolidated issue numbers: 39, 40" in canonical_body
    assert "Consolidated source runs: 40206088425, 40207665385" in canonical_body
    assert "Event refs complete: false" in canonical_body
    evidence = json.loads(incidents._field(canonical_body, "Consolidated issue evidence"))
    assert evidence == [
        {
            "issue_number": 39,
            "first_failure_at": "2026-10-25T15:20:18+00:00",
            "source_run_ids": ["40206088425"],
            "comments_preserved_on_issue": 39,
        },
        {
            "issue_number": 40,
            "first_failure_at": "2026-10-25T15:46:08+00:00",
            "source_run_ids": ["40207665385"],
            "comments_preserved_on_issue": 40,
        },
    ]

    refs, complete = incidents._issue_event_refs(
        "Affected event count: 0\nEvent refs: unknown\nEvent refs complete: true"
    )
    assert refs == []
    assert complete is False


def test_conflicting_duplicate_group_does_not_block_independent_incident(monkeypatch, tmp_path):
    now = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
    active_trace = _trace("partial", detected=now - timedelta(minutes=45), reason="recipient_receipt_partial")
    active_key = incidents._incident_group("recipient_receipt_partial", "public-summary-v4")[1]
    conflict_key = "f" * 24

    def row(number, reason):
        return {
            "number": number,
            "title": f"{incidents.EVENT_ISSUE_TITLE_PREFIX} / official_event_delivery",
            "body": (
                f"{incidents.EVENT_INCIDENT_MARKER}{conflict_key}\n"
                "Component: official_event_delivery\n"
                f"Root cause: {reason}\nSummary contract: public-summary-v4\n"
                "Affected event count: 0\nEvent refs: not available\nEvent refs complete: false"
            ),
        }

    active_issue = {
        "number": 51,
        "title": f"{incidents.EVENT_ISSUE_TITLE_PREFIX} / official_event_delivery",
        "body": (
            f"{incidents.EVENT_INCIDENT_MARKER}{active_key}\n"
            "Component: official_event_delivery\nRoot cause: recipient_receipt_partial\n"
            "Summary contract: public-summary-v4\nAffected event count: 1\n"
            "Event refs: opaque-ref\nEvent refs complete: true\n"
            f"First failure: {(now - timedelta(minutes=45)).isoformat()}\n"
            f"Next reminder at: {(now + timedelta(hours=1)).isoformat()}"
        ),
    }
    path = tmp_path / "trace.json"
    path.write_text(json.dumps(active_trace), encoding="utf-8")
    monkeypatch.setattr(incidents, "_open_incidents", lambda *_args, **_kwargs: [row(49, "cause_a"), row(50, "cause_b"), active_issue])
    calls = []
    monkeypatch.setattr(incidents, "_request_json", lambda *args, **kwargs: calls.append(args) or {})

    result = incidents.reconcile_incidents(
        api_url="https://api.github.com", repository="owner/repo", token="token",
        trace_path=path, now=now,
    )

    assert result["diagnostic_complete"] is False
    assert result["unresolved_issue_groups"] == [{
        "marker": conflict_key,
        "issue_numbers": [49, 50],
        "reason": "official_event_incident_duplicate_identity_conflict",
    }]
    assert any(len(args) > 4 and args[3] == "PATCH" and args[4] == "issues/51" for args in calls)


def test_non_fj_summary_and_expired_rows_do_not_reopen_alert_cycles():
    now = datetime(2026, 10, 28, 10, 0, tzinfo=UTC)
    base = {"expected": True, "event_ref": "evt-1", "summary_contract_version": "v1", "reason": "content_incomplete"}
    trace = {"events": [{**base, "status": "summary_pending", "source_type": "mops", "first_detected_at": (now - timedelta(minutes=40)).isoformat()}], "stages": {}}
    active = incidents._active_incidents(trace, now)
    assert all(item["reason"] != "priority_summary_timeout" for item in active.values())
    trace["events"] = [{**base, "status": "expired", "source_type": "financialjuice", "first_detected_at": (now - timedelta(hours=1)).isoformat()}]
    assert incidents._active_incidents(trace, now) == {}


def test_expired_event_stops_reminder_cycle_without_claiming_recovery(monkeypatch, tmp_path):
    now = datetime(2026, 10, 28, 10, 0, tzinfo=UTC)
    trace = _trace("expired", detected=now - timedelta(hours=1))
    trace["events"][0]["expected"] = True
    path = tmp_path / "expired-trace.json"
    path.write_text(json.dumps(trace), encoding="utf-8")
    marker = incidents._incident_group("priority_summary_timeout", "public-summary-v4")[1]
    issue = {
        "number": 91,
        "title": f"{incidents.EVENT_ISSUE_TITLE_PREFIX} / financialjuice_summary",
        "body": (
            f"{incidents.EVENT_INCIDENT_MARKER}{marker}\n"
            "Affected event count: 1\nEvent refs: opaque-ref\nEvent refs complete: true\n"
            "Next reminder at: 2026-10-28T09:30:00+00:00\n"
            "Alert pending consumer: 123/1\nAlert pending since: 2026-10-28T09:00:00+00:00"
        ),
    }
    calls = []
    monkeypatch.setattr(incidents, "_open_incidents", lambda *_args, **_kwargs: [issue])
    monkeypatch.setattr(incidents, "_request_json", lambda *args, **kwargs: calls.append(args) or {})

    result = incidents.reconcile_incidents(
        api_url="https://api.github.com", repository="owner/repo", token="token",
        trace_path=path, now=now, defer_notification_cadence=True,
    )

    assert result["reminded_issue_numbers"] == []
    assert result["recovered_issue_numbers"] == []
    patch = next(args[5] for args in calls if args[3] == "PATCH")
    assert "Lifecycle: historical_diagnosed" in patch["body"]
    assert "Next reminder at:" not in patch["body"]
    assert "Alert pending consumer:" not in patch["body"]


def test_unreferenced_historical_issue_is_parked_and_new_attributable_impact_reactivates(monkeypatch, tmp_path):
    now = datetime(2026, 10, 29, 13, 0, tzinfo=UTC)
    key = incidents._incident_group("release_preparation_failed", "unknown")[1]
    issue = {
        "number": 1054, "title": f"{incidents.EVENT_ISSUE_TITLE_PREFIX} / official_event_delivery",
        "body": (
            f"{incidents.EVENT_INCIDENT_MARKER}{key}\nRoot cause: release_preparation_failed\n"
            "Summary contract: unknown\nAffected event count: 0\nEvent refs: not available\n"
            "Event refs complete: false\nFirst failure: 2026-10-19T14:19:18+00:00\n"
            "Next reminder at: 2026-10-29T12:30:00+00:00\n"
            "Alert pending consumer: 456/1\nAlert pending since: 2026-10-29T12:00:00+00:00"
        ),
    }
    trace = _trace("no_event", detected=now)
    trace["events"] = []
    path = tmp_path / "trace.json"
    path.write_text(json.dumps(trace), encoding="utf-8")
    calls = []
    monkeypatch.setattr(incidents, "_open_incidents", lambda *a, **k: [issue])

    def request(*args, **kwargs):
        calls.append(args)
        issue["body"] = args[5]["body"]
        return {}

    monkeypatch.setattr(incidents, "_request_json", request)
    result = incidents.reconcile_incidents(
        api_url="https://api.github.com", repository="owner/repo", token="token",
        trace_path=path, now=now, defer_notification_cadence=True,
    )
    assert not result["recovered_issue_numbers"]
    assert not result["notification_cadence_confirmations"]
    assert result["historical_pending_issue_numbers"] == [1054]
    assert "Lifecycle: historical_pending_verification" in issue["body"]
    assert "Next reminder at:" not in issue["body"]
    assert "Alert pending consumer:" not in issue["body"]
    assert "First failure: 2026-10-19T14:19:18+00:00" in issue["body"]
    before = len(calls)
    incidents.reconcile_incidents(
        api_url="https://api.github.com", repository="owner/repo", token="token", trace_path=path, now=now,
    )
    assert len(calls) == before

    trace = _trace("ready", detected=now, reason="candidate_ready")
    trace["events"][0]["summary_contract_version"] = "unknown"
    trace["stages"].update({"queue": "acquired", "prepare": "failed"})
    path.write_text(json.dumps(trace), encoding="utf-8")
    result = incidents.reconcile_incidents(
        api_url="https://api.github.com", repository="owner/repo", token="token",
        trace_path=path, now=now, defer_notification_cadence=True,
    )
    assert result["incident_active"] is True
    assert result["reminded_issue_numbers"] == [1054]
    assert "Lifecycle: historical_pending_verification" not in issue["body"]
    assert "opaque-ref" in issue["body"]
    assert "Alert pending consumer:" in issue["body"]


@pytest.mark.parametrize("first_age,refs,scan", [
    (10, "not available", "success"),
    (60, "known-event", "success"),
    (60, "not available", "failed"),
])
def test_historical_policy_keeps_recent_or_attributable_or_incomplete_scan_incidents(
    monkeypatch, tmp_path, first_age, refs, scan,
):
    now = datetime(2026, 10, 29, 13, 0, tzinfo=UTC)
    issue = {
        "number": 1054, "title": f"{incidents.EVENT_ISSUE_TITLE_PREFIX} / official_event_delivery",
        "body": (
            f"{incidents.EVENT_INCIDENT_MARKER}{'f' * 24}\n"
            f"First failure: {(now - timedelta(minutes=first_age)).isoformat()}\n"
            f"Event refs: {refs}\nEvent refs complete: false\n"
            "Next reminder at: 2026-10-29T12:30:00+00:00"
        ),
    }
    trace = _trace("no_event", detected=now)
    trace["events"] = []
    trace["stages"]["scan"] = scan
    path = tmp_path / "trace.json"
    path.write_text(json.dumps(trace), encoding="utf-8")
    calls = []
    monkeypatch.setattr(incidents, "_open_incidents", lambda *a, **k: [issue])
    monkeypatch.setattr(incidents, "_request_json", lambda *a, **k: calls.append(a) or {})
    result = incidents.reconcile_incidents(
        api_url="https://api.github.com", repository="owner/repo", token="token", trace_path=path, now=now,
    )
    assert result["historical_pending_issue_numbers"] == []
    assert calls == []
