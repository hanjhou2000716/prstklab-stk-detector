"""Authenticated, bounded Gmail Pub/Sub ingress orchestration."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from email_router import DLQ_STATES, parse_email
from email_store import FJ_VENDOR_PRIORITY_THRESHOLD, EmailStore
from gmail_watch import GmailWatchConfig, GmailWatchManager
from gmail_watch import health as watch_health

MAX_BODY_BYTES = 256 * 1024


class GmailIngressError(ValueError):
    """Raised when the push cannot be accepted safely."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _message_content_hash(record: Mapping[str, Any]) -> str:
    """Hash message content for exact-content deduplication.

    The template fingerprint intentionally describes a provider format and is
    therefore shared by many different emails.  It must not be used as the
    unique content key in the durable observation store.
    """
    subject = str(record.get("subject") or "")
    body = str(record.get("body") or "")
    raw_attachments = record.get("attachments")
    attachments: list[Mapping[str, Any]] = (
        [item for item in raw_attachments if isinstance(item, Mapping)]
        if isinstance(raw_attachments, list)
        else []
    )
    mime_types = [str(item.get("mime_type") or "") for item in attachments]
    material = "\x1f".join((subject, body, *mime_types))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _fresh_financialjuice_candidate(row: Mapping[str, Any]) -> bool:
    """Only a newly received, timestamped FJ fact may wake the monitor."""
    return _financialjuice_candidate_reason(row) == ""


def _financialjuice_candidate_reason(
    row: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> str:
    """Explain why one sanitized FJ row cannot wake the event monitor.

    This classifier deliberately uses the source publication time only.  It
    is also kept content-free so the reason can safely be projected to the
    Actions summary and the public health diagnostics.
    """
    if str(row.get("content_origin") or row.get("source") or "").strip().casefold() != "financialjuice":
        return "not_financialjuice"
    value = row.get("source_published_at")
    if not value:
        return "missing_source_time"
    try:
        published = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return "invalid_source_time"
    published = published.replace(tzinfo=published.tzinfo or UTC).astimezone(UTC)
    age = ((now or datetime.now(UTC)).astimezone(UTC) - published).total_seconds()
    if age < -300:
        return "future_source_time"
    if age > 1800:
        return "stale_source_event"
    return ""


_CANDIDATE_DIAGNOSTIC_KEYS = (
    "new_event_eligible", "duplicate_message", "duplicate_fact", "stale_source_event",
    "missing_source_time", "invalid_source_time", "future_source_time", "incomplete_parse",
    "below_notification_gate", "below_priority_gate", "priority_event_eligible",
    "manual_replay", "downstream_dispatch_failure",
)


def _candidate_diagnostics(
    rows: list[Mapping[str, Any]],
    store: EmailStore,
    *,
    source_is_financialjuice: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return bounded per-message candidate counts and a primary reason."""
    counts = {key: 0 for key in _CANDIDATE_DIAGNOSTIC_KEYS}
    batch_fact_keys: set[str] = set()
    saw_financialjuice = False
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("content_origin") or row.get("source") or "").strip().casefold() != "financialjuice":
            continue
        saw_financialjuice = True
        freshness_reason = _financialjuice_candidate_reason(row, now=now)
        if freshness_reason:
            counts[freshness_reason] += 1
            continue
        if row.get("source_identity_verified") is False:
            counts["incomplete_parse"] += 1
            continue
        try:
            importance = float(row.get("vendor_importance"))
        except (TypeError, ValueError, OverflowError):
            importance = 0.0
        # Scores below the priority floor may still enter the ordinary event
        # lane when the fact is complete.  Only a missing/invalid score uses
        # the legacy notification-gate diagnostic below.
        if importance <= 0:
            counts["below_notification_gate"] += 1
            continue
        if importance < FJ_VENDOR_PRIORITY_THRESHOLD:
            counts["below_priority_gate"] += 1
        fact_key = str(row.get("canonical_fact_key") or "").strip()
        if not fact_key:
            counts["incomplete_parse"] += 1
        elif fact_key in batch_fact_keys:
            counts["duplicate_fact"] += 1
        else:
            # Public observation storage is not a delivery receipt.  A fact
            # already saved by an earlier sync may still have no Telegram
            # receipt (for example when the old 8/10 gate rejected it).  Let
            # the shared notification claim decide whether this is a true
            # replay, while keeping the fact duplicate visible in diagnostics.
            try:
                already_observed = store.public_fact_exists(fact_key)
            except Exception:
                already_observed = False
            if already_observed:
                counts["duplicate_fact"] += 1
            if importance >= FJ_VENDOR_PRIORITY_THRESHOLD:
                counts["priority_event_eligible"] += 1
            counts["new_event_eligible"] += 1
            batch_fact_keys.add(fact_key)
    if source_is_financialjuice and not saw_financialjuice:
        counts["incomplete_parse"] += 1
    priority = (
        "stale_source_event", "missing_source_time", "invalid_source_time",
        "incomplete_parse", "duplicate_fact", "future_source_time",
        "below_notification_gate", "below_priority_gate", "manual_replay",
        "downstream_dispatch_failure",
    )
    primary = next((key for key in priority if counts[key]), "")
    return {"counts": counts, "primary_reason": primary}


def _normalize_service_account(value: str) -> str:
    """Normalize documented Pub/Sub identity header variants.

    Pub/Sub push delivery can expose the authenticated principal as either
    ``accounts.google.com:<email>`` or ``accounts.google.com:serviceAccount:<email>``
    depending on the push-auth path.  Remove only these documented prefixes;
    the caller still performs an exact match against the configured account.
    """
    normalized = value.strip()
    prefixes = (
        "https://accounts.google.com:",
        "accounts.google.com:",
        "serviceAccount:",
        "serviceaccount:",
    )
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            if normalized.casefold().startswith(prefix.casefold()):
                normalized = normalized[len(prefix):].strip()
                changed = True
                break
    return normalized


class GmailIngressService:
    def __init__(
        self,
        store: EmailStore,
        config: GmailWatchConfig,
        *,
        token_verifier: Callable[[str, str], bool | Mapping[str, Any]] | None = None,
    ) -> None:
        self.store = store
        self.config = config
        self.token_verifier = token_verifier

    def ensure_watch(self) -> dict[str, Any]:
        """Create or renew the Gmail lease when it is missing or near expiry.

        Renewal errors are returned as a bounded diagnostic and persisted by
        the manager; they must not prevent the Pub/Sub health server from
        starting or accepting a later retry.
        """
        return GmailWatchManager(self.config, self.store).ensure_watch()

    def _authenticate(self, headers: Mapping[str, str]) -> None:
        if self.config.missing:
            raise GmailIngressError("gmail_gateway_configuration_missing")
        auth = headers.get("authorization", "")
        audience = headers.get("x-goog-authenticated-audience", "")
        header_identity = _normalize_service_account(headers.get("x-goog-authenticated-user-email", ""))
        verified_identity = ""
        if not auth.casefold().startswith("bearer "):
            raise GmailIngressError("unauthenticated_pubsub_push")
        token = auth.split(" ", 1)[1].strip()
        if self.config.require_jwt_verification:
            if self.token_verifier is None:
                raise GmailIngressError("pubsub_jwt_verification_failed")
            verification = self.token_verifier(token, self.config.audience)
            if not verification:
                raise GmailIngressError("pubsub_jwt_verification_failed")
            if isinstance(verification, Mapping):
                verified_identity = _normalize_service_account(str(verification.get("email") or ""))
                if not verified_identity:
                    raise GmailIngressError("pubsub_jwt_identity_missing")
        # Pub/Sub authenticated push requests carry the configured audience
        # in the OIDC JWT ``aud`` claim. The optional frontend header is not
        # guaranteed, so validate it only when the sender supplies it.
        # Strict JWT mode still validates the claim through token_verifier.
        if audience and audience != self.config.audience:
            raise GmailIngressError("pubsub_audience_mismatch")
        service_account = verified_identity or header_identity
        if verified_identity and header_identity and header_identity != verified_identity:
            raise GmailIngressError("pubsub_service_account_mismatch")
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
        public_rows = parsed.get("public_observations")
        public_rich_count = sum(
            1
            for row in (public_rows if isinstance(public_rows, list) else [])
            if isinstance(row, dict)
            and any(str(row.get(key) or "").strip() for key in (
                "original_headline", "chinese_translation", "ai_commentary", "possible_impact",
                "vendor_original_headline", "vendor_translation", "vendor_analysis", "vendor_possible_impact",
            ))
        )
        semantic_field_counts = {
            key: sum(
                1
                for row in (public_rows if isinstance(public_rows, list) else [])
                if isinstance(row, dict) and str(row.get(key) or "").strip()
            )
            for key in (
                "original_headline", "chinese_translation", "ai_commentary", "possible_impact",
                "vendor_original_headline", "vendor_translation", "vendor_analysis", "vendor_possible_impact",
            )
        }
        observation = {
            "observation_id": f"email-{message_id or parsed['template_fingerprint'][:16]}",
            "gmail_message_id": message_id,
            "content_hash": _message_content_hash(record),
            "parse_status": parsed["parse_status"],
            "parser_version": parsed["parser_version"],
            "received_at": record.get("received_at"),
            "content_origin": parsed["content_origin"],
            "content_type": parsed["content_type"],
            "public_rich_observation_count": public_rich_count,
            "public_semantic_field_counts": semantic_field_counts,
        }
        source_is_financialjuice = str(parsed["content_origin"] or "").strip().casefold() == "financialjuice"
        public_rows_for_diagnostics = public_rows if isinstance(public_rows, list) else []
        diagnostics = _candidate_diagnostics(
            [row for row in public_rows_for_diagnostics if isinstance(row, Mapping)],
            self.store,
            source_is_financialjuice=source_is_financialjuice,
        )
        observation["candidate_diagnostics"] = diagnostics
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
            return {
                "accepted": False, "status": parsed["parse_status"], "observation": observation,
                "candidate_diagnostics": diagnostics,
            }
        claimed = self.store.claim_observation(observation)
        if not claimed:
            # A replay can carry a richer MIME part after a parser or Gmail
            # attachment fix.  Refresh only the sanitized public projection;
            # the private message claim and downstream notification identity
            # remain idempotent, so enrichment cannot create a second alert.
            refreshed_public = 0
            for row in public_rows if isinstance(public_rows, list) else []:
                if not isinstance(row, dict):
                    continue
                try:
                    if self.store.save_public_observation(row):
                        refreshed_public += 1
                except (TypeError, ValueError):
                    continue
            observation["parse_status"] = "duplicate"
            observation["public_observation_count"] = refreshed_public
            # A content-duplicate high-priority mail can still represent the
            # only durable trigger for a previously parsed-but-not-delivered
            # fact.  Re-enter the shared monitor; EventLedger and the sender
            # claim remain the final exactly-once guard.
            priority_candidate = diagnostics["counts"]["priority_event_eligible"] > 0
            return {
                "accepted": False, "status": "duplicate", "observation": observation,
                "public_observation_count": refreshed_public,
                "public_rich_observation_count": public_rich_count,
                "public_semantic_field_counts": semantic_field_counts,
                "material_candidate": priority_candidate,
                "priority_candidate": priority_candidate,
                "candidate_diagnostics": {"counts": {**diagnostics["counts"], "new_event_eligible": 0, "duplicate_message": 1}, "primary_reason": "duplicate_message"},
            }
        diagnostic_counts = diagnostics["counts"]
        material_candidate = bool(
            diagnostic_counts["new_event_eligible"] > 0
            or diagnostic_counts["priority_event_eligible"] > 0
        )
        saved_public = 0
        if isinstance(public_rows, list):
            for row in public_rows:
                if not isinstance(row, dict):
                    continue
                try:
                    if self.store.save_public_observation(row):
                        saved_public += 1
                except (TypeError, ValueError):
                    # A malformed derived row is isolated to this message;
                    # the private observation remains durably recorded and
                    # the parser contract exposes the failure on the next
                    # health projection rather than dropping the whole batch.
                    continue
        observation["public_observation_count"] = saved_public
        return {
            "accepted": True, "status": parsed["parse_status"], "observation": observation,
            "public_observation_count": saved_public,
            "public_rich_observation_count": public_rich_count,
            "public_semantic_field_counts": semantic_field_counts,
            "material_candidate": material_candidate,
            "priority_candidate": diagnostic_counts["priority_event_eligible"] > 0,
            "candidate_diagnostics": diagnostics,
        }

    def health(self) -> dict[str, Any]:
        store_health = self.store.health()
        cursor = store_health.get("cursor")
        if not isinstance(cursor, Mapping):
            cursor = self.store.cursor()
        return {
            "watch": watch_health(self.config, cursor, store_health=store_health),
            "store": store_health,
        }

    def accept_push(self, body: bytes | str, headers: Mapping[str, str]) -> dict[str, Any]:
        """Authenticate and durably record one bounded Gmail notification.

        Pub/Sub notifications contain only a Gmail history cursor. Message
        bodies are fetched separately by the worker and never enter this HTTP
        handler or its logs.
        """
        notification = self.decode_push(body, headers)
        history_id = str(notification.get("history_id") or "").strip()
        if not history_id:
            raise GmailIngressError("gmail_history_id_missing")
        received_at = _now()
        # A Pub/Sub history cursor is a notification hint, not an acknowledged
        # Gmail sync cursor.  Keep it pending until the bounded history worker
        # completes; advancing last_history_id here can permanently skip mail
        # when the downstream dispatch or runner fails.
        current = self.store.save_cursor(
            pending_history_id=history_id,
            last_push_received_at=received_at,
            # Keep the legacy field populated for old health readers.  New
            # readers must use last_push_received_at.
            last_notification_at=received_at,
        )
        record_event = getattr(self.store, "record_pubsub_event", None)
        if callable(record_event):
            record_event(history_id, received_at=received_at)
        return {"accepted": True, "history_id": history_id, "cursor": current}


__all__ = ["GmailIngressError", "GmailIngressService"]
