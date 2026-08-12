"""Fail-closed Gmail Watch/PubSub ingress primitives.

This module does not call Gmail or Pub/Sub.  It validates the transport
envelope, decodes only bounded message metadata, and makes history replay
idempotent so a Railway restart cannot duplicate observations.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass, field
from typing import Any

MAX_PUSH_BYTES = 256 * 1024
MAX_HISTORY_IDS = 1000


class GmailIngressError(ValueError):
    """Raised when an inbound push cannot be safely accepted."""


@dataclass
class GmailCursor:
    """Durable state shape for a Gmail history cursor."""

    last_history_id: str | None = None
    last_notification_at: str | None = None
    last_sync_at: str | None = None
    last_full_sync_at: str | None = None
    last_message_id: str | None = None
    watch_expiration: str | None = None
    seen_message_ids: set[str] = field(default_factory=set)

    def as_public_health(self) -> dict[str, Any]:
        """Return non-sensitive health metadata; IDs are not message content."""
        return {
            "watch_active": bool(self.watch_expiration),
            "watch_expiration": self.watch_expiration,
            "last_history_id": self.last_history_id,
            "last_notification_at": self.last_notification_at,
            "last_sync_at": self.last_sync_at,
            "last_full_sync_at": self.last_full_sync_at,
            "last_message_id": self.last_message_id,
            "dedupe_size": len(self.seen_message_ids),
        }


def validate_push_headers(
    *,
    authorization: str | None,
    audience: str | None,
    expected_audience: str | None,
    service_account: str | None,
    expected_service_account: str | None,
) -> None:
    """Require an upstream-verified identity before parsing a push body."""
    if not authorization or not authorization.casefold().startswith("bearer "):
        raise GmailIngressError("missing authenticated Pub/Sub bearer token")
    if expected_audience and audience != expected_audience:
        raise GmailIngressError("Pub/Sub audience mismatch")
    if expected_service_account and service_account != expected_service_account:
        raise GmailIngressError("Pub/Sub service account mismatch")


def decode_push_body(body: bytes | str) -> dict[str, Any]:
    """Decode a bounded Pub/Sub envelope without logging raw content."""
    raw = body.encode("utf-8") if isinstance(body, str) else body
    if len(raw) > MAX_PUSH_BYTES:
        raise GmailIngressError("Pub/Sub request body exceeds limit")
    try:
        envelope = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GmailIngressError("invalid Pub/Sub JSON envelope") from exc
    if not isinstance(envelope, dict) or not isinstance(envelope.get("message"), dict):
        raise GmailIngressError("Pub/Sub message envelope is missing")
    message = envelope["message"]
    encoded = message.get("data")
    if not isinstance(encoded, str) or not encoded:
        raise GmailIngressError("Pub/Sub message data is missing")
    try:
        decoded = base64.b64decode(encoded, validate=True)
        payload = json.loads(decoded.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GmailIngressError("invalid Gmail notification payload") from exc
    if not isinstance(payload, dict):
        raise GmailIngressError("Gmail notification payload must be an object")
    return {
        "message_id": str(payload.get("emailAddress") or ""),
        "history_id": str(payload.get("historyId") or ""),
        "publish_time": message.get("publishTime"),
        "subscription": envelope.get("subscription"),
    }


def accept_history_ids(cursor: GmailCursor, history_ids: list[str]) -> list[str]:
    """Dedupe history IDs and advance the cursor only for accepted values."""
    if len(history_ids) > MAX_HISTORY_IDS:
        raise GmailIngressError("history page exceeds limit")
    accepted: list[str] = []
    for value in history_ids:
        history_id = str(value).strip()
        if not history_id or history_id in cursor.seen_message_ids:
            continue
        cursor.seen_message_ids.add(history_id)
        accepted.append(history_id)
    if accepted:
        cursor.last_history_id = accepted[-1]
    return accepted


def replay_decision(*, cursor_history_id: str | None, requested_start_id: str | None, history_invalid: bool) -> dict[str, Any]:
    """Select incremental replay or bounded full-sync recovery."""
    if history_invalid or (requested_start_id and cursor_history_id and requested_start_id != cursor_history_id):
        return {"mode": "full_sync", "reason": "stale_or_invalid_history_cursor", "start_history_id": None}
    if not cursor_history_id:
        return {"mode": "full_sync", "reason": "no_durable_history_cursor", "start_history_id": None}
    return {"mode": "incremental", "reason": "cursor_valid", "start_history_id": cursor_history_id}


__all__ = [
    "GmailCursor",
    "GmailIngressError",
    "accept_history_ids",
    "decode_push_body",
    "replay_decision",
    "validate_push_headers",
]
