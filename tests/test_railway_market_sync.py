from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

MODULE = Path(__file__).parents[1] / "railway-monitor" / "market_sync.py"
SPEC = importlib.util.spec_from_file_location("railway_market_sync_test", MODULE)
assert SPEC and SPEC.loader
market_sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(market_sync)


def test_snapshot_url_prefers_explicit_url_and_uses_dashboard_fallback():
    assert market_sync.snapshot_url({"MARKET_SNAPSHOT_URL": "https://x.test/m.json"}) == "https://x.test/m.json"
    assert market_sync.snapshot_url({"DASHBOARD_URL": "https://x.test/app/"}) == "https://x.test/app/data/market.json"
    assert market_sync.snapshot_url({}) == ""


class Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {"indices": []}


class Client:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, url):
        self.url = url
        return Response()


def test_fetch_returns_public_dict_without_live_network():
    result = asyncio.run(
        market_sync.fetch_market_sync_snapshot(
            environ={"MARKET_SNAPSHOT_URL": "https://x.test/market.json"},
            client_factory=Client,
        )
    )
    assert result == {"indices": []}


def test_fetch_fails_closed_when_url_is_missing():
    assert asyncio.run(market_sync.fetch_market_sync_snapshot(environ={})) == {}


def test_observation_distinguishes_configuration_from_no_event():
    observation = asyncio.run(market_sync.fetch_market_sync_observation(environ={}))
    assert observation.status == "configuration_missing"
    assert observation.snapshot == {}
    assert observation.health()["error"] == "market_snapshot_url_missing"


def test_observation_marks_valid_empty_snapshot_as_available():
    observation = asyncio.run(
        market_sync.fetch_market_sync_observation(
            environ={"MARKET_SNAPSHOT_URL": "https://x.test/market.json"},
            client_factory=Client,
        )
    )
    assert observation.status == "available"
    assert observation.error is None
    assert observation.health()["record_count"] == 0


class InvalidResponse(Response):
    def json(self):
        return ["not", "an", "object"]


class InvalidClient(Client):
    async def get(self, url):
        self.url = url
        return InvalidResponse()


def test_observation_marks_non_object_payload_as_invalid():
    observation = asyncio.run(
        market_sync.fetch_market_sync_observation(
            environ={"MARKET_SNAPSHOT_URL": "https://x.test/market.json"},
            client_factory=InvalidClient,
        )
    )
    assert observation.status == "invalid_payload"
    assert observation.error == "payload_not_object"
