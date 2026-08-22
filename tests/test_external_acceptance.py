from __future__ import annotations

import json

import pytest
import requests

from src.external_acceptance import capture


class _Response:
    def __init__(self, status: int, value):
        self.status_code = status
        self._value = value

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("http failure")

    def json(self):
        return self._value


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)

    def get(self, *_args, **_kwargs):
        return self.responses.pop(0)


def _health():
    return {
        "status": "ok",
        "service": "prstk-jin10-monitor",
        "gmail": {"status": "configuration_missing", "missing": ["GMAIL_WATCH_TOPIC"], "raw_body": "private"},
        "gdelt": {"status": "failed", "error": "HTTP_429", "health_dispatch_error": "HTTP_403"},
        "delivery": {"status": "not_checked", "last_trace_id": "trace"},
        "runtime_config": {"secret_values_exposed": False, "active_name": "DELIVERY_STATUS_SHARED_SECRET"},
        "private_token": "must not be copied",
    }


def _manifest():
    return {
        "status": "ready",
        "release_id": "release-1",
        "market_snapshot_id": "market-1",
        "research_snapshot_id": "research-1",
        "event_snapshot_id": "event-1",
        "artifact_hashes": {"market.json": "a" * 64},
    }


def test_capture_is_read_only_and_redacts_health_payload() -> None:
    report = capture(
        railway_url="https://railway.example/",
        public_url="https://pages.example/app/",
        session=_Session([_Response(200, _health()), _Response(200, _manifest())]),
    )
    assert report["status"] == "NEEDS_REVERIFY"
    assert "railway_gmail:configuration_missing" in report["blocking_reasons"]
    assert "railway_gdelt:failed" in report["blocking_reasons"]
    encoded = json.dumps(report, ensure_ascii=False)
    assert "private" not in encoded
    assert "private_token" not in encoded
    assert report["side_effects"] == {"telegram": False, "railway_write": False, "configuration_changed": False}
    assert report["pages"]["artifact_hash_count"] == 1


def test_capture_passes_when_health_and_manifest_are_ready() -> None:
    health = {"status": "ok", "service": "monitor", "gmail": {"status": "no_new_content"}, "gdelt": {"status": "no_event"}, "delivery": {"status": "not_checked"}}
    report = capture(
        railway_url="https://railway.example/",
        public_url="https://pages.example/",
        session=_Session([_Response(200, health), _Response(200, _manifest())]),
    )
    assert report["status"] == "PASS"
    assert report["blocking_reasons"] == []


def test_capture_rejects_non_https_urls() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        capture(railway_url="http://railway.example/", public_url="https://pages.example/")


def test_capture_marks_http_or_invalid_json_as_needs_reverify() -> None:
    report = capture(
        railway_url="https://railway.example/",
        public_url="https://pages.example/",
        session=_Session([_Response(429, {}), _Response(200, ["not", "an", "object"])]),
    )
    assert report["status"] == "NEEDS_REVERIFY"
    assert any(reason.startswith("railway_health_unavailable:") for reason in report["blocking_reasons"])
    assert any(reason.startswith("pages_manifest_unavailable:") for reason in report["blocking_reasons"])
