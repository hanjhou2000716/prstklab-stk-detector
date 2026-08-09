"""Shared provider error classification and bounded-retry metadata.

Provider failures are expected operational states.  Normalising them in one
place keeps source-health cards actionable without leaking exception text or
making a blocked endpoint look like a successful observation.
"""

from __future__ import annotations

from typing import Any


def classify_provider_error(exc: BaseException) -> dict[str, Any]:
    """Return a stable, non-sensitive error classification for ``exc``."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status is None:
        status = getattr(exc, "status_code", None)
    try:
        status = int(status) if status is not None else None
    except (TypeError, ValueError):
        status = None

    name = type(exc).__name__.lower()
    if status == 403:
        code, retryable = "http_403", False
    elif status == 429:
        code, retryable = "http_429", True
    elif status is not None and 400 <= status < 500:
        code, retryable = "http_4xx", False
    elif status is not None and status >= 500:
        code, retryable = "http_5xx", True
    elif "timeout" in name:
        code, retryable = "timeout", True
    elif "json" in name:
        code, retryable = "invalid_json", False
    elif isinstance(exc, (ValueError, TypeError, KeyError)):
        code, retryable = "invalid_payload", False
    elif isinstance(exc, OSError) or "connection" in name or "network" in name:
        code, retryable = "network_error", True
    else:
        code, retryable = "unknown", False
    return {"code": code, "retryable": retryable, "http_status": status}


def error_token(provider: str, item: str, exc: BaseException) -> str:
    """Build a deterministic health token without including exception text."""
    return f"{provider}:{item}:{classify_provider_error(exc)['code']}"
