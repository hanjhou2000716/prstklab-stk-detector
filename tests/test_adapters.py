from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.adapters import AdapterError, build_default_adapters
from src.adapters.base import AdapterObservation


@dataclass
class FakeResponse:
    payload: object
    status_code: int = 200
    text: str = "raw"

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def test_registry_contains_all_phase_one_sources():
    adapters = build_default_adapters(transport=lambda *args, **kwargs: FakeResponse({"ok": True}))
    assert set(adapters) == {"twse", "taifex", "tpex", "yahoo", "sec", "fred", "eia", "binance", "gdelt"}
    assert adapters["twse"].source_tier == "official"
    assert adapters["gdelt"].source_tier == "discovery"


def test_successful_fetch_preserves_hash_and_provenance():
    adapters = build_default_adapters(
        transport=lambda *args, **kwargs: FakeResponse({"value": 42}),
    )
    observation = adapters["twse"].fetch()
    assert isinstance(observation, AdapterObservation)
    assert observation.payload_hash and len(observation.payload_hash) == 64
    assert adapters["twse"].normalize(observation) == {"value": 42}
    provenance = adapters["twse"].provenance(observation)
    assert provenance["provider"] == "twse"
    assert provenance["source_tier"] == "official"
    assert provenance["fetched_at"]
    assert provenance["payload_hash"] == observation.payload_hash


def test_failed_fetch_is_explicit_and_does_not_fabricate_success():
    def fail(*args, **kwargs):
        raise TimeoutError("network")

    adapter = build_default_adapters(transport=fail)["yahoo"]
    with pytest.raises(AdapterError) as exc_info:
        adapter.fetch()
    assert exc_info.value.code == "transport_error"
    health = adapter.health().as_dict()
    assert health["status"] == "failed"
    assert health["last_success_at"] is None
    assert health["consecutive_failures"] == 1
    assert "network" not in health["message"]


def test_http_status_and_retry_taxonomy_are_retained():
    adapter = build_default_adapters(
        transport=lambda *args, **kwargs: FakeResponse({}, status_code=429),
    )["gdelt"]
    with pytest.raises(AdapterError) as exc_info:
        adapter.fetch()
    assert exc_info.value.code == "http_error"
    assert exc_info.value.transient is True
    assert adapter.health().error_code == "http_error"


def test_credential_required_sources_fail_closed_without_exposing_secret(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    adapter = build_default_adapters(transport=lambda *args, **kwargs: FakeResponse({}))["fred"]
    with pytest.raises(AdapterError) as exc_info:
        adapter.fetch()
    assert exc_info.value.code == "missing_credential"
    assert "FRED_API_KEY" in str(exc_info.value)
    assert "SECRET" not in str(exc_info.value).upper()
    assert adapter.health().status == "failed"


def test_health_snapshot_is_sorted_and_explicit():
    adapters = build_default_adapters(transport=lambda *args, **kwargs: FakeResponse({}))
    snapshot = __import__("src.adapters.registry", fromlist=["adapter_health_snapshot"]).adapter_health_snapshot(adapters)
    assert [item["provider"] for item in snapshot] == sorted(adapters)
    assert all(item["status"] == "unknown" for item in snapshot)