"""Fetch Railway's authenticated, public-safe email observation export."""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx


def observation_export_url(configured_url: str | None = None) -> str:
    """Return a stable ``/external-observations`` endpoint for a Railway URL."""
    raw = str(configured_url or os.getenv("RAILWAY_OBSERVATIONS_URL") or os.getenv("RAILWAY_STATUS_URL") or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return urlunparse((parsed.scheme, parsed.netloc, "/external-observations", "", "limit=100", ""))


def _signature(url: str, secret: str) -> str:
    parsed = urlparse(url)
    target = parsed.path or "/"
    if parsed.query:
        # Keep the exact query order used in the request; the Railway handler
        # signs the path and query verbatim.
        target += "?" + parsed.query
    return "sha256=" + hmac.new(secret.encode("utf-8"), f"GET\n{target}".encode(), hashlib.sha256).hexdigest()


def load_railway_observations(
    *,
    url: str | None = None,
    secret: str | None = None,
    timeout: float = 8.0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return sanitized observations and an explicit source-health result.

    Missing configuration is a no-op, not a failure: the local reviewed input
    remains usable.  Network, authentication and schema failures are surfaced
    as a degraded source so the release can fail closed without inventing
    events.
    """
    endpoint = observation_export_url(url)
    token = str(secret or os.getenv("RAILWAY_STATUS_SHARED_SECRET") or "").strip()
    if not endpoint or not token:
        return [], {"status": "configuration_missing", "reason": "railway_observation_export_not_configured"}
    try:
        response = httpx.get(
            endpoint,
            headers={"X-PRSTK-Signature": _signature(endpoint, token), "Accept": "application/json"},
            timeout=max(1.0, min(30.0, float(timeout))),
        )
        if response.status_code != 200:
            return [], {"status": "failed", "reason": f"http_{response.status_code}"}
        payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError):
        return [], {"status": "failed", "reason": "request_or_json_error"}
    rows = payload.get("observations") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return [], {"status": "failed", "reason": "invalid_observation_shape"}
    safe: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("public_safe") is not True:
            continue
        if not str(row.get("observation_id") or "").strip():
            continue
        if any(row.get(key) not in (None, "", [], {}) for key in ("body", "raw_body", "attachments", "gmail_message_id", "sender")):
            continue
        safe.append(dict(row))
    status_value = payload.get("status") or ("ready" if safe else "no_event")
    status = str(status_value)
    return safe, {"status": status, "count": len(safe)}


__all__ = ["load_railway_observations", "observation_export_url"]
