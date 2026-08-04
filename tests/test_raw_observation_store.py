from __future__ import annotations

import json

from src.raw_observation_store import RawObservationStore, observation_metadata


def test_raw_store_is_idempotent_and_content_addressed(tmp_path) -> None:
    store = RawObservationStore(tmp_path / "raw")
    kwargs = {
        "provider": "twse",
        "endpoint": "https://example.test/twse",
        "fetched_at": "2026-08-05T09:00:00+08:00",
        "request_id": "request-1",
        "payload": {"b": 2, "a": 1},
        "http_status": 200,
        "parser_version": "1",
        "parsing_status": "parsed",
    }

    first = store.record(**kwargs)
    second = store.record(**{**kwargs, "payload": {"a": 1, "b": 2}})

    assert first == second
    assert store.count() == 1
    raw_path = tmp_path / "raw" / first.raw_payload_location
    assert json.loads(raw_path.read_text(encoding="utf-8")) == {"a": 1, "b": 2}


def test_raw_store_keeps_distinct_payloads_and_safe_metadata(tmp_path) -> None:
    store = RawObservationStore(tmp_path / "raw")
    common = {
        "provider": "gdelt",
        "endpoint": "https://example.test/gdelt",
        "fetched_at": "2026-08-05T09:00:00+08:00",
        "http_status": 200,
        "parser_version": "2",
        "parsing_status": "parsed",
    }
    first = store.record(**common, request_id="one", payload={"items": [1]})
    second = store.record(**common, request_id="two", payload={"items": [2]})

    assert first.observation_id != second.observation_id
    assert store.count(provider="gdelt") == 2
    rows = store.list_recent(provider="gdelt")
    metadata = observation_metadata(rows)
    assert {item["request_id"] for item in metadata} == {"one", "two"}
    assert all("payload_hash" in item for item in metadata)
