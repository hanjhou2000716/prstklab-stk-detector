"""Authenticated, bounded Gmail Pub/Sub ingress orchestration."""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from email_router import DLQ_STATES, parse_email
from email_store import EmailStore
from gmail_watch import GmailWatchConfig
from gmail_watch import health as watch_health

MAX_BODY_BYTES = 256 * 1024


class GmailIngressError(ValueError):
    """Raised when the push cannot be accepted safely."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class GmailIngressService:
    def __init__(self, store: EmailStore, config: GmailWatchConfig) -> None:
        self.store = store
        self.config = config

    def _authenticate(self, headers: Mapping[str, str]) -> None:
        if self.config.missing:
            raise GmailIngressError("gmail_gateway_configuration_missing")
        auth = headers.get("authorization", "")
        audience = headers.get("x-goog-authenticated-audience", "")
        service_account = headers.get("x-goog-authenticated-user-email", "").removeprefix("accounts.google.com:")
        if not auth.casefold().startswith("bearer "):
            raise GmailIngressError("unauthenticated_pubsub_push")
        if audience != self.config.audience:
            raise GmailIngressError("pubsub_audience_mismatch")
        if service_account != self.config.service_account:
            raise GmailIngressError("pubsub_service_account_mismatch")

    def decode_push(self, body: bytes | str, headers: Mapping[str, str]) -> dict[str, Any]:
        self._authenticate(headers)
        raw = body.encode("utf-8") if isinstance(body, str) else body
        if len(raw) > MAX_BODY_BYTES:
            raise GmailIngressError("push_body_too_large")
        try:
            envelope = json.loads(raw.decode("utf-8"))
            message = envelope["message"]
            encoded = message["data"]
            payload = json.loads(base64.b64decode(encoded, validate=True).decode("utf-8"))
        except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error) as error:
            raise GmailIngressError("invalid_pubsub_envelope") from error
        if not isinstance(payload, dict):
            raise GmailIngressError("invalid_gmail_notification")
        return {
            "gmail_address": str(payload.get("emailAddress") or ""),
            "history_id": str(payload.get("historyId") or ""),
            "publish_time": message.get("publishTime"),
        }

    def accept_email(self, record: dict[str, Any]) -> dict[str, Any]:
        parsed = parse_email(record)
        message_id = parsed["gmail_message_id"]
        observation = {
            "observation_id": f"email-{message_id or parsed['template_fingerprint'][:16]}",
            "gmail_message_id": message_id,
            "content_hash": parsed["template_fingerprint"],
            "parse_status": parsed["parse_status"],
            "parser_version": parsed["parser_version"],
            "received_at": record.get("received_at"),
            "content_origin": parsed["content_origin"],
            "content_type": parsed["content_type"],
        }
        if parsed["parse_status"] in DLQ_STATES:
            self.store.record_dlq(
                message_id=message_id or "unknown",
                parser_name=parsed["parser_name"],
                parser_version=parsed["parser_version"],
                template_fingerprint=parsed["template_fingerprint"],
                parse_status=parsed["parse_status"],
                failure_reason=str(parsed.get("failure_reason") or "parse_failed"),
                metadata={"content_origin": parsed["content_origin"]},
            )
            return {"accepted": False, "status": parsed["parse_status"], "observation": observation}
        claimed = self.store.claim_observation(observation)
        if not claimed:
            observation["parse_status"] = "duplicate"
            return {"accepted": False, "status": "duplicate", "observation": observation}
        self.store.save_cursor(last_message_id=message_id, last_notification_at=_now(), last_sync_at=_now())
        return {"accepted": True, "status": parsed["parse_status"], "observation": observation}

    def health(self) -> dict[str, Any]:
        return {"watch": watch_health(self.config, self.store.cursor()), "store": self.store.health()}


__all__ = ["GmailIngressError", "GmailIngressService"]
