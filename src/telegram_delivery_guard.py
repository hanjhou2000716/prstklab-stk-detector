"""Signed client for the durable per-recipient Telegram send guard.

The guard is deliberately a separate request from Telegram.  A send is never
attempted unless the Worker durably reserves and starts that recipient's
attempt.  Once the request may have reached Telegram, uncertain outcomes are
terminal for automatic replay.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import requests

from src.railway_secret import delivery_shared_secret

HASH_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_ATTEMPTS = 3
LEASE_SECONDS = 60
DEFAULT_REALTIME_TTL = timedelta(minutes=15)


class DeliveryGuardError(RuntimeError):
    """Guard unavailable or rejected the transition; never send on this path."""


@dataclass(frozen=True)
class GuardReservation:
    allowed: bool
    status: str
    attempt_id: str = ""
    message_id: int | None = None
    retry_after_at: datetime | None = None


def _target_url() -> str:
    configured = os.environ.get("RECEIPT_CALLBACK_URL", "").strip().rstrip("/")
    if not configured:
        raise DeliveryGuardError("delivery_guard_not_configured")
    suffix = "/api/delivery-receipt"
    if configured.endswith(suffix):
        return configured[: -len(suffix)] + "/api/delivery-attempts"
    if configured.endswith("/api/delivery-attempts"):
        return configured
    raise DeliveryGuardError("delivery_guard_endpoint_invalid")


def _secret() -> str:
    return os.environ.get("DELIVERY_RECEIPT_SHARED_SECRET", "").strip() or delivery_shared_secret()


def _hash(value: str) -> str:
    if not value:
        raise DeliveryGuardError("delivery_guard_identity_missing")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DeliveryGuardError("delivery_guard_deadline_invalid")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def resolve_deadline(value: datetime | str | None) -> datetime:
    """Parse an event's immutable expiry or create the bounded first-use TTL."""
    if value is None or value == "":
        return default_realtime_deadline()
    if isinstance(value, datetime):
        _iso(value)
        return value.astimezone(UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise DeliveryGuardError("delivery_guard_deadline_invalid") from exc
        _iso(parsed)
        return parsed.astimezone(UTC)
    raise DeliveryGuardError("delivery_guard_deadline_invalid")


def _post(payload: dict[str, object]) -> dict[str, object]:
    target_url = _target_url()
    secret = _secret()
    if not secret:
        raise DeliveryGuardError("delivery_guard_secret_missing")
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    try:
        response = requests.post(
            target_url, data=body,
            headers={"Content-Type": "application/json", "X-PRSTK-Signature": signature},
            timeout=10,
        )
    except requests.RequestException as exc:
        raise DeliveryGuardError("delivery_guard_transport_unknown") from exc
    if not response.ok:
        raise DeliveryGuardError(f"delivery_guard_http_{response.status_code}")
    try:
        value = response.json()
    except ValueError as exc:
        raise DeliveryGuardError("delivery_guard_response_invalid") from exc
    if not isinstance(value, dict) or value.get("ok") is not True:
        raise DeliveryGuardError("delivery_guard_response_invalid")
    return value


def _identity(notification_key: str, chat_id: str) -> tuple[str, str]:
    notification_hash = _hash(notification_key)
    recipient_hash = _hash(chat_id)
    if not HASH_RE.fullmatch(notification_hash) or not HASH_RE.fullmatch(recipient_hash):
        raise DeliveryGuardError("delivery_guard_identity_invalid")
    return notification_hash, recipient_hash


def reserve_and_start(
    *, notification_key: str, chat_id: str, deadline_at: datetime,
) -> GuardReservation:
    """Obtain both durable transitions before making exactly one send call."""
    notification_hash, recipient_hash = _identity(notification_key, chat_id)
    attempt_id = str(uuid.uuid4())
    base: dict[str, object] = {
        "notification_hash": notification_hash,
        "recipient_hash": recipient_hash,
        "attempt_id": attempt_id,
    }
    reserved = _post({
        **base, "operation": "reserve", "deadline_at": _iso(deadline_at),
        "lease_seconds": LEASE_SECONDS,
    })
    if reserved.get("status") != "reserved":
        message_id = reserved.get("message_id")
        retry_after_at = reserved.get("retry_after_at")
        parsed_retry_after: datetime | None = None
        if isinstance(retry_after_at, str):
            try:
                parsed_retry_after = datetime.fromisoformat(retry_after_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise DeliveryGuardError("delivery_guard_response_invalid") from exc
            if parsed_retry_after.tzinfo is None or parsed_retry_after.utcoffset() is None:
                raise DeliveryGuardError("delivery_guard_response_invalid")
        return GuardReservation(
            False, str(reserved.get("status") or "blocked"),
            message_id=message_id if isinstance(message_id, int) else None,
            retry_after_at=parsed_retry_after.astimezone(UTC) if parsed_retry_after else None,
        )
    # If this response is lost, the start call fails closed.  The reservation
    # can be reclaimed after its short lease because Telegram was not called.
    started = _post({**base, "operation": "start"})
    if started.get("status") != "sending":
        return GuardReservation(False, str(started.get("status") or "blocked"))
    return GuardReservation(True, "sending", attempt_id)


def record_result(
    *, notification_key: str, chat_id: str, attempt_id: str, status: str,
    message_id: int | None = None, retry_after_at: datetime | None = None,
) -> str:
    """Persist the bounded result. Failure leaves the lease to become unknown."""
    if status not in {"delivered", "retryable_failed", "terminal_failed", "delivery_unknown"}:
        raise DeliveryGuardError("delivery_guard_result_invalid")
    notification_hash, recipient_hash = _identity(notification_key, chat_id)
    value = _post({
        "notification_hash": notification_hash,
        "recipient_hash": recipient_hash,
        "attempt_id": attempt_id,
        "operation": "result",
        "result": status,
        "message_id": message_id,
        "retry_after_at": _iso(retry_after_at) if retry_after_at else None,
    })
    return str(value.get("status") or "unknown")


def default_realtime_deadline(now: datetime | None = None) -> datetime:
    """A stable initial TTL for non-scheduled events; the DB never extends it."""
    return (now or datetime.now(UTC)).astimezone(UTC) + DEFAULT_REALTIME_TTL
