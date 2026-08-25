"""Async compatibility adapter for the canonical Gmail watch manager.

``gmail_watch.py`` owns the Gmail ``users.watch`` contract, lease decisions,
bounded retry and cursor persistence. Railway's existing async application
loop imports this module for compatibility; it contains only a transport
bridge and result-shape adapter so a second watch producer cannot drift from
the Pub/Sub ingress path.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl

import httpx
from email_store import EmailStore
from gmail_watch import (
    CANONICAL_WATCH_OWNER,
    TOKEN_ENDPOINT,
    WATCH_ENDPOINT,
    GmailWatchConfig,
    GmailWatchManager,
)

# Compatibility names are retained for callers that imported the old adapter.
TOKEN_URL = TOKEN_ENDPOINT
WATCH_URL = WATCH_ENDPOINT


def _service_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Map the manager result to the historical async-service envelope."""
    status = str(result.get("status") or "failed")
    if status == "healthy":
        output: dict[str, Any] = {
            "status": "active",
            "watch_status": "active",
            "watch_expiration": result.get("watch_expiration"),
            "attempted": bool(result.get("renewed")),
            "error": None,
        }
    elif status == "configuration_missing":
        output = {
            "status": status,
            "watch_status": status,
            "attempted": False,
            "error": "watch_configuration_missing",
            "missing": list(result.get("missing") or []),
        }
    else:
        suppressed = bool(result.get("retry_suppressed"))
        output = {
            "status": "failed",
            "watch_status": "failed",
            "attempted": not suppressed,
            "error": str(result.get("error") or "watch_renewal_failed")[:80],
        }
        for key in ("retry_suppressed", "retry_after_seconds"):
            if key in result:
                output[key] = result[key]
    return output


def _run_manager(
    config: GmailWatchConfig,
    store: EmailStore,
    *,
    now: datetime | None,
    force: bool,
    client_factory: Callable[..., Any],
) -> dict[str, Any]:
    """Run the canonical sync manager in a worker thread.

    The injected async client remains usable in tests and production, while
    all lease state decisions remain in ``GmailWatchManager``. ``asyncio.run``
    is safe here because this function is called from ``asyncio.to_thread``.
    """

    def transport(url: str, body: bytes, headers: Mapping[str, str], timeout: float) -> tuple[int, bytes]:
        async def request() -> tuple[int, bytes]:
            async with client_factory(timeout=timeout, follow_redirects=True) as client:
                if url == TOKEN_ENDPOINT:
                    response = await client.post(url, data=dict(parse_qsl(body.decode("ascii"))))
                else:
                    response = await client.post(
                        url,
                        # The async adapter preserves the historical caller
                        # shape; httpx adds JSON content type automatically.
                        headers={key: value for key, value in headers.items() if key.casefold() == "authorization"},
                        json=json.loads(body.decode("utf-8")),
                    )
                payload = response.json()
                return int(response.status_code), json.dumps(payload, ensure_ascii=False).encode("utf-8")

        return asyncio.run(request())

    current = now or datetime.now(UTC)
    manager = GmailWatchManager(config, store, transport=transport, now=lambda: current)
    return manager.ensure_watch(force=force)


async def renew_watch_if_due(
    config: GmailWatchConfig,
    store: EmailStore,
    *,
    now: datetime | None = None,
    force: bool = False,
    client_factory: Callable[..., Any] = httpx.AsyncClient,
) -> dict[str, Any]:
    """Renew the canonical Gmail lease without blocking Railway's event loop."""
    result = await asyncio.to_thread(
        _run_manager,
        config,
        store,
        now=now,
        force=force,
        client_factory=client_factory,
    )
    return _service_result(result)


__all__ = [
    "CANONICAL_WATCH_OWNER",
    "TOKEN_URL",
    "WATCH_URL",
    "renew_watch_if_due",
]
