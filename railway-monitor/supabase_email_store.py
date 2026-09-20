"""Supabase-backed implementation of the canonical Gmail store contract.

This is deliberately a storage adapter, not a second Gmail pipeline.  It
implements the methods consumed by ``GmailWatchManager`` and
``GmailHistorySync`` so the same parser and safety rules work without a
Railway filesystem or persistent volume.
"""

from __future__ import annotations

import hashlib
import os
import random
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import requests

CURSOR_FIELDS = (
    "watch_expiration", "watch_last_renewed_at", "watch_error", "watch_error_at",
    "last_history_id", "pending_history_id", "last_push_received_at",
    "last_notification_at", "last_sync_at", "last_sync_started_at",
    "last_sync_completed_at", "last_sync_status", "last_sync_error",
    "last_full_sync_at", "last_message_id", "last_sync_diagnostics",
)
SYNC_HEALTH_FIELDS = (
    "status", "first_failure_at", "consecutive_failure_count", "last_failure_at",
    "last_error", "last_run_id", "last_run_sha", "last_success_at", "next_retry_at",
)
TRANSIENT_HTTP_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
DEFAULT_CURSOR = {key: None for key in CURSOR_FIELDS}
BLOCKED_FIELDS = {
    "body", "raw_body", "attachments", "gmail_thread_id", "sender", "recipient",
    # These identifiers are useful only inside the private observation table.
    # Never copy a Gmail transport ID into the public projection JSONB.
    "gmail_message_id", "gmail_history_id", "message_id", "thread_id",
    "source_message_id", "episode_id", "email_address",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


_SEMANTIC_FIELDS = (
    "original_headline", "chinese_translation", "vendor_translation",
    "ai_commentary", "vendor_analysis", "possible_impact",
    "vendor_possible_impact", "vendor_impact",
)
_SEMANTIC_LABELS = (
    "original headline", "headline", "translation", "chinese translation",
    "ai commentary", "ai 評論", "AI評論", "analysis", "分析",
    "possible impact", "可能影響", "市場影響", "原文內容", "原文", "重要性評分",
)


def _semantic_quality(payload: dict[str, Any]) -> tuple[int, int, int]:
    """Rank sanitized observations so a replay can enrich, never erase, facts.

    A parser repair can keep the same number of populated fields while
    removing labels accidentally captured inside their values.  Prefer that
    cleaner projection before comparing text length; the merge below still
    copies only non-empty values, so a sparse replay cannot erase facts.
    """
    values: list[str] = []
    for field in _SEMANTIC_FIELDS:
        value = payload.get(field)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            text = " ".join(str(value).split()).strip()
            if text:
                values.append(text)
    noise = sum(
        len(re.findall(re.escape(label) + r"\s*[:：]", value, flags=re.IGNORECASE))
        for value in values
        for label in _SEMANTIC_LABELS
    )
    return len(values), -noise, sum(len(value) for value in values)


class SupabaseEmailStore:
    """REST adapter with the same privacy and idempotency contract as EmailStore."""

    def __init__(
        self,
        url: str | None = None,
        key: str | None = None,
        *,
        timeout: float = 15.0,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self.url = str(url or os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
        self.key = str(key or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
        self.timeout = max(1.0, min(30.0, float(timeout)))
        self._sleep = sleep_fn or time.sleep
        self.last_retry_count = 0
        self.last_request_attempts = 0
        if not self.url or not self.key:
            raise ValueError("supabase_store_not_configured")
        if not self.url.startswith("https://"):
            raise ValueError("supabase_url_must_use_https")

    def _request(self, method: str, table: str, query: str = "", body: Any = None, *, prefer: str = "return=representation") -> tuple[int, Any]:
        method = method.upper()
        # Cursor reads are safe to retry; writes remain single-attempt unless
        # the caller's explicit idempotent operation handles its own conflict.
        retryable = method == "GET"
        attempts = 4 if retryable else 1
        deadline = time.monotonic() + 90.0 if retryable else None
        response: requests.Response | None = None
        self.last_retry_count = 0
        self.last_request_attempts = 0
        for attempt in range(attempts):
            self.last_request_attempts = attempt + 1
            try:
                request_timeout = self.timeout
                if deadline is not None:
                    request_timeout = min(request_timeout, max(1.0, deadline - time.monotonic()))
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
                    timeout=request_timeout,
                )
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as error:
                if not retryable or attempt >= attempts - 1:
                    raise RuntimeError("supabase_transport_error") from error
                self._retry_after(attempt, deadline, None)
                continue
            if response.status_code not in TRANSIENT_HTTP_STATUS_CODES or not retryable or attempt >= attempts - 1:
                break
            headers = getattr(response, "headers", {}) or {}
            retry_after = headers.get("Retry-After") if hasattr(headers, "get") else None
            self._retry_after(attempt, deadline, retry_after)
        if response is None:  # defensive: every loop either returned or raised
            raise RuntimeError("supabase_transport_error")
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

    def _rpc(self, function: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call one private state RPC without exposing provider details."""
        response = requests.request(
            "POST",
            f"{self.url}/rest/v1/rpc/{function}",
            headers={
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=arguments,
            timeout=self.timeout,
        )
        self.last_request_attempts = 1
        if response.status_code >= 400:
            raise RuntimeError(f"supabase_http_{response.status_code}")
        try:
            payload = response.json()
        except (ValueError, requests.exceptions.JSONDecodeError):
            payload = None
        row = payload[0] if isinstance(payload, list) and payload and isinstance(payload[0], dict) else payload
        return row if isinstance(row, dict) else {}

    def _retry_after(self, attempt: int, deadline: float | None, header: str | None) -> None:
        """Sleep within the bounded read retry window without exposing details."""
        try:
            requested = max(0.0, float(str(header).strip())) if header else 0.0
        except (TypeError, ValueError):
            requested = 0.0
        backoff = (1.0, 3.0, 7.0)[min(attempt, 2)]
        # A tiny bounded jitter prevents all five-minute workers from
        # retrying a transient Supabase edge failure in lockstep.
        delay = max(backoff, requested) + random.uniform(0.0, 0.25)
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            delay = min(delay, remaining)
        self.last_retry_count += 1
        self._sleep(delay)

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

    def clear_pending_history_if_matches(self, expected_history_id: str) -> bool:
        """Atomically acknowledge only the pending cursor consumed by a run."""
        expected = str(expected_history_id or "").strip()
        if not expected:
            return False
        encoded = quote(expected, safe="")
        _status, payload = self._request(
            "PATCH",
            "gmail_watch_state",
            f"?id=eq.primary&pending_history_id=eq.{encoded}",
            {"pending_history_id": None},
            prefer="return=representation",
        )
        return isinstance(payload, list) and bool(payload)

    def record_sync_failure(
        self,
        *,
        error: str,
        failed_at: str,
        run_id: str | None = None,
        run_sha: str | None = None,
        next_retry_at: str | None = None,
    ) -> dict[str, Any]:
        """Atomically record one transient sync failure in private state."""
        return self._rpc(
            "record_gmail_sync_failure",
            {
                "p_error": str(error)[:80],
                "p_failed_at": failed_at,
                "p_run_id": str(run_id or "")[:80] or None,
                "p_run_sha": str(run_sha or "")[:80] or None,
                "p_next_retry_at": next_retry_at,
            },
        )

    def clear_sync_failure(self, *, success_at: str) -> dict[str, Any]:
        """Clear transient failure state and return whether recovery occurred."""
        return self._rpc("clear_gmail_sync_failure", {"p_success_at": success_at})

    def sync_health(self) -> dict[str, Any]:
        """Read bounded private sync health for diagnostics."""
        _status, payload = self._request("GET", "gmail_sync_health", "?id=eq.primary&select=*&limit=1")
        row = payload[0] if isinstance(payload, list) and payload and isinstance(payload[0], dict) else {}
        return {key: row.get(key) for key in SYNC_HEALTH_FIELDS}

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
        try:
            _status, payload = self._request(
                "POST", "gmail_email_observations", "?on_conflict=gmail_message_id", row,
                prefer="resolution=ignore-duplicates,return=representation",
            )
        except RuntimeError as error:
            # The table also has a unique exact-content index.  A replay with
            # a new Gmail transport id can therefore conflict on content_hash
            # rather than the upsert target; treat that as the same durable
            # observation instead of aborting the whole history batch.
            if str(error) != "supabase_http_409":
                raise
            return False
        return isinstance(payload, list) and bool(payload)

    def update_pubsub_event(self, history_id: str, **values: Any) -> bool:
        """Update private Pub/Sub processing state after an atomic ingress claim."""
        key = str(history_id or "").strip()
        if not key:
            return False
        allowed = {
            "dispatch_status", "dispatch_requested_at", "sync_started_at",
            "sync_completed_at", "candidate_decided_at", "dispatch_error",
        }
        updates = {name: value for name, value in values.items() if name in allowed}
        if not updates:
            return False
        _status, payload = self._request(
            "PATCH", "gmail_pubsub_events", f"?history_id=eq.{key}",
            updates, prefer="return=representation",
        )
        return isinstance(payload, list) and bool(payload)

    def record_pubsub_event(self, history_id: str, *, received_at: str | None = None) -> bool:
        """Insert one private Pub/Sub event idempotently for reconciliation."""
        key = str(history_id or "").strip()
        if not key:
            return False
        _status, payload = self._request(
            "POST", "gmail_pubsub_events", "?on_conflict=history_id",
            {"history_id": key, "received_at": received_at or _now()},
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
        _status, existing = self._request(
            "GET", "gmail_public_observations",
            f"?observation_id=eq.{observation_id}&select=payload_json&limit=1",
        )
        previous = existing[0].get("payload_json") if isinstance(existing, list) and existing and isinstance(existing[0], dict) else None
        if not isinstance(previous, dict):
            _status, result = self._request(
                "POST", "gmail_public_observations", "?on_conflict=observation_id",
                {"observation_id": observation_id, "content_origin": source,
                 "content_hash": payload.get("content_hash"),
                 "published_at": payload.get("published_at") or payload.get("source_published_at"),
                 "payload_json": payload},
                prefer="resolution=ignore-duplicates,return=representation",
            )
            return isinstance(result, list) and bool(result)
        if _semantic_quality(payload) <= _semantic_quality(previous):
            return False
        merged = dict(previous)
        for key, value in payload.items():
            if value not in (None, "", [], {}):
                merged[key] = value
        self._request(
            "PATCH", "gmail_public_observations", f"?observation_id=eq.{observation_id}",
            {"content_origin": source,
             "content_hash": merged.get("content_hash"),
             "published_at": merged.get("published_at") or merged.get("source_published_at"),
             "payload_json": merged},
            prefer="return=minimal",
        )
        return True

    def public_observations(self, *, limit: int = 100) -> list[dict[str, Any]]:
        bounded = max(1, min(500, int(limit)))
        _status, payload = self._request("GET", "gmail_public_observations", f"?select=payload_json&order=created_at.desc,observation_id.desc&limit={bounded}")
        rows = payload if isinstance(payload, list) else []
        return [row["payload_json"] for row in rows if isinstance(row, dict) and isinstance(row.get("payload_json"), dict) and row["payload_json"].get("public_safe") is True]

    def public_fact_exists(self, canonical_fact_key: str) -> bool:
        """Check the sanitized Supabase projection before waking the monitor.

        Fact identity is stored inside the public-safe JSON projection rather
        than in a second index.  A read failure is intentionally raised so a
        Gmail history batch can retry without acknowledging the message or
        moving its cursor past an unverified dedupe decision.
        """
        key = str(canonical_fact_key or "").strip()
        if not key:
            return False
        _status, payload = self._request(
            "GET", "gmail_public_observations",
            "?select=payload_json&limit=500",
        )
        rows = payload if isinstance(payload, list) else []
        for row in rows:
            value = row.get("payload_json") if isinstance(row, dict) else None
            if isinstance(value, dict) and str(value.get("canonical_fact_key") or "").strip() == key:
                return True
        return False

    def upsert_priority_pending(self, event: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
        """Atomically persist one private FJ summary-recovery state."""
        key = str(event.get("canonical_fact_key") or "").strip()
        version = str(event.get("material_fact_version") or "").strip()
        source_at = str(event.get("source_published_at") or "").strip()
        if not key or not version or not source_at:
            raise ValueError("priority_pending_identity_incomplete")
        try:
            source_dt = datetime.fromisoformat(source_at.replace("Z", "+00:00"))
        except (TypeError, ValueError) as error:
            raise ValueError("priority_pending_source_time_invalid") from error
        source_dt = source_dt.replace(tzinfo=source_dt.tzinfo or UTC).astimezone(UTC)
        checked = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
        event_ref = _hash(f"{key}:{version}")[:32]
        status = str(event.get("public_summary_status") or "pending").strip() or "pending"
        if status not in {"pending", "ready", "expired", "contract_failed"}:
            status = "pending"
        arguments = {
            "p_canonical_fact_key": key,
            "p_material_fact_version": version,
            "p_event_ref": event_ref,
            "p_summary_contract_version": str(event.get("summary_contract_version") or "")[:80],
            "p_summary_status": status,
            "p_summary_reason": str(event.get("public_summary_reason") or "summary_semantics_incomplete")[:120],
            "p_source_published_at": source_dt.isoformat(),
            "p_checked_at": checked,
            "p_last_run_id": str(os.getenv("GITHUB_RUN_ID") or "")[:80] or None,
            "p_last_run_sha": str(os.getenv("GITHUB_SHA") or "")[:80] or None,
        }
        try:
            result = self._rpc("upsert_financialjuice_priority_pending", arguments)
            return result if isinstance(result, dict) else {"event_ref": event_ref, "summary_status": status}
        except RuntimeError as error:
            # Older Supabase deployments may have the table but not the RPC
            # in PostgREST's schema cache.  The table has a composite primary
            # key, so this single-attempt REST upsert is idempotent and safe
            # as a compatibility fallback.  Other errors, especially a 5xx
            # with unknown write outcome, remain hard failures and are never
            # blindly retried.
            if str(error) not in {"supabase_http_400", "supabase_http_404"}:
                raise
            return self._upsert_priority_pending_rest(
                key=key,
                version=version,
                event_ref=event_ref,
                status=status,
                reason=str(arguments["p_summary_reason"]),
                contract=str(arguments["p_summary_contract_version"]),
                source_published_at=source_dt.isoformat(),
                checked_at=checked,
                run_id=arguments["p_last_run_id"],
                run_sha=arguments["p_last_run_sha"],
            )

    def _upsert_priority_pending_rest(
        self,
        *,
        key: str,
        version: str,
        event_ref: str,
        status: str,
        reason: str,
        contract: str,
        source_published_at: str,
        checked_at: str,
        run_id: str | None,
        run_sha: str | None,
    ) -> dict[str, Any]:
        """Use the private table directly when the compatibility RPC is absent."""
        encoded_key = quote(key, safe="")
        encoded_version = quote(version, safe="")
        _status, payload = self._request(
            "GET",
            "financialjuice_priority_pending",
            f"?canonical_fact_key=eq.{encoded_key}&material_fact_version=eq.{encoded_version}&select=first_detected_at,expires_at,attempt_count&limit=1",
        )
        existing = payload[0] if isinstance(payload, list) and payload and isinstance(payload[0], dict) else {}
        first_detected_at = str(existing.get("first_detected_at") or checked_at)
        try:
            source_value = datetime.fromisoformat(source_published_at.replace("Z", "+00:00"))
            source_value = source_value.replace(tzinfo=source_value.tzinfo or UTC).astimezone(UTC)
            calculated_expiry = (source_value + timedelta(minutes=30)).isoformat()
        except (TypeError, ValueError) as error:
            raise ValueError("priority_pending_source_time_invalid") from error
        expires_at = str(existing.get("expires_at") or calculated_expiry)
        try:
            attempts = max(0, int(existing.get("attempt_count") or 0)) + 1
        except (TypeError, ValueError, OverflowError):
            attempts = 1
        body = {
            "canonical_fact_key": key,
            "material_fact_version": version,
            "event_ref": event_ref,
            "summary_contract_version": contract,
            "summary_status": status,
            "summary_reason": reason[:120],
            "source_published_at": source_published_at,
            "first_detected_at": first_detected_at,
            "last_checked_at": checked_at,
            "expires_at": expires_at,
            "attempt_count": attempts,
            "last_run_id": run_id,
            "last_run_sha": run_sha,
            "updated_at": checked_at,
        }
        _status, payload = self._request(
            "POST",
            "financialjuice_priority_pending",
            "?on_conflict=canonical_fact_key%2Cmaterial_fact_version",
            body,
            prefer="resolution=merge-duplicates,return=representation",
        )
        row = payload[0] if isinstance(payload, list) and payload and isinstance(payload[0], dict) else {}
        return row or {"event_ref": event_ref, "summary_status": status, "summary_reason": reason, "expires_at": expires_at, "attempt_count": attempts}

    def priority_pending_events(self, *, now: datetime | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Read only active, identifier-only private pending state."""
        current = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
        bounded = max(1, min(500, int(limit)))
        encoded = quote(current, safe="")
        _status, payload = self._request(
            "GET", "financialjuice_priority_pending",
            f"?summary_status=in.(pending,ready)&expires_at=gt.{encoded}&order=source_published_at.asc&limit={bounded}",
        )
        rows = payload if isinstance(payload, list) else []
        return [row for row in rows if isinstance(row, dict)]

    def mark_priority_pending(self, event: dict[str, Any], *, status: str, reason: str = "") -> bool:
        key = str(event.get("canonical_fact_key") or "").strip()
        version = str(event.get("material_fact_version") or "").strip()
        if not key or not version or status not in {"ready", "expired", "contract_failed"}:
            return False
        encoded_key = quote(key, safe="")
        encoded_version = quote(version, safe="")
        _status, payload = self._request(
            "PATCH", "financialjuice_priority_pending",
            f"?canonical_fact_key=eq.{encoded_key}&material_fact_version=eq.{encoded_version}",
            {"summary_status": status, "summary_reason": str(reason or "")[:120],
             "last_checked_at": _now(), "updated_at": _now()},
            prefer="return=representation",
        )
        return isinstance(payload, list) and bool(payload)

    def health(self) -> dict[str, Any]:
        cursor = self.cursor()
        observation_count = 0
        dlq_count = 0
        public_count = 0
        try:
            _status, payload = self._request(
                "GET", "gmail_email_observations",
                "?select=gmail_message_id&limit=1000",
                prefer="return=representation",
            )
            observation_count = len(payload) if isinstance(payload, list) else 0
            _status, payload = self._request(
                "GET", "gmail_email_dlq", "?select=id&limit=1000",
                prefer="return=representation",
            )
            dlq_count = len(payload) if isinstance(payload, list) else 0
            _status, payload = self._request(
                "GET", "gmail_public_observations", "?select=observation_id&limit=1000",
                prefer="return=representation",
            )
            public_count = len(payload) if isinstance(payload, list) else 0
        except RuntimeError:
            # Health remains available when an optional count query is denied;
            # the stable cursor state still tells operators whether ingress is
            # live, and no provider response body is exposed.
            pass
        fj_status = str(
            (self.source_health().get("financialjuice") or {}).get("status") or "no_new_content"
        )
        return {
            # last_sync_at is retained for old readers, but health must follow
            # the latest completed-sync status and expose a later failure.
            "status": fj_status,
            "observation_count": observation_count,
            "dlq_count": dlq_count,
            "queue_pending_count": 0,
            "dead_letter_count": dlq_count,
            "public_observation_count": public_count,
            "cursor": cursor,
            "raw_content_stored": False,
            "source_health": self.source_health(),
        }

    def source_health(self) -> dict[str, dict[str, Any]]:
        cursor = self.cursor()
        diagnostics = cursor.get("last_sync_diagnostics")
        if not isinstance(diagnostics, dict):
            diagnostics = None
        sync_status = str(cursor.get("last_sync_status") or "").strip().casefold()
        sync_error = str(cursor.get("last_sync_error") or "").strip()
        status = (
            "degraded" if sync_status in {"degraded", "failed", "history_cursor_expired", "running"} or sync_error
            else "healthy" if cursor.get("last_sync_completed_at")
            else "no_new_content"
        )
        try:
            sync_health = self.sync_health()
        except Exception:
            sync_health = {}
        if str(sync_health.get("status") or "") in {"retry_pending", "persistent_failure"}:
            status = "degraded"
        return {
            "financialjuice": {
                "status": status,
                "last_sync_at": cursor.get("last_sync_at"),
                "last_push_received_at": cursor.get("last_push_received_at"),
                "last_sync_started_at": cursor.get("last_sync_started_at"),
                "last_sync_completed_at": cursor.get("last_sync_completed_at"),
                "last_sync_status": sync_status or "not_checked",
                "last_sync_error": sync_error or None,
                "push_delivery_verified": bool(cursor.get("last_push_received_at")),
                "last_sync_diagnostics": diagnostics,
                **{
                    key: sync_health[key]
                    for key in SYNC_HEALTH_FIELDS
                    if sync_health.get(key) is not None
                },
            }
        }


__all__ = ["SupabaseEmailStore"]
