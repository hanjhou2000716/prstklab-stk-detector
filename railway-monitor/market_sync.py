"""Read-only market-snapshot retrieval used as event-confirmation evidence."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx


def snapshot_url(environ: dict[str, str] | None = None) -> str:
    values = environ if environ is not None else {}
    base = values.get("MARKET_SNAPSHOT_URL", "").strip()
    if base:
        return base
    dashboard = values.get("DASHBOARD_URL", "").strip().rstrip("/")
    return f"{dashboard}/data/market.json" if dashboard else ""


async def fetch_market_sync_snapshot(
    *,
    environ: dict[str, str] | None = None,
    client_factory: Callable[..., Any] = httpx.AsyncClient,
) -> dict[str, Any]:
    """Fetch a public snapshot; failures are an explicit no-confirmation result."""
    url = snapshot_url(environ)
    if not url:
        return {}
    try:
        async with client_factory(timeout=15, follow_redirects=True) as client:
            response = await client.get(url)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}
    except (httpx.HTTPError, ValueError, TypeError) as error:
        import logging

        logging.warning("market sync snapshot unavailable error=%s", type(error).__name__)
        return {}
