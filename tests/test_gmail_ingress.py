import base64
import json

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from src.gmail_ingress import (
    GmailCursor,
    GmailIngressError,
    accept_history_ids,
    decode_push_body,
    replay_decision,
    validate_push_headers,
)


def _body(payload: dict) -> bytes:
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    return json.dumps({"message": {"data": encoded, "publishTime": "2026-08-12T01:00:00Z"}, "subscription": "sub"}).encode()


def test_push_requires_authenticated_identity() -> None:
    with pytest.raises(GmailIngressError, match="authenticated"):
        validate_push_headers(
            authorization=None, audience="a", expected_audience="a",
            service_account="s", expected_service_account="s",
        )


def test_decode_push_is_bounded_and_metadata_only() -> None:
    result = decode_push_body(_body({"emailAddress": "bot@example.com", "historyId": 123}))
    assert result["history_id"] == "123"
    assert "body" not in result


def test_invalid_payload_fails_closed() -> None:
    with pytest.raises(GmailIngressError, match="invalid"):
        decode_push_body(b"not-json")


def test_history_ids_are_idempotent() -> None:
    cursor = GmailCursor()
    assert accept_history_ids(cursor, ["1", "2", "2"]) == ["1", "2"]
    assert accept_history_ids(cursor, ["2", "3"]) == ["3"]
    assert cursor.last_history_id == "3"


def test_stale_cursor_requests_full_sync() -> None:
    assert replay_decision(cursor_history_id="10", requested_start_id="9", history_invalid=False)["mode"] == "full_sync"
    assert replay_decision(cursor_history_id="10", requested_start_id="10", history_invalid=False)["mode"] == "incremental"


def test_cursor_health_matches_schema() -> None:
    schema = json.loads(open("schemas/gmail-watch.schema.json", encoding="utf-8").read())
    health = GmailCursor(watch_expiration="2026-08-13T01:00:00+00:00").as_public_health()
    assert not list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(health))
