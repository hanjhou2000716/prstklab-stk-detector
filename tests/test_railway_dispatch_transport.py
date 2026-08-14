from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import httpx

MODULE_PATH = Path(__file__).parents[1] / "railway-monitor" / "dispatch_transport.py"
SPEC = importlib.util.spec_from_file_location("railway_dispatch_transport", MODULE_PATH)
assert SPEC and SPEC.loader
transport = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(transport)


def test_dispatch_transport_retries_rate_limit_then_succeeds(monkeypatch):
    request = httpx.Request("POST", "https://api.github.com/repos/o/r/dispatches")
    responses = [
        httpx.Response(429, json={"parameters": {"retry_after": 0}}, request=request),
        httpx.Response(204, request=request),
    ]

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, *_args, **_kwargs):
            return responses.pop(0)

    monkeypatch.setattr(transport.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    monkeypatch.setattr(transport.asyncio, "sleep", _no_sleep)
    asyncio.run(transport.dispatch_repository_payload({}, token="token", repository="o/r", trace_id="trace"))
    assert responses == []


def test_dispatch_transport_retries_http_error_then_succeeds(monkeypatch):
    request = httpx.Request("POST", "https://api.github.com/repos/o/r/dispatches")
    responses = [httpx.ConnectError("offline"), httpx.Response(204, request=request)]

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, *_args, **_kwargs):
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

    monkeypatch.setattr(transport.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    monkeypatch.setattr(transport.asyncio, "sleep", _no_sleep)
    asyncio.run(transport.dispatch_repository_payload({}, token="token", repository="o/r", trace_id="trace"))
    assert responses == []


async def _no_sleep(_seconds: float) -> None:
    return None
