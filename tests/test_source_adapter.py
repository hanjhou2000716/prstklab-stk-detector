from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pytest

from src.raw_observation_store import RawObservationStore
from src.source_adapter import AdapterConfig, AdapterError, JsonSourceAdapter


@dataclass
class FakeResponse:
    status_code: int
    body: dict

    @property
    def content(self) -> bytes:
        return b"{}"

    def json(self) -> dict:
        return self.body


def test_adapter_returns_provenance_and_normalizes_payload() -> None:
    calls: list[dict] = []

    def transport(url: str, **kwargs):
        calls.append({"url": url, **kwargs})
        return FakeResponse(200, {"value": "42"})

    adapter = JsonSourceAdapter(
        AdapterConfig(provider="demo", endpoint="https://example.test/data", parser_version="7"),
        parser=lambda payload: {"value": int(payload["value"])},
        transport=transport,
    )
    observation = adapter.fetch(params={"date": "2026-08-05"})

    assert observation.payload == {"value": 42}
    assert observation.http_status == 200
    assert observation.stale_used is False
    assert adapter.provenance(observation)["parser_version"] == "7"
    assert calls[0]["timeout"] == 10.0
    assert calls[0]["headers"]["User-Agent"].startswith("PRStK")
    assert adapter.health()["status"] == "healthy"


def test_adapter_provenance_exposes_conservative_quality_contract() -> None:
    adapter = JsonSourceAdapter(
        AdapterConfig(provider="demo", endpoint="https://example.test/data"),
        transport=lambda url, **kwargs: FakeResponse(200, {"ok": True}),
    )
    observation = adapter.fetch()
    now = datetime.fromisoformat(observation.fetched_at)
    quality = observation.quality(now=now)
    provenance = observation.provenance()

    assert quality["data_quality_score"] == 85.0
    assert quality["alert_eligible"] is False
    assert "crosscheck_missing" in quality["reasons"]
    assert provenance["data_quality_score"] == 85.0
    assert provenance["quality_freshness"] == "fresh"


def test_stale_adapter_fallback_is_never_reported_as_live() -> None:
    responses = [FakeResponse(200, {"value": 1}), FakeResponse(503, {})]

    def transport(url: str, **kwargs):
        return responses.pop(0)

    adapter = JsonSourceAdapter(
        AdapterConfig(provider="cache", endpoint="https://example.test", max_retries=0, max_stale_seconds=60),
        transport=transport,
    )
    adapter.fetch()
    observation = adapter.fetch(allow_stale=True)
    quality = observation.quality()

    assert quality["freshness"] == "stale"
    assert quality["data_quality_score"] == 0.0
    assert quality["alert_eligible"] is False
    assert quality["display_eligible"] is False
    assert "stale_used" in quality["reasons"]


def test_adapter_retries_transient_http_then_succeeds() -> None:
    attempts = 0

    def transport(url: str, **kwargs):
        nonlocal attempts
        attempts += 1
        return FakeResponse(503, {}) if attempts == 1 else FakeResponse(200, {"ok": True})

    adapter = JsonSourceAdapter(
        AdapterConfig(provider="retry", endpoint="https://example.test", max_retries=1),
        transport=transport,
    )
    observation = adapter.fetch()

    assert attempts == 2
    assert observation.payload == {"ok": True}
    assert adapter.health()["consecutive_failures"] == 0


def test_adapter_fails_closed_without_stale_opt_in() -> None:
    def transport(url: str, **kwargs):
        return FakeResponse(200, {"value": 1})

    adapter = JsonSourceAdapter(
        AdapterConfig(provider="cache", endpoint="https://example.test", max_retries=0),
        transport=transport,
    )
    adapter.fetch()
    adapter.transport = lambda url, **kwargs: FakeResponse(500, {})

    with pytest.raises(AdapterError) as error:
        adapter.fetch()
    assert error.value.code == "http_error"
    assert adapter.health()["status"] == "failed"


def test_adapter_can_explicitly_label_stale_cache() -> None:
    responses = [FakeResponse(200, {"value": 1}), FakeResponse(503, {})]

    def transport(url: str, **kwargs):
        return responses.pop(0)

    adapter = JsonSourceAdapter(
        AdapterConfig(provider="cache", endpoint="https://example.test", max_retries=0, max_stale_seconds=60),
        transport=transport,
    )
    adapter.fetch()
    observation = adapter.fetch(allow_stale=True)

    assert observation.payload == {"value": 1}
    assert observation.stale_used is True
    assert observation.freshness == "stale"
    assert adapter.health()["status"] == "stale"


def test_adapter_persists_raw_payload_before_normalization(tmp_path) -> None:
    store = RawObservationStore(tmp_path / "raw")
    adapter = JsonSourceAdapter(
        AdapterConfig(provider="twse", endpoint="https://example.test/twse"),
        parser=lambda payload: payload["data"],
        transport=lambda url, **kwargs: FakeResponse(200, {"data": [1, 2]}),
        raw_store=store,
    )

    observation = adapter.fetch()

    assert observation.payload == [1, 2]
    assert observation.observation_id
    assert store.count(provider="twse") == 1
    assert adapter.provenance(observation)["raw_payload_location"]
