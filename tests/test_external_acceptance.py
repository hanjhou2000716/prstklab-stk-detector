from __future__ import annotations

import hashlib
import json

import pytest
import requests

from src.external_acceptance import capture


class _Response:
    def __init__(self, status: int, value, content: bytes | None = None):
        self.status_code = status
        self._value = value
        self.content = content

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
    artifact = b'{"market":"ok","snapshot_id":"market-1"}\n'
    return {
        "status": "ready",
        "release_id": "release-1",
        "market_snapshot_id": "market-1",
        "research_snapshot_id": "research-1",
        "event_snapshot_id": "event-1",
        "artifact_hashes": {"market.json": hashlib.sha256(artifact).hexdigest()},
        "artifact_paths": {"market.json": "data/market.json"},
        "_artifact_fixture": artifact,
    }


def test_capture_is_read_only_and_redacts_health_payload() -> None:
    manifest = _manifest()
    artifact = manifest.pop("_artifact_fixture")
    report = capture(
        railway_url="https://railway.example/",
        public_url="https://pages.example/app/",
        session=_Session([_Response(200, _health()), _Response(200, manifest), _Response(200, None, artifact)]),
    )
    assert report["status"] == "NEEDS_REVERIFY"
    assert "railway_gmail:configuration_missing" in report["blocking_reasons"]
    assert "railway_gdelt:failed" in report["blocking_reasons"]
    encoded = json.dumps(report, ensure_ascii=False)
    assert "private" not in encoded
    assert "private_token" not in encoded
    assert report["side_effects"] == {"telegram": False, "railway_write": False, "configuration_changed": False}
    assert report["pages"]["artifact_hash_count"] == 1
    assert report["pages"]["artifact_hash_audit"]["verified_count"] == 1
    assert report["schema_version"] == "1.0"
    assert report["gate_summary"]["railway_health"]["status"] == "needs_reverify"
    assert report["gate_summary"]["gmail_watch"]["status"] == "needs_reverify"
    assert report["gate_summary"]["pages_manifest"]["status"] == "pass"
    assert report["gate_summary"]["pages_artifacts"]["status"] == "pass"


def test_capture_passes_when_health_and_manifest_are_ready() -> None:
    health = {"status": "ok", "service": "monitor", "gmail": {"status": "no_new_content"}, "gdelt": {"status": "no_event"}, "delivery": {"status": "not_checked"}}
    manifest = _manifest()
    artifact = manifest.pop("_artifact_fixture")
    report = capture(
        railway_url="https://railway.example/",
        public_url="https://pages.example/",
        session=_Session([_Response(200, health), _Response(200, manifest), _Response(200, None, artifact)]),
    )
    assert report["status"] == "PASS"
    assert report["blocking_reasons"] == []
    assert all(gate["status"] == "pass" for gate in report["gate_summary"].values() if gate["status"] != "not_checked")
    assert report["gate_summary"]["delivery_receipt"]["status"] == "not_checked"


def test_capture_accepts_a_successful_delivery_receipt() -> None:
    health = {
        "status": "ok",
        "service": "monitor",
        "gmail": {"status": "healthy", "watch_status": "healthy"},
        "gdelt": {"status": "no_event"},
        "delivery": {
            "status": "delivered",
            "last_delivered_count": 1,
            "last_failed_count": 0,
        },
    }
    manifest = _manifest()
    artifact = manifest.pop("_artifact_fixture")
    report = capture(
        railway_url="https://railway.example/",
        public_url="https://pages.example/",
        session=_Session([_Response(200, health), _Response(200, manifest), _Response(200, None, artifact)]),
    )
    assert report["status"] == "PASS"
    assert report["blocking_reasons"] == []
    assert report["gate_summary"]["delivery_receipt"]["status"] == "pass"


def test_capture_fails_closed_when_delivery_storage_is_not_durable() -> None:
    health = {
        "status": "ok",
        "service": "monitor",
        "gmail": {"status": "healthy", "watch_status": "healthy"},
        "gdelt": {"status": "no_event"},
        "delivery": {
            "status": "delivered",
            "storage": {"status": "unknown", "durable_volume_detected": False},
        },
    }
    manifest = _manifest()
    artifact = manifest.pop("_artifact_fixture")
    report = capture(
        railway_url="https://railway.example/",
        public_url="https://pages.example/",
        session=_Session([_Response(200, health), _Response(200, manifest), _Response(200, None, artifact)]),
    )
    assert report["status"] == "NEEDS_REVERIFY"
    assert report["blocking_reasons"] == ["railway_delivery_persistence:unknown"]
    assert report["gate_summary"]["delivery_receipt"]["status"] == "needs_reverify"


def test_capture_distinguishes_configured_gmail_from_failed_watch() -> None:
    health = {
        "status": "ok",
        "service": "monitor",
        "gmail": {"status": "ready", "watch_status": "failed"},
        "gdelt": {"status": "no_event"},
        "delivery": {"status": "not_checked"},
    }
    manifest = _manifest()
    artifact = manifest.pop("_artifact_fixture")
    report = capture(
        railway_url="https://railway.example/",
        public_url="https://pages.example/",
        session=_Session([_Response(200, health), _Response(200, manifest), _Response(200, None, artifact)]),
    )
    assert report["status"] == "NEEDS_REVERIFY"
    assert report["blocking_reasons"] == ["railway_gmail_watch:failed"]


def test_capture_fails_closed_when_legacy_delivery_secret_requires_migration() -> None:
    health = {
        "status": "ok",
        "service": "monitor",
        "gmail": {"status": "no_new_content"},
        "gdelt": {"status": "no_event"},
        "delivery": {"status": "not_checked"},
        "runtime_config": {
            "canonical_name_present": False,
            "legacy_name_present": True,
            "active_name": "DELIVERY_STATUS_SHARED_SECRET",
            "migration_required": True,
            "secret_values_exposed": False,
        },
    }
    manifest = _manifest()
    artifact = manifest.pop("_artifact_fixture")
    report = capture(
        railway_url="https://railway.example/",
        public_url="https://pages.example/",
        session=_Session([_Response(200, health), _Response(200, manifest), _Response(200, None, artifact)]),
    )
    assert report["status"] == "NEEDS_REVERIFY"
    assert report["blocking_reasons"] == ["railway_runtime_config:secret_migration_required"]
    assert report["railway"]["health"]["runtime_config"]["secret_values_exposed"] is False


def test_capture_fails_closed_when_public_artifact_hash_mismatches() -> None:
    manifest = _manifest()
    manifest.pop("_artifact_fixture")
    report = capture(
        railway_url="https://railway.example/",
        public_url="https://pages.example/",
        session=_Session([
            _Response(200, {"gmail": {"status": "no_new_content"}, "gdelt": {"status": "no_event"}, "delivery": {"status": "not_checked"}}),
            _Response(200, manifest),
            _Response(200, None, b'{"market":"tampered"}\n'),
        ]),
    )
    assert report["status"] == "NEEDS_REVERIFY"
    assert report["pages"]["artifact_hash_audit"]["mismatch_count"] == 1
    assert report["blocking_reasons"] == ["pages_artifact_hash_mismatch:market.json"]


def test_capture_fails_closed_when_public_snapshot_identity_mismatches() -> None:
    manifest = _manifest()
    artifact = b'{"market":"ok","snapshot_id":"market-other"}\n'
    manifest["artifact_hashes"]["market.json"] = hashlib.sha256(artifact).hexdigest()
    manifest.pop("_artifact_fixture")
    report = capture(
        railway_url="https://railway.example/",
        public_url="https://pages.example/",
        session=_Session([
            _Response(200, {"gmail": {"status": "no_new_content"}, "gdelt": {"status": "no_event"}, "delivery": {"status": "not_checked"}}),
            _Response(200, manifest),
            _Response(200, None, artifact),
        ]),
    )
    assert report["status"] == "NEEDS_REVERIFY"
    assert report["pages"]["artifact_hash_audit"]["snapshot_mismatch_count"] == 1
    assert report["blocking_reasons"] == ["pages_artifact_snapshot_mismatch:market.json"]


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
    assert report["gate_summary"]["railway_health"]["status"] == "needs_reverify"
    assert report["gate_summary"]["pages_manifest"]["status"] == "needs_reverify"
    assert report["gate_summary"]["pages_artifacts"]["status"] == "not_checked"
