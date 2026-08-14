from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1] / "railway-monitor"
SPEC = importlib.util.spec_from_file_location("railway_health_dispatch_test", ROOT / "health_dispatch.py")
assert SPEC and SPEC.loader
health_dispatch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(health_dispatch)


class _Response:
    status_code = 204
    headers: dict[str, str] = {}

    def raise_for_status(self) -> None:
        return None


class _Client:
    def __init__(self, **_: object) -> None:
        self.calls = 0

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def post(self, *_: object, **__: object) -> _Response:
        self.calls += 1
        return _Response()


def test_missing_configuration_is_non_fatal_and_updates_state():
    updates: list[tuple[object, dict[str, object]]] = []

    def update(component: object, **values: object) -> None:
        updates.append((component, values))

    state = asyncio.run(
        health_dispatch.dispatch_monitor_health(
            token="",
            repository="owner/repo",
            gdelt={"status": "failed"},
            backoff_until=0,
            backoff_status="not_checked",
            backoff_error=None,
            backoff_next_at=None,
            update_health=update,
            github_api_version="2022-11-28",
        )
    )
    assert state["status"] == "configuration_missing"
    assert updates[-1][1]["health_dispatch_status"] == "configuration_missing"


def test_success_clears_backoff_and_sends_bounded_payload():
    updates: list[tuple[object, dict[str, object]]] = []
    posted: list[dict[str, object]] = []

    class Client(_Client):
        async def post(self, _url: object, **kwargs: object) -> _Response:
            posted.append(kwargs["json"])  # type: ignore[arg-type]
            return _Response()

    def update(component: object, **values: object) -> None:
        updates.append((component, values))

    state = asyncio.run(
        health_dispatch.dispatch_monitor_health(
            token="token",
            repository="owner/repo",
            gdelt={
                "status": "fallback_active",
                "pending_count": 2,
                "pending_reasons": {"needs_official": 2},
                "error": "HTTP_429",
                "article_body": "must not be sent",
            },
            backoff_until=0,
            backoff_status="degraded",
            backoff_error="HTTP_429",
            backoff_next_at="later",
            update_health=update,
            github_api_version="2022-11-28",
            client_factory=Client,
        )
    )
    assert state == {"until": 0.0, "status": "not_checked", "error": None, "next_at": None}
    assert posted[0]["event_type"] == "monitor-health"
    assert "article_body" not in posted[0]["client_payload"]
    assert updates[-1][1]["health_dispatch_status"] == "healthy"
