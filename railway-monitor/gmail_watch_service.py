"""Private Gmail ``users.watch`` creation and renewal adapter.

The transport is isolated from the authenticated Pub/Sub receiver. It
exchanges a refresh token for a short-lived access token, calls the official
Gmail API, and persists only the returned history cursor and expiration.
Tokens and response bodies never enter logs or health payloads; failures are
bounded and never stop the Railway polling loop.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
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
    if not force and not renewal_due(str(expiration) if expiration else None, now=now):
        return {
            "status": "active",
            "watch_status": "active",
            "watch_expiration": expiration,
            "attempted": False,
            "error": None,
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
                return {"status": "failed", "watch_status": "failed", "attempted": True, "error": _http_error(token_response)}
            token_payload = token_response.json()
            access_token = token_payload.get("access_token") if isinstance(token_payload, dict) else None
            if not isinstance(access_token, str) or not access_token.strip():
                return {"status": "failed", "watch_status": "failed", "attempted": True, "error": "invalid_token_response"}
            watch_response = await client.post(
                WATCH_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                json=config.watch_request(),
            )
            if watch_response.status_code >= 400:
                return {"status": "failed", "watch_status": "failed", "attempted": True, "error": _http_error(watch_response)}
            watch_payload = watch_response.json()
            if not isinstance(watch_payload, dict):
                return {"status": "failed", "watch_status": "failed", "attempted": True, "error": "invalid_watch_response"}
            new_expiration = _iso_expiration(watch_payload.get("expiration"))
            history_id = str(watch_payload.get("historyId") or "").strip()
            if not new_expiration or not history_id:
                return {"status": "failed", "watch_status": "failed", "attempted": True, "error": "invalid_watch_response"}
            store.save_cursor(watch_expiration=new_expiration, last_history_id=history_id)
            return {
                "status": "active",
                "watch_status": "active",
                "watch_expiration": new_expiration,
                "attempted": True,
                "error": None,
            }
    except httpx.TimeoutException:
        return {"status": "failed", "watch_status": "failed", "attempted": True, "error": "timeout"}
    except httpx.HTTPError as error:
        return {"status": "failed", "watch_status": "failed", "attempted": True, "error": type(error).__name__}
    except (TypeError, ValueError, KeyError):
        return {"status": "failed", "watch_status": "failed", "attempted": True, "error": "invalid_response"}


__all__ = ["TOKEN_URL", "WATCH_URL", "renew_watch_if_due"]
