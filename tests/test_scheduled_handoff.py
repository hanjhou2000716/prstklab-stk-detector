from datetime import datetime
from unittest.mock import patch

from src.scheduled_handoff import (
    HandoffError,
    build_handoff_payload,
    dispatch_and_wait,
    handoff_deadline,
    validate_handoff_parent,
)


def _context():
    return {
        "scheduled_slot": "us_premarket",
        "scheduled_for_at": "2026-09-25T09:00:00-04:00",
        "contract_status": "valid",
        "delivery_intent": "notify_candidate",
        "dispatch_trace_id": "trace-abc",
    }


def _payload():
    return build_handoff_payload(
        _context(), parent_run_id=1234, parent_sha="a" * 40,
        target_sha="b" * 40, now=datetime.fromisoformat("2026-09-25T13:05:00+00:00"),
    )


def test_handoff_is_fixed_to_original_slot_and_expires_at_nyse_open():
    payload = _payload()["client_payload"]
    assert payload["scheduled_for_at"] == "2026-09-25T09:00:00-04:00"
    assert payload["handoff_attempt"] == 1
    assert payload["notify"] is True
    assert payload["force"] is False
    assert handoff_deadline(_context()) == datetime.fromisoformat("2026-09-25T13:30:00+00:00")


def test_handoff_refuses_expired_window_and_non_notification_slot():
    with patch("src.scheduled_handoff._utc_now", return_value=datetime.fromisoformat("2026-09-25T13:30:00+00:00")):
        try:
            build_handoff_payload(_context(), parent_run_id=1234, parent_sha="a" * 40, target_sha="b" * 40)
        except HandoffError as exc:
            assert str(exc) == "handoff_window_expired"
        else:
            raise AssertionError("handoff must stop at the original open deadline")
    context = {**_context(), "delivery_intent": "expected_skip"}
    try:
        build_handoff_payload(
            context, parent_run_id=1234, parent_sha="a" * 40,
            target_sha="b" * 40, now=datetime.fromisoformat("2026-09-25T13:05:00+00:00"),
        )
    except HandoffError as exc:
        assert str(exc) == "handoff_delivery_not_required"
    else:
        raise AssertionError("only an expected report can be handed off")


def test_parent_validation_binds_repository_workflow_slot_and_current_revision():
    client_payload = _payload()["client_payload"]
    parent = {
        "id": 1234,
        "path": ".github/workflows/scheduled-brief.yml",
        "name": "Scheduled market brief",
        "head_branch": "main",
        "head_sha": "a" * 40,
        "event": "schedule",
        "status": "in_progress",
        "created_at": "2026-09-25T13:01:00Z",
        "repository": {"full_name": "owner/repo"},
    }
    with patch("src.scheduled_handoff._http_json", return_value=(200, parent)):
        result = validate_handoff_parent(
            client_payload, repository="owner/repo", token="not-a-real-token",
            now=datetime.fromisoformat("2026-09-25T13:05:00+00:00"), current_sha="b" * 40,
        )
    assert result["valid"] is True
    with patch("src.scheduled_handoff._http_json", return_value=(200, parent)):
        result = validate_handoff_parent(
            client_payload, repository="owner/repo", token="not-a-real-token",
            now=datetime.fromisoformat("2026-09-25T13:05:00+00:00"), current_sha="c" * 40,
        )
    assert result == {"valid": False, "reason": "handoff_target_revision_mismatch"}


def test_replayed_handoff_from_completed_parent_is_rejected():
    client_payload = _payload()["client_payload"]
    parent = {
        "id": 1234, "path": ".github/workflows/scheduled-brief.yml",
        "name": "Scheduled market brief", "head_branch": "main", "head_sha": "a" * 40,
        "event": "schedule", "status": "completed", "created_at": "2026-09-25T13:01:00Z",
        "repository": {"full_name": "owner/repo"},
    }
    with patch("src.scheduled_handoff._http_json", return_value=(200, parent)):
        result = validate_handoff_parent(
            client_payload, repository="owner/repo", token="not-a-real-token",
            now=datetime.fromisoformat("2026-09-25T13:05:00+00:00"), current_sha="b" * 40,
        )
    assert result == {"valid": False, "reason": "handoff_parent_not_active"}


def test_unknown_dispatch_result_is_reconciled_without_a_second_post():
    payload = _payload()
    handoff_id = payload["client_payload"]["handoff_id"]
    calls = []

    def fake_request(url, *, method, token, body=None):
        calls.append(method)
        if method == "POST":
            raise HandoffError("handoff_request_outcome_unknown_TimeoutError")
        return 200, {"workflow_runs": [{
            "name": "Scheduled market brief", "path": ".github/workflows/scheduled-brief.yml",
            "head_branch": "main", "event": "repository_dispatch",
            "display_title": f"Scheduled market brief / {handoff_id}", "status": "completed",
            "conclusion": "success", "id": 5678, "head_sha": "b" * 40,
        }]}

    with patch("src.scheduled_handoff._http_json", side_effect=fake_request):
        result = dispatch_and_wait(
            payload, repository="owner/repo", token="not-a-real-token",
            deadline=datetime.fromisoformat("2026-09-25T13:30:00+00:00"),
            now_fn=lambda: datetime.fromisoformat("2026-09-25T13:10:00+00:00"),
            sleep_fn=lambda _seconds: None,
        )
    assert result["status"] == "delivered"
    assert result["request_outcome"] == "unknown"
    assert calls.count("POST") == 1
    assert calls.count("GET") == 1


def test_explicit_dispatch_rejection_does_not_search_or_retry():
    payload = _payload()
    calls = []

    def rejected(url, *, method, token, body=None):
        calls.append(method)
        raise HandoffError("handoff_request_rejected_http_422")

    with patch("src.scheduled_handoff._http_json", side_effect=rejected):
        result = dispatch_and_wait(
            payload, repository="owner/repo", token="not-a-real-token",
            deadline=datetime.fromisoformat("2026-09-25T13:30:00+00:00"),
        )
    assert result["status"] == "rejected"
    assert calls == ["POST"]
