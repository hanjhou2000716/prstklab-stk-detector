"""Bounded, non-fatal health callback delivery for the Railway monitor."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

UpdateHealth = Callable[..., None]


async def dispatch_monitor_health(
    *,
    token: str,
    repository: str,
    gdelt: dict[str, Any],
    backoff_until: float,
    backoff_status: str,
    backoff_error: str | None,
    backoff_next_at: str | None,
    update_health: UpdateHealth,
    github_api_version: str,
    client_factory: Callable[..., Any] = httpx.AsyncClient,
) -> dict[str, Any]:
    """Publish bounded diagnostics without ever crashing the source monitor."""
    state = {
        "until": backoff_until,
        "status": backoff_status,
        "error": backoff_error,
        "next_at": backoff_next_at,
    }
    if not token or not repository:
        update_health(
            "gdelt",
            health_dispatch_status="configuration_missing",
            health_dispatch_error="missing_github_dispatch_configuration",
            health_dispatch_next_retry_at=None,
        )
        logging.warning("monitor health dispatch skipped: GitHub credentials are not configured")
        state.update(status="configuration_missing", error="missing_github_dispatch_configuration", next_at=None)
        return state
    if time.monotonic() < backoff_until:
        update_health(
            "gdelt",
            health_dispatch_status=backoff_status,
            health_dispatch_error=backoff_error,
            health_dispatch_next_retry_at=backoff_next_at,
        )
        logging.info("monitor health dispatch backoff active status=%s", backoff_status)
        return state
    payload = {
        "event_type": "monitor-health",
        "client_payload": {
            "component": "gdelt",
            "status": str(gdelt.get("status") or "unknown"),
            "checked_at": gdelt.get("last_success_at") or gdelt.get("last_failure_at"),
            "pending_count": int(gdelt.get("pending_count") or 0),
            "pending_reasons": {
                str(key): int(value or 0)
                for key, value in (gdelt.get("pending_reasons") or {}).items()
            },
            "market_sync_status": str(gdelt.get("market_sync_status") or "not_confirmed"),
            "error": str(gdelt.get("error") or "") or None,
        },
    }
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": github_api_version,
    }
    endpoint = f"https://api.github.com/repos/{repository}/dispatches"
    async with client_factory(timeout=20) as client:
        for attempt in range(3):
            try:
                response = await client.post(endpoint, headers=headers, json=payload)
            except httpx.HTTPError as exc:
                if attempt == 2:
                    state.update(
                        until=time.monotonic() + 60,
                        status="degraded",
                        error=type(exc).__name__,
                        next_at=(datetime.now(UTC) + timedelta(seconds=60)).isoformat(),
                    )
                    update_health("gdelt", health_dispatch_status="degraded", health_dispatch_error=type(exc).__name__, health_dispatch_next_retry_at=state["next_at"])
                    logging.warning("monitor health dispatch unavailable error=%s", type(exc).__name__)
                    return state
                await asyncio.sleep(2**attempt)
                continue
            if response.status_code in {401, 403}:
                state.update(
                    until=time.monotonic() + 900,
                    status="configuration_missing" if response.status_code == 401 else "permission_denied",
                    error=f"HTTP_{response.status_code}",
                    next_at=(datetime.now(UTC) + timedelta(seconds=900)).isoformat(),
                )
                update_health("gdelt", health_dispatch_status=state["status"], health_dispatch_error=state["error"], health_dispatch_next_retry_at=state["next_at"])
                logging.warning("monitor health dispatch rejected status=%s; local health retained", response.status_code)
                return state
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == 2:
                    state.update(
                        until=time.monotonic() + 300,
                        status="degraded",
                        error=f"HTTP_{response.status_code}",
                        next_at=(datetime.now(UTC) + timedelta(seconds=300)).isoformat(),
                    )
                    update_health("gdelt", health_dispatch_status="degraded", health_dispatch_error=state["error"], health_dispatch_next_retry_at=state["next_at"])
                    logging.warning("monitor health dispatch rate-limited/unavailable status=%s", response.status_code)
                    return state
                try:
                    retry_after = int(response.headers.get("Retry-After", "0"))
                except (TypeError, ValueError):
                    retry_after = 0
                await asyncio.sleep(min(60, max(1, retry_after)) if retry_after else 2**attempt)
                continue
            response.raise_for_status()
            state.update(until=0.0, status="not_checked", error=None, next_at=None)
            update_health("gdelt", health_dispatch_status="healthy", health_dispatch_error=None, health_dispatch_next_retry_at=None)
            logging.info("monitor health dispatch accepted status=%s", response.status_code)
            return state
    return state
