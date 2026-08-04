from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.adapters.base import AdapterObservation, payload_hash
from src.observation_store import RawObservationStore


def observation(payload: object, *, provider: str = "twse") -> AdapterObservation:
    return AdapterObservation(
        provider=provider,
        endpoint="https://example.test/feed",
        source_tier="official",
        fetched_at=datetime(2026, 8, 4, 1, 0, tzinfo=UTC),
        payload=payload,
        source_url="https://example.test/feed",
        request_id="trace-1",
        http_status=200,
        payload_hash=payload_hash(payload),
    )


def test_append_is_idempotent_and_preserves_raw_payload(tmp_path: Path):
    store = RawObservationStore(tmp_path / "raw")
    item = observation({"price": 123})
    first = store.append(item, parser_version="twse-v1")
    second = store.append(item, parser_version="twse-v1")
    assert first.observation_id == second.observation_id
    assert store.count() == 1
    assert store.read_payload(first) == {"price": 123}
    assert Path(first.raw_payload_location).is_file()


def test_different_payloads_are_separate_and_queryable(tmp_path: Path):
    store = RawObservationStore(tmp_path / "raw")
    store.append(observation({"n": 1}), parser_version="v1")
    store.append(observation({"n": 2}), parser_version="v1")
    assert store.count(provider="twse") == 2
    assert len(store.list(provider="twse")) == 2


def test_hash_mismatch_fails_closed(tmp_path: Path):
    store = RawObservationStore(tmp_path / "raw")
    item = observation({"price": 1})
    bad = AdapterObservation(**{**item.__dict__, "payload_hash": "0" * 64})
    with pytest.raises(ValueError, match="payload hash"):
        store.append(bad, parser_version="v1")


def test_raw_path_is_provider_and_date_partitioned(tmp_path: Path):
    store = RawObservationStore(tmp_path / "raw")
    record = store.append(observation({"ok": True}, provider="TPEx"), parser_version="tpex-v2")
    path = Path(record.raw_payload_location)
    assert path.parent.name == "2026-08-04"
    assert path.parent.parent.name == "tpex"
    assert record.parse_status == "ok"
    assert record.source_tier == "official"