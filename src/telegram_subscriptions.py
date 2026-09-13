"""Private Telegram subscription storage.

The subscription table is the production source of truth after the one-time
legacy migration.  This module deliberately returns only validated chat IDs to
senders; usernames and database responses never enter public artifacts.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable
from typing import Any

import requests

SUBSCRIPTION_TABLE = "telegram_subscriptions"
_CHAT_ID = re.compile(r"^-?\d+$")


class TelegramSubscriptionError(RuntimeError):
    """A safe, stable error class for recipient lookup or migration."""


def _credentials(url: str | None = None, key: str | None = None) -> tuple[str, str]:
    base = str(url or os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
    token = str(key or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not base or not token:
        raise TelegramSubscriptionError("telegram_subscription_store_not_configured")
    if not base.startswith("https://"):
        raise TelegramSubscriptionError("telegram_subscription_store_requires_https")
    return base, token


def _headers(key: str) -> dict[str, str]:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _validated_ids(payload: Any) -> tuple[str, ...]:
    if not isinstance(payload, list):
        raise TelegramSubscriptionError("telegram_subscription_invalid_response")
    result: list[str] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        chat_id = str(row.get("chat_id") or "").strip()
        if not _CHAT_ID.fullmatch(chat_id):
            raise TelegramSubscriptionError("telegram_subscription_invalid_chat_id")
        if chat_id not in result:
            result.append(chat_id)
    return tuple(result)


def fetch_active_chat_ids(
    url: str | None = None,
    key: str | None = None,
    *,
    timeout: float = 15.0,
    request_get: Callable[..., Any] = requests.get,
) -> tuple[str, ...]:
    """Read active private subscribers without exposing the table contents."""
    base, token = _credentials(url, key)
    response = request_get(
        f"{base}/rest/v1/{SUBSCRIPTION_TABLE}",
        params={
            "status": "eq.active",
            "chat_type": "eq.private",
            "select": "chat_id",
            "order": "created_at.asc,chat_id.asc",
            "limit": "100",
        },
        headers=_headers(token),
        timeout=max(1.0, min(30.0, float(timeout))),
    )
    if not getattr(response, "ok", False):
        raise TelegramSubscriptionError(
            f"telegram_subscription_http_{int(getattr(response, 'status_code', 0) or 0)}"
        )
    try:
        payload = response.json()
    except (TypeError, ValueError, requests.exceptions.JSONDecodeError) as exc:
        raise TelegramSubscriptionError("telegram_subscription_invalid_response") from exc
    return _validated_ids(payload)


def migrate_legacy_chat_ids(
    chat_ids: Iterable[str],
    *,
    editor_chat_id: str = "8869592162",
    url: str | None = None,
    key: str | None = None,
    timeout: float = 15.0,
    request_post: Callable[..., Any] = requests.post,
) -> int:
    """Insert legacy recipients once, without reactivating existing rows.

    ``ignore-duplicates`` is intentional: a user who already used ``/stop``
    must not be re-enabled by a later migration or a stale secret.
    """
    base, token = _credentials(url, key)
    normalized = list(dict.fromkeys(
        value for value in (str(item).strip() for item in [*chat_ids, editor_chat_id])
        if _CHAT_ID.fullmatch(value)
    ))
    if not normalized:
        return 0
    response = request_post(
        f"{base}/rest/v1/{SUBSCRIPTION_TABLE}?on_conflict=chat_id",
        json=[
            {
                "chat_id": chat_id,
                "chat_type": "private",
                "status": "active",
                "is_editor": chat_id == editor_chat_id,
                "source": "legacy_migration",
            }
            for chat_id in normalized
        ],
        headers={**_headers(token), "Prefer": "resolution=ignore-duplicates,return=representation"},
        timeout=max(1.0, min(30.0, float(timeout))),
    )
    if not getattr(response, "ok", False):
        raise TelegramSubscriptionError(
            f"telegram_subscription_http_{int(getattr(response, 'status_code', 0) or 0)}"
        )
    try:
        payload = response.json()
    except (TypeError, ValueError, requests.exceptions.JSONDecodeError) as exc:
        raise TelegramSubscriptionError("telegram_subscription_invalid_response") from exc
    return len(_validated_ids(payload)) if isinstance(payload, list) else 0


__all__ = [
    "TelegramSubscriptionError",
    "fetch_active_chat_ids",
    "migrate_legacy_chat_ids",
]
