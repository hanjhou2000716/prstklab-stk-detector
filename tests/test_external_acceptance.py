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


def test_capture_accepts_healthy_worker_when_railway_is_optional() -> None:
    """A healthy zero-cost Worker keeps delivery available during Railway outage."""
    manifest = _manifest()
    artifact = manifest.pop("_artifact_fixture")
    report = capture(
        railway_url="https://railway.example/",
        worker_url="https://worker.example/",
        public_url="https://pages.example/",
        session=_Session([
            _Response(404, {}),
            _Response(200, {"ok": True, "status": "healthy", "database": "ok"}),
            _Response(200, manifest),
            _Response(200, None, artifact),
        ]),
    )
    assert report["status"] == "PASS"
    assert report["warnings"] == ["railway_optional_unavailable"]
    assert report["worker"]["health"]["status"] == "healthy"
    assert report["gate_summary"]["worker_health"]["status"] == "pass"
    assert report["gate_summary"]["railway_health"]["status"] == "optional_unavailable"
    assert report["gate_summary"]["external_observations"]["status"] == "optional_unavailable"


def test_capture_does_not_hide_railway_source_failure_when_worker_is_healthy() -> None:
    manifest = _manifest()
    artifact = manifest.pop("_artifact_fixture")
    report = capture(
        railway_url="https://railway.example/",
        worker_url="https://worker.example/",
        public_url="https://pages.example/",
        session=_Session([
            _Response(200, {
                "status": "ok",
                "gmail": {"status": "healthy"},
                "gdelt": {"status": "failed"},
                "delivery": {"status": "not_checked"},
            }),
            _Response(200, {"ok": True, "status": "healthy"}),
            _Response(200, manifest),
            _Response(200, None, artifact),
        ]),
    )
    assert report["status"] == "NEEDS_REVERIFY"
    assert "railway_gdelt:failed" in report["blocking_reasons"]


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


def test_capture_requires_restart_continuity_for_durable_delivery() -> None:
    health = {
        "status": "ok",
        "service": "monitor",
        "gmail": {"status": "healthy", "watch_status": "healthy"},
        "gdelt": {"status": "no_event"},
        "delivery": {
            "status": "delivered",
            "last_delivered_count": 1,
            "last_failed_count": 0,
            "storage": {
                "status": "ready",
                "durable_volume_detected": True,
                "restart_continuity": {"status": "not_verified"},
            },
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
    assert "railway_delivery_persistence:restart_continuity_not_verified" in report["blocking_reasons"]
    assert report["railway"]["health"]["delivery"]["storage"]["restart_continuity"]["status"] == "not_verified"


def test_capture_accepts_verified_restart_continuity() -> None:
    health = {
        "status": "ok",
        "service": "monitor",
        "gmail": {
            "status": "healthy",
            "watch_status": "healthy",
            "storage": {"status": "ready", "restart_continuity": {"status": "verified"}},
        },
        "gdelt": {"status": "no_event"},
        "delivery": {
            "status": "delivered",
            "last_delivered_count": 1,
            "last_failed_count": 0,
            "storage": {"status": "ready", "restart_continuity": {"status": "verified"}},
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


def test_capture_records_sanitized_external_observation_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAILWAY_STATUS_SHARED_SECRET", "acceptance-secret")
    health = {
        "status": "ok",
        "service": "monitor",
        "gmail": {"status": "healthy", "watch_status": "active"},
        "gdelt": {"status": "no_event"},
        "delivery": {"status": "not_checked"},
    }
    manifest = _manifest()
    artifact = manifest.pop("_artifact_fixture")
    identity_hash = hashlib.sha256(
        json.dumps(
            [{"observation_id": "obs-1", "source": "financialjuice"}],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    manifest.update({
        "external_observation_count": 1,
        "external_observation_ids_hash": identity_hash,
        "external_observation_sources": ["financialjuice"],
        "external_observation_status": "ready",
    })
    report = capture(
        railway_url="https://railway.example/",
        public_url="https://pages.example/",
        session=_Session([
            _Response(200, health),
            _Response(200, {
                "status": "ready",
                "observations": [{
                    "public_safe": True,
                    "observation_id": "obs-1",
                    "source": "financialjuice",
                    "fetched_at": "2026-08-25T01:00:00+00:00",
                }],
            }),
            _Response(200, manifest),
            _Response(200, None, artifact),
        ]),
    )
    assert report["external_observations"] == {
        "http_status": 200,
        "status": "ready",
        "count": 1,
        "rejected_count": 0,
        "sources": ["financialjuice"],
        "latest_fetched_at": "2026-08-25T01:00:00+00:00",
        "observation_ids_hash": identity_hash,
    }
    assert report["gate_summary"]["external_observations"]["status"] == "pass"
    encoded = json.dumps(report, ensure_ascii=False)
    assert "acceptance-secret" not in encoded


def test_capture_rejects_external_observations_not_bound_to_public_release(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAILWAY_STATUS_SHARED_SECRET", "acceptance-secret")
    manifest = _manifest()
    artifact = manifest.pop("_artifact_fixture")
    report = capture(
        railway_url="https://railway.example/",
        public_url="https://pages.example/",
        session=_Session([
            _Response(200, {"gmail": {"status": "healthy"}, "gdelt": {"status": "no_event"}, "delivery": {"status": "not_checked"}}),
            _Response(200, {"status": "ready", "observations": [{
                "public_safe": True,
                "observation_id": "obs-unpublished",
                "source": "financialjuice",
                "fetched_at": "2026-08-25T01:00:00+00:00",
            }]}),
            _Response(200, manifest),
            _Response(200, None, artifact),
        ]),
    )
    assert report["status"] == "NEEDS_REVERIFY"
    assert report["gate_summary"]["external_observations"]["status"] == "needs_reverify"
    assert "pages_external_observations:manifest_status_missing" in report["blocking_reasons"]


def test_capture_marks_external_observation_failure_without_inventing_events(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAILWAY_STATUS_SHARED_SECRET", "acceptance-secret")
    manifest = _manifest()
    artifact = manifest.pop("_artifact_fixture")
    report = capture(
        railway_url="https://railway.example/",
        public_url="https://pages.example/",
        session=_Session([
            _Response(200, {"gmail": {"status": "no_new_content"}, "gdelt": {"status": "no_event"}, "delivery": {"status": "not_checked"}}),
            _Response(403, {}),
            _Response(200, manifest),
            _Response(200, None, artifact),
        ]),
    )
    assert report["external_observations"]["status"] == "failed"
    assert report["gate_summary"]["external_observations"]["status"] == "needs_reverify"
    assert "railway_observations:HTTPError" in report["blocking_reasons"]


def test_capture_rejects_private_rows_from_observation_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAILWAY_STATUS_SHARED_SECRET", "acceptance-secret")
    manifest = _manifest()
    artifact = manifest.pop("_artifact_fixture")
    report = capture(
        railway_url="https://railway.example/",
        public_url="https://pages.example/",
        session=_Session([
            _Response(200, {"gmail": {"status": "no_new_content"}, "gdelt": {"status": "no_event"}, "delivery": {"status": "not_checked"}}),
            _Response(200, {"status": "ready", "observations": [{
                "public_safe": True,
                "observation_id": "obs-private",
                "source": "creator",
                "body": "private body",
            }]}),
            _Response(200, manifest),
            _Response(200, None, artifact),
        ]),
    )
    assert report["external_observations"]["count"] == 0
    assert report["external_observations"]["rejected_count"] == 1
    assert report["gate_summary"]["external_observations"]["status"] == "needs_reverify"
    assert "private body" not in json.dumps(report, ensure_ascii=False)


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


def test_capture_fails_closed_when_news_artifact_is_from_another_release() -> None:
    manifest = _manifest()
    market_artifact = manifest.pop("_artifact_fixture")
    news_artifact = b'{"snapshot_id":"news-other","market_snapshot_id":"market-1","status":"no_event"}\n'
    manifest.update({
        "news_snapshot_id": "news-1",
        "news_status": "no_event",
        "artifact_hashes": {
            **manifest["artifact_hashes"],
            "news.json": hashlib.sha256(news_artifact).hexdigest(),
        },
        "artifact_paths": {
            **manifest["artifact_paths"],
            "news.json": "data/news.json",
        },
    })
    report = capture(
        railway_url="https://railway.example/",
        public_url="https://pages.example/",
        session=_Session([
            _Response(200, {"gmail": {"status": "no_new_content"}, "gdelt": {"status": "no_event"}, "delivery": {"status": "not_checked"}}),
            _Response(200, manifest),
            _Response(200, None, market_artifact),
            _Response(200, None, news_artifact),
        ]),
    )
    assert report["status"] == "NEEDS_REVERIFY"
    assert report["pages"]["artifact_hash_audit"]["lineage_mismatch_count"] == 1
    assert "pages_artifact_lineage_mismatch:news.json:snapshot_id" in report["blocking_reasons"]


def test_capture_fails_closed_when_creator_public_artifact_is_not_bound() -> None:
    manifest = _manifest()
    market_artifact = manifest.pop("_artifact_fixture")
    creator_artifact = b'{"snapshot_id":"creator-other","parent_release_id":"release-1","market_snapshot_id":"market-1","research_snapshot_id":"research-1","event_snapshot_id":"event-1","status":"ready"}\n'
    manifest.update({
        "creator_snapshot_id": "creator-1",
        "creator_public_status": "ready",
        "artifact_hashes": {
            **manifest["artifact_hashes"],
            "creator-insights.json": hashlib.sha256(creator_artifact).hexdigest(),
        },
        "artifact_paths": {
            **manifest["artifact_paths"],
            "creator-insights.json": "data/creator-insights.json",
        },
    })
    report = capture(
        railway_url="https://railway.example/",
        public_url="https://pages.example/",
        session=_Session([
            _Response(200, {"gmail": {"status": "no_new_content"}, "gdelt": {"status": "no_event"}, "delivery": {"status": "not_checked"}}),
            _Response(200, manifest),
            _Response(200, None, market_artifact),
            _Response(200, None, creator_artifact),
        ]),
    )
    assert report["status"] == "NEEDS_REVERIFY"
    assert report["pages"]["artifact_hash_audit"]["lineage_mismatch_count"] == 1
    assert "pages_artifact_lineage_mismatch:creator-insights.json:snapshot_id" in report["blocking_reasons"]


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
