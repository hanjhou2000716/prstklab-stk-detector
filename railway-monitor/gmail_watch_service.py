"""Private Gmail ``users.watch`` creation and renewal adapter.

The transport is isolated from the authenticated Pub/Sub receiver. It
exchanges a refresh token for a short-lived access token, calls the official
Gmail API, and persists only the returned history cursor and expiration.
Tokens and response bodies never enter logs or health payloads; failures are
bounded and never stop the Railway polling loop.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import math
from typing import Any

import httpx

from email_store import EmailStore
from gmail_watch import GmailWatchConfig, renewal_due

TOKEN_URL = "https://oauth2.googleapis.com/token"
WATCH_URL = "https://gmail.googleapis.com/gmail/v1/users/me/watch"


def _http_error(response: httpx.Response) -> str:
    return f"http_{response.status_code}"


def _iso_expiration(value: Any) -> str | None:
    """Normalize Gmail's millisecond epoch expiration without guessing."""
    try:
        millis = int(str(value))
    except (TypeError, ValueError, OverflowError):
        return None
    if millis <= 0:
        return None
    return datetime.fromtimestamp(millis / 1000, tz=UTC).isoformat()


def _retry_after_seconds(cursor: dict[str, Any], config: GmailWatchConfig, now: datetime) -> int:
    """Return a bounded retry delay after a failed watch attempt."""
    error = str(cursor.get("watch_error") or "").strip()
    error_at = str(cursor.get("watch_error_at") or "").strip()
    if not error or not error_at:
        return 0
    try:
        failed_at = datetime.fromisoformat(error_at.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return 0
    remaining = failed_at + timedelta(minutes=max(1, config.retry_cooldown_minutes)) - now.astimezone(UTC)
    return max(0, math.ceil(remaining.total_seconds()))


def _failure(store: EmailStore, error: str, now: datetime) -> dict[str, Any]:
    """Persist a redacted failure while keeping the monitor non-fatal."""
    safe_error = error[:80]
    store.save_cursor(watch_error=safe_error, watch_error_at=now.astimezone(UTC).isoformat())
    return {"status": "failed", "watch_status": "failed", "attempted": True, "error": safe_error}


async def renew_watch_if_due(
    config: GmailWatchConfig,
    store: EmailStore,
    *,
    now: datetime | None = None,
    force: bool = False,
    client_factory: Callable[..., Any] = httpx.AsyncClient,
) -> dict[str, Any]:
    """Create or renew a Gmail watch when its durable lease is near expiry."""
    cursor = store.cursor()
    expiration = cursor.get("watch_expiration")
    current = (now or datetime.now(UTC)).astimezone(UTC)
    if not force and not renewal_due(str(expiration) if expiration else None, now=now):
        return {
            "status": "active",
            "watch_status": "active",
            "watch_expiration": expiration,
            "attempted": False,
            "error": None,
        }
    if not force:
        retry_after = _retry_after_seconds(cursor, config, current)
        if retry_after:
            return {
                "status": "failed",
                "watch_status": "failed",
                "attempted": False,
                "error": str(cursor.get("watch_error") or "watch_renewal_failed")[:80],
                "retry_suppressed": True,
                "retry_after_seconds": retry_after,
            }
    if config.missing:
        return {
            "status": "configuration_missing",
            "watch_status": "configuration_missing",
            "missing": list(config.missing),
            "attempted": False,
            "error": "watch_configuration_missing",
        }
    if config.oauth_missing:
        return {
            "status": "configuration_missing",
            "watch_status": "configuration_missing",
            "missing": list(config.oauth_missing),
            "attempted": False,
            "error": "oauth_configuration_missing",
        }

    try:
        async with client_factory(timeout=20, follow_redirects=True) as client:
            token_response = await client.post(
                TOKEN_URL,
                data={
                    "client_id": config.oauth_client_id,
                    "client_secret": config.oauth_client_secret,
                    "refresh_token": config.refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            if token_response.status_code >= 400:
                return _failure(store, _http_error(token_response), current)
            token_payload = token_response.json()
            access_token = token_payload.get("access_token") if isinstance(token_payload, dict) else None
            if not isinstance(access_token, str) or not access_token.strip():
                return _failure(store, "invalid_token_response", current)
            watch_response = await client.post(
                WATCH_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                json=config.watch_request(),
            )
            if watch_response.status_code >= 400:
                return _failure(store, _http_error(watch_response), current)
            watch_payload = watch_response.json()
            if not isinstance(watch_payload, dict):
                return _failure(store, "invalid_watch_response", current)
            new_expiration = _iso_expiration(watch_payload.get("expiration"))
            history_id = str(watch_payload.get("historyId") or "").strip()
            if not new_expiration or not history_id:
                return _failure(store, "invalid_watch_response", current)
            store.save_cursor(
                watch_expiration=new_expiration,
                watch_last_renewed_at=current.isoformat(),
                watch_error=None,
                watch_error_at=None,
                last_history_id=history_id,
            )
            return {
                "status": "active",
                "watch_status": "active",
                "watch_expiration": new_expiration,
                "attempted": True,
                "error": None,
            }
    except httpx.TimeoutException:
        return _failure(store, "timeout", current)
    except httpx.HTTPError as error:
        return _failure(store, type(error).__name__, current)
    except (TypeError, ValueError, KeyError):
        return _failure(store, "invalid_response", current)


__all__ = ["TOKEN_URL", "WATCH_URL", "renew_watch_if_due"]
