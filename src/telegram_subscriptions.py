"""Private Telegram subscription storage.

The subscription table is the production source of truth after the one-time
legacy migration.  This module deliberately returns only validated chat IDs to
senders; usernames and database responses never enter public artifacts.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import requests

SUBSCRIPTION_TABLE = "telegram_subscriptions"
_CHAT_ID = re.compile(r"^-?\d+$")


class TelegramSubscriptionError(RuntimeError):
    """A safe, stable error class for recipient lookup or migration."""


@dataclass(frozen=True)
class SubscriptionStorePreflight:
    """The safe result of checking the subscription schema before writes."""

    status: str
    reason: str | None = None


@dataclass(frozen=True)
class TelegramMigrationResult:
    """Machine-readable, privacy-safe outcome for the one-time migration."""

    migration_status: str
    prerequisite_status: str
    migrated_count: int
    reason: str | None = None


_REQUIRED_COLUMNS = "chat_id,chat_type,status,is_editor,source"


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


def _response_error(response: Any, *, schema_check: bool = False) -> TelegramSubscriptionError:
    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code in {401, 403}:
        return TelegramSubscriptionError(f"telegram_subscription_http_{status_code}")
    if schema_check and status_code == 400:
        return TelegramSubscriptionError("telegram_subscription_schema_incompatible")
    return TelegramSubscriptionError(f"telegram_subscription_http_{status_code}")


def check_subscription_store(
    url: str | None = None,
    key: str | None = None,
    *,
    timeout: float = 15.0,
    request_get: Callable[..., Any] = requests.get,
    request_post: Callable[..., Any] = requests.post,
) -> SubscriptionStorePreflight:
    """Check the migration prerequisites without inserting a subscriber.

    The GET verifies the table and required columns.  The empty upsert validates
    that ``chat_id`` remains a usable conflict target without sending rows or
    changing subscription state.  A missing table is an expected deployment
    ordering problem and is returned as a safe, non-failing prerequisite block;
    authentication and schema errors remain hard failures.
    """
    base, token = _credentials(url, key)
    request_timeout = max(1.0, min(30.0, float(timeout)))
    response = request_get(
        f"{base}/rest/v1/{SUBSCRIPTION_TABLE}",
        params={"select": _REQUIRED_COLUMNS, "limit": "0"},
        headers=_headers(token),
        timeout=request_timeout,
    )
    if not getattr(response, "ok", False):
        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code == 404:
            return SubscriptionStorePreflight("blocked_prerequisite", "telegram_subscription_table_missing")
        raise _response_error(response, schema_check=True)
    try:
        payload = response.json()
    except (TypeError, ValueError, requests.exceptions.JSONDecodeError) as exc:
        raise TelegramSubscriptionError("telegram_subscription_invalid_response") from exc
    if not isinstance(payload, list):
        raise TelegramSubscriptionError("telegram_subscription_invalid_response")

    constraint_response = request_post(
        f"{base}/rest/v1/{SUBSCRIPTION_TABLE}?on_conflict=chat_id",
        json=[],
        headers={**_headers(token), "Prefer": "resolution=ignore-duplicates,return=minimal"},
        timeout=request_timeout,
    )
    if not getattr(constraint_response, "ok", False):
        status_code = int(getattr(constraint_response, "status_code", 0) or 0)
        if status_code == 404:
            return SubscriptionStorePreflight("blocked_prerequisite", "telegram_subscription_table_missing")
        raise _response_error(constraint_response, schema_check=True)
    return SubscriptionStorePreflight("ready")


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
    request_get: Callable[..., Any] = requests.get,
    request_post: Callable[..., Any] = requests.post,
) -> int:
    """Insert legacy recipients once, without reactivating existing rows.

    ``ignore-duplicates`` is intentional: a user who already used ``/stop``
    must not be re-enabled by a later migration or a stale secret.
    """
    result = migrate_legacy_chat_ids_result(
        chat_ids,
        editor_chat_id=editor_chat_id,
        url=url,
        key=key,
        timeout=timeout,
        request_get=request_get,
        request_post=request_post,
    )
    if result.migration_status == "blocked_prerequisite":
        raise TelegramSubscriptionError(result.reason or "telegram_subscription_prerequisite_missing")
    return result.migrated_count


def migrate_legacy_chat_ids_result(
    chat_ids: Iterable[str],
    *,
    editor_chat_id: str = "8869592162",
    url: str | None = None,
    key: str | None = None,
    timeout: float = 15.0,
    request_get: Callable[..., Any] = requests.get,
    request_post: Callable[..., Any] = requests.post,
) -> TelegramMigrationResult:
    """Run the migration with an explicit, idempotent outcome contract."""
    base, token = _credentials(url, key)
    preflight = check_subscription_store(
        url,
        key,
        timeout=timeout,
        request_get=request_get,
        request_post=request_post,
    )
    if preflight.status == "blocked_prerequisite":
        return TelegramMigrationResult(
            migration_status="blocked_prerequisite",
            prerequisite_status="missing",
            migrated_count=0,
            reason=preflight.reason,
        )
    normalized = list(dict.fromkeys(
        value for value in (str(item).strip() for item in [*chat_ids, editor_chat_id])
        if _CHAT_ID.fullmatch(value)
    ))
    if not normalized:
        return TelegramMigrationResult(
            migration_status="already_applied",
            prerequisite_status="ready",
            migrated_count=0,
            reason="no_valid_legacy_recipients",
        )
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
        raise _response_error(response)
    try:
        payload = response.json()
    except (TypeError, ValueError, requests.exceptions.JSONDecodeError) as exc:
        raise TelegramSubscriptionError("telegram_subscription_invalid_response") from exc
    if not isinstance(payload, list):
        raise TelegramSubscriptionError("telegram_subscription_invalid_response")
    migrated_count = len(_validated_ids(payload))
    return TelegramMigrationResult(
        migration_status="applied" if migrated_count else "already_applied",
        prerequisite_status="ready",
        migrated_count=migrated_count,
        reason=None if migrated_count else "all_recipients_already_present",
    )


__all__ = [
    "TelegramSubscriptionError",
    "SubscriptionStorePreflight",
    "TelegramMigrationResult",
    "check_subscription_store",
    "fetch_active_chat_ids",
    "migrate_legacy_chat_ids",
    "migrate_legacy_chat_ids_result",
]
