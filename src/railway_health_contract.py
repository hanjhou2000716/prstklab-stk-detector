"""Safe, deterministic normalization for the Railway monitor health payload."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

_TRANSIENT_ERRORS = {"http_429", "http_5xx", "timeout", "network_error"}
_CONFIG_ERRORS = {"http_401", "http_403", "configuration_missing", "missing_config"}
_STATUSES = {"healthy", "degraded", "failed", "stale", "not_checked", "configuration_missing"}


def _time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)


def _bounded_retry(value: Any) -> int | None:
    try:
        return max(0, min(3600, int(value)))
    except (TypeError, ValueError):
        return None


def normalize_railway_health(
    payload: dict[str, Any] | None,
    *,
    now: Any = None,
    heartbeat_timeout_seconds: int = 300,
) -> dict[str, Any]:
    """Normalize monitor health without copying secrets or raw exceptions.

    HTTP 403/401 is an operator configuration problem, not a restart signal.
    HTTP 429/5xx and network timeouts remain retryable and expose a bounded
    retry hint. A missing or old heartbeat is stale and fail-closed.
    """
    if not isinstance(payload, dict):
        return {
            "status": "failed", "reason": "invalid_payload", "retryable": False,
            "restart_recommended": False, "secret_values_exposed": False,
        }
    current = _time(now) or datetime.now(UTC)
    raw_components = payload.get("components")
    components: dict[str, Any] = raw_components if isinstance(raw_components, dict) else {}
    safe_components: dict[str, dict[str, Any]] = {}
    retryable = False
    configuration_missing = False
    failed = False
    for name, raw in components.items():
        if not isinstance(raw, dict):
            continue
        status = str(raw.get("status") or "not_checked").strip().lower()
        error_code = str(raw.get("error_code") or raw.get("code") or "").strip().lower()
        if error_code in _CONFIG_ERRORS:
            status = "configuration_missing"
            configuration_missing = True
        elif error_code in _TRANSIENT_ERRORS:
            status = "degraded"
            retryable = True
        elif status not in _STATUSES:
            status = "failed"
        failed = failed or status == "failed"
        retryable = retryable or status == "degraded"
        safe_components[str(name)] = {
            "status": status,
            "error_code": error_code or None,
            "last_success_at": str(raw.get("last_success_at") or "") or None,
            "last_failure_at": str(raw.get("last_failure_at") or "") or None,
            "retry_after_seconds": _bounded_retry(raw.get("retry_after_seconds")),
        }
    heartbeat = _time(
        payload.get("last_cycle_completed_at")
        or payload.get("last_heartbeat_at")
        or payload.get("last_success_at")
    )
    heartbeat_age = (current - heartbeat).total_seconds() if heartbeat else None
    stale = heartbeat is None or (
        heartbeat_age is not None and heartbeat_age > max(1, int(heartbeat_timeout_seconds))
    )
    if failed:
        status = "failed"
    elif configuration_missing and not retryable:
        status = "configuration_missing"
    elif stale:
        status = "stale"
    elif retryable:
        status = "degraded"
    else:
        status = "healthy"
    retry_after = _bounded_retry(payload.get("retry_after_seconds"))
    return {
        "status": status,
        "heartbeat_at": heartbeat.isoformat() if heartbeat else None,
        "heartbeat_age_seconds": round(heartbeat_age, 1) if heartbeat_age is not None else None,
        "components": safe_components,
        "retryable": retryable,
        "retry_after_seconds": retry_after,
        "restart_recommended": status in {"failed", "stale"} and not configuration_missing,
        "secret_values_exposed": False,
        "raw_error_included": False,
    }


__all__ = ["normalize_railway_health"]
