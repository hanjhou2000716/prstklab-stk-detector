"""Standalone GitHub dispatch transport for the Railway monitor.

The monitor owns event construction, signing and persistence.  This module
owns only the bounded HTTP transport so a transient GitHub failure cannot
crash the poll loop and the transport can be verified without importing the
full Railway application.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx


async def dispatch_repository_payload(
    payload: dict[str, Any],
    *,
    token: str,
    repository: str,
    trace_id: str,
    api_version: str = "2022-11-28",
) -> None:
    """Deliver one repository-dispatch payload with bounded retry/backoff."""
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": api_version,
    }
    endpoint = f"https://api.github.com/repos/{repository}/dispatches"
    async with httpx.AsyncClient(timeout=20) as client:
        for attempt in range(3):
            try:
                response = await client.post(endpoint, headers=headers, json=payload)
            except httpx.HTTPError as exc:
                if attempt == 2:
                    logging.error("dispatch failed trace_id=%s error=%s", trace_id, type(exc).__name__)
                    raise
                await asyncio.sleep(2**attempt)
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == 2:
                    response.raise_for_status()
                retry_after = 0
                try:
                    retry_after = int(response.json().get("parameters", {}).get("retry_after", 0))
                except (TypeError, ValueError, AttributeError):
                    pass
                await asyncio.sleep(min(60, max(1, retry_after)) if retry_after else 2**attempt)
                continue
            response.raise_for_status()
            logging.info("dispatch accepted trace_id=%s status=%s", trace_id, response.status_code)
            return
