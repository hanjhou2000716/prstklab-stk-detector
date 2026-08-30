"""Fetch Railway's authenticated, public-safe email observation export."""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from src.creator_provider_registry import creator_ids
from src.external_observation_input import SAFE_FIELDS
from src.railway_secret import delivery_shared_secret

_ALLOWED_SOURCES = {"financialjuice", *creator_ids()}
_BLOCKED_FIELDS = {
    "body", "raw_body", "attachments", "data", "local_path", "private_url",
    "gmail_message_id", "gmail_thread_id", "gmail_history_id", "message_id",
    "thread_id", "sender", "recipient", "email_address",
}


def observation_export_url(configured_url: str | None = None) -> str:
    """Return the configured sanitized export endpoint.

    ``PUBLIC_OBSERVATIONS_URL`` is the zero-cost Worker replacement for the
    legacy Railway endpoint. A bare base URL remains supported for migration.
    """
    raw = str(configured_url or os.getenv("PUBLIC_OBSERVATIONS_URL") or os.getenv("RAILWAY_OBSERVATIONS_URL") or os.getenv("RAILWAY_STATUS_URL") or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    path = parsed.path.rstrip("/")
    if not path or path in {"/health", "/api/health"}:
        path = "/external-observations"
    query = parsed.query or "limit=100"
    if "limit=" not in query:
        query = f"{query}&limit=100" if query else "limit=100"
    return urlunparse((parsed.scheme, parsed.netloc, path, "", query, ""))


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
    max_attempts: int = 2,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return sanitized observations and an explicit source-health result.

    Missing configuration is a no-op, not a failure: the local reviewed input
    remains usable.  Network, authentication and schema failures are surfaced
    as a degraded source so the release can fail closed without inventing
    events.
    """
    endpoint = observation_export_url(url)
    # The scheduled collection step receives this narrowly scoped secret only
    # when the canonical Worker export is enabled.  Keep it separate from the
    # legacy Railway helper so Telegram tokens never enter the job.
    token = str(secret or os.getenv("PUBLIC_OBSERVATIONS_SHARED_SECRET") or delivery_shared_secret()).strip()
    if not endpoint or not token:
        return [], {"status": "configuration_missing", "reason": "railway_observation_export_not_configured", "rejected_count": 0}
    attempts_limit = max(1, min(2, int(max_attempts)))
    retry_count = 0
    response: Any = None
    payload: Any = None
    last_reason = "request_or_json_error"
    for attempt in range(attempts_limit):
        try:
            response = httpx.get(
                endpoint,
                headers={"X-PRSTK-Signature": _signature(endpoint, token), "Accept": "application/json"},
                timeout=max(1.0, min(30.0, float(timeout))),
            )
            status_code = int(response.status_code)
            if status_code != 200:
                last_reason = f"http_{status_code}"
                retryable = status_code == 429 or status_code >= 500
                if not retryable or attempt + 1 >= attempts_limit:
                    return [], {
                        "status": "failed",
                        "reason": last_reason,
                        "retryable": retryable,
                        "attempts": attempt + 1,
                        "retry_count": retry_count,
                        "rejected_count": 0,
                    }
                retry_count += 1
                _sleep_before_retry(response, attempt)
                continue
            payload = response.json()
            break
        except (httpx.HTTPError, ValueError, TypeError):
            if attempt + 1 >= attempts_limit:
                return [], {
                    "status": "failed",
                    "reason": last_reason,
                    "retryable": True,
                    "attempts": attempt + 1,
                    "retry_count": retry_count,
                    "rejected_count": 0,
                }
            retry_count += 1
            _sleep_before_retry(response, attempt)
    if payload is None:
        return [], {"status": "failed", "reason": last_reason, "retryable": True, "attempts": attempts_limit, "retry_count": retry_count, "rejected_count": 0}
    rows = payload.get("observations") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return [], {"status": "failed", "reason": "invalid_observation_shape", "rejected_count": 0}
    safe: list[dict[str, Any]] = []
    rejected = 0
    for row in rows:
        if not isinstance(row, dict) or row.get("public_safe") is not True:
            rejected += 1
            continue
        if not str(row.get("observation_id") or "").strip():
            rejected += 1
            continue
        source = str(row.get("source") or row.get("content_origin") or "").strip().casefold()
        if source not in _ALLOWED_SOURCES:
            rejected += 1
            continue
        if any(row.get(key) not in (None, "", [], {}) for key in _BLOCKED_FIELDS):
            rejected += 1
            continue
        normalized = {key: row[key] for key in SAFE_FIELDS if key in row}
        normalized["source"] = source
        normalized["content_origin"] = source
        safe.append(normalized)
    status_value = payload.get("status") or ("ready" if safe else "no_event")
    status = str(status_value)
    return safe, {"status": status, "count": len(safe), "rejected_count": rejected, "attempts": retry_count + 1, "retry_count": retry_count}


def _sleep_before_retry(response: Any, attempt: int) -> None:
    """Apply a short, bounded delay without retrying auth/configuration errors."""
    headers = getattr(response, "headers", {}) or {}
    raw_retry_after = headers.get("Retry-After") if hasattr(headers, "get") else None
    try:
        delay = float(raw_retry_after) if raw_retry_after is not None else 0.5 * (2**attempt)
    except (TypeError, ValueError):
        delay = 0.5 * (2**attempt)
    time.sleep(max(0.0, min(5.0, delay)))


__all__ = ["load_railway_observations", "observation_export_url"]
