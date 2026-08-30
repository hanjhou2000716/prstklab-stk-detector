"""Supabase-backed implementation of the canonical Gmail store contract.

This is deliberately a storage adapter, not a second Gmail pipeline.  It
implements the methods consumed by ``GmailWatchManager`` and
``GmailHistorySync`` so the same parser and safety rules work without a
Railway filesystem or persistent volume.
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from typing import Any

import requests

CURSOR_FIELDS = (
    "watch_expiration", "watch_last_renewed_at", "watch_error", "watch_error_at",
    "last_history_id", "pending_history_id", "last_notification_at", "last_sync_at",
    "last_full_sync_at", "last_message_id",
)
DEFAULT_CURSOR = {key: None for key in CURSOR_FIELDS}
BLOCKED_FIELDS = {"body", "raw_body", "attachments", "gmail_thread_id", "sender", "recipient"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class SupabaseEmailStore:
    """REST adapter with the same privacy and idempotency contract as EmailStore."""

    def __init__(self, url: str | None = None, key: str | None = None, *, timeout: float = 15.0) -> None:
        self.url = str(url or os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
        self.key = str(key or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
        self.timeout = max(1.0, min(30.0, float(timeout)))
        if not self.url or not self.key:
            raise ValueError("supabase_store_not_configured")
        if not self.url.startswith("https://"):
            raise ValueError("supabase_url_must_use_https")

    def _request(self, method: str, table: str, query: str = "", body: Any = None, *, prefer: str = "return=representation") -> tuple[int, Any]:
        response = requests.request(
            method,
            f"{self.url}/rest/v1/{table}{query}",
            headers={
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Prefer": prefer,
            },
            json=body,
            timeout=self.timeout,
        )
        payload: Any = None
        try:
            payload = response.json()
        except (ValueError, requests.exceptions.JSONDecodeError):
            payload = None
        if response.status_code >= 400:
            # Never expose a provider response body: it can contain private
            # database details.  Callers only receive a stable class label.
            raise RuntimeError(f"supabase_http_{response.status_code}")
        return int(response.status_code), payload

    def cursor(self) -> dict[str, Any]:
        _status, payload = self._request("GET", "gmail_watch_state", "?id=eq.primary&select=*&limit=1")
        row = payload[0] if isinstance(payload, list) and payload and isinstance(payload[0], dict) else {}
        return {key: row.get(key) for key in CURSOR_FIELDS}

    def save_cursor(self, **values: Any) -> dict[str, Any]:
        current = self.cursor()
        current.update({key: value for key, value in values.items() if key in CURSOR_FIELDS})
        current["id"] = "primary"
        current["updated_at"] = _now()
        self._request(
            "POST", "gmail_watch_state", "?on_conflict=id", current,
            prefer="resolution=merge-duplicates,return=representation",
        )
        current.pop("id", None)
        current.pop("updated_at", None)
        return current

    def claim_observation(self, observation: dict[str, Any]) -> bool:
        message_id = str(observation.get("gmail_message_id") or "").strip()
        if not message_id:
            raise ValueError("gmail_message_id is required")
        content_hash = observation.get("body_hash") or observation.get("content_hash")
        metadata = {key: value for key, value in observation.items() if key not in BLOCKED_FIELDS}
        row = {
            "gmail_message_id": message_id,
            "observation_id": str(observation.get("observation_id") or f"email-{_hash(message_id)[:16]}"),
            "content_hash": str(content_hash) if content_hash else None,
            "creator_episode_key": observation.get("creator_episode_key"),
            "event_cluster_key": observation.get("event_cluster_key"),
            "parse_status": str(observation.get("parse_status") or "received"),
            "parser_version": str(observation.get("parser_version") or "unknown"),
            "received_at": observation.get("received_at"),
            "metadata_json": metadata,
        }
        _status, payload = self._request(
            "POST", "gmail_email_observations", "?on_conflict=gmail_message_id", row,
            prefer="resolution=ignore-duplicates,return=representation",
        )
        return isinstance(payload, list) and bool(payload)

    def record_dlq(self, *, message_id: str, parser_name: str, parser_version: str, template_fingerprint: str,
                   parse_status: str, failure_reason: str, metadata: dict[str, Any] | None = None) -> None:
        safe = {key: value for key, value in (metadata or {}).items() if key not in BLOCKED_FIELDS}
        self._request("POST", "gmail_email_dlq", "", {
            "gmail_message_id": str(message_id),
            "parser_name": str(parser_name),
            "parser_version": str(parser_version),
            "template_fingerprint": str(template_fingerprint),
            "parse_status": str(parse_status),
            "failure_reason": str(failure_reason),
            "metadata_json": safe,
        }, prefer="return=minimal")

    def save_public_observation(self, observation: dict[str, Any]) -> bool:
        if observation.get("public_safe") is not True:
            raise ValueError("public observation must be marked public_safe")
        if any(observation.get(key) not in (None, "", [], {}) for key in BLOCKED_FIELDS | {"gmail_message_id"}):
            raise ValueError("public observation contains private fields")
        observation_id = str(observation.get("observation_id") or "").strip()
        source = str(observation.get("content_origin") or observation.get("source") or "").strip().casefold()
        if not observation_id or not source:
            raise ValueError("public observation identity is required")
        payload = {key: value for key, value in observation.items() if key not in BLOCKED_FIELDS | {"gmail_message_id"}}
        payload.update({"observation_id": observation_id, "content_origin": source, "source": source, "public_safe": True})
        _status, result = self._request(
            "POST", "gmail_public_observations", "?on_conflict=observation_id",
            {"observation_id": observation_id, "content_origin": source,
             "content_hash": payload.get("content_hash"),
             "published_at": payload.get("published_at") or payload.get("source_published_at"),
             "payload_json": payload},
            prefer="resolution=ignore-duplicates,return=representation",
        )
        return isinstance(result, list) and bool(result)

    def public_observations(self, *, limit: int = 100) -> list[dict[str, Any]]:
        bounded = max(1, min(500, int(limit)))
        _status, payload = self._request("GET", "gmail_public_observations", f"?select=payload_json&order=created_at.desc,observation_id.desc&limit={bounded}")
        rows = payload if isinstance(payload, list) else []
        return [row["payload_json"] for row in rows if isinstance(row, dict) and isinstance(row.get("payload_json"), dict) and row["payload_json"].get("public_safe") is True]

    def health(self) -> dict[str, Any]:
        cursor = self.cursor()
        return {
            "status": "healthy" if cursor.get("last_sync_at") else "no_new_content",
            "observation_count": 0,
            "dlq_count": 0,
            "queue_pending_count": 0,
            "dead_letter_count": 0,
            "public_observation_count": 0,
            "cursor": cursor,
            "raw_content_stored": False,
            "source_health": self.source_health(),
        }

    def source_health(self) -> dict[str, dict[str, Any]]:
        return {}


__all__ = ["SupabaseEmailStore"]
