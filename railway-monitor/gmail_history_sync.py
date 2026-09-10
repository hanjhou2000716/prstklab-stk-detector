"""Bounded Gmail History -> canonical parser synchronisation.

The Gmail Watch notification contains only a history cursor.  This adapter
fetches the corresponding ``messageAdded`` records from the official Gmail
API, extracts only the fields needed by the existing canonical parser, and
immediately discards the raw transport payload.  It never persists message
bodies or attachment bytes.
"""

from __future__ import annotations

import base64
import binascii
import html
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any

import httpx
from email_store import EmailStore
from gmail_watch import GmailWatchConfig

from gmail_ingress import GmailIngressService

TOKEN_URL = "https://oauth2.googleapis.com/token"
HISTORY_URL = "https://gmail.googleapis.com/gmail/v1/users/me/history"
MESSAGE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
MESSAGE_LIST_URL = MESSAGE_URL
LATEST_FINANCIALJUICE_QUERY = "{from:financialjuice subject:FinancialJuice}"
DEFAULT_MAX_MESSAGES = 50
MAX_PAGE_SIZE = 100
MAX_HISTORY_PAGES = 20


class GmailHistorySyncError(RuntimeError):
    """Bounded, non-sensitive synchronisation failure."""


_CANDIDATE_DIAGNOSTIC_KEYS = (
    "new_event_eligible", "duplicate_message", "duplicate_fact", "stale_source_event",
    "missing_source_time", "invalid_source_time", "future_source_time", "incomplete_parse",
    "below_notification_gate", "below_priority_gate", "priority_event_eligible",
    "manual_replay", "downstream_dispatch_failure",
)


def _empty_candidate_diagnostics() -> dict[str, Any]:
    return {"counts": {key: 0 for key in _CANDIDATE_DIAGNOSTIC_KEYS}, "primary_reason": ""}


def _merge_candidate_diagnostics(total: dict[str, Any], value: Any) -> None:
    if not isinstance(value, Mapping):
        return
    counts = value.get("counts")
    if isinstance(counts, Mapping):
        target = total.setdefault("counts", {})
        for key in _CANDIDATE_DIAGNOSTIC_KEYS:
            try:
                target[key] = int(target.get(key) or 0) + max(0, int(counts.get(key) or 0))
            except (TypeError, ValueError, OverflowError):
                continue
    reason = str(value.get("primary_reason") or "").strip()
    if reason and not str(total.get("primary_reason") or "").strip():
        total["primary_reason"] = reason


def _with_candidate_diagnostics(result: dict[str, Any], diagnostics: dict[str, Any]) -> dict[str, Any]:
    result["candidate_diagnostics"] = diagnostics
    counts = diagnostics.get("counts") if isinstance(diagnostics, Mapping) else None
    if "priority_candidate_count" not in result:
        try:
            result["priority_candidate_count"] = max(0, int((counts or {}).get("priority_event_eligible") or 0))
        except (TypeError, ValueError, OverflowError):
            result["priority_candidate_count"] = 0
    return result


def _sync_diagnostics_record(
    result: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
    *,
    sync_started_at: str | None = None,
    sync_completed_at: str | None = None,
) -> dict[str, Any]:
    """Build the bounded record exposed to operators and the release export."""
    def counter(key: str) -> int:
        try:
            return max(0, min(1_000_000_000, int(result.get(key) or 0)))
        except (TypeError, ValueError, OverflowError):
            return 0

    counts = diagnostics.get("counts") if isinstance(diagnostics, Mapping) else None
    safe_counts: dict[str, int] = {}
    for key in _CANDIDATE_DIAGNOSTIC_KEYS:
        try:
            safe_counts[key] = max(0, min(1_000_000_000, int(counts.get(key) or 0))) if isinstance(counts, Mapping) else 0
        except (TypeError, ValueError, OverflowError):
            safe_counts[key] = 0
    record = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "status": str(result.get("status") or "unknown")[:80],
        "processed": counter("processed"),
        "accepted_new_count": counter("accepted_new_count"),
        "material_candidate_count": counter("material_candidate_count"),
        "priority_candidate_count": counter("priority_candidate_count"),
        "duplicate_count": counter("duplicate_count"),
        "failed": counter("failed"),
        "candidate_diagnostics": {
            "counts": safe_counts,
            "primary_reason": str(diagnostics.get("primary_reason") or "")[:80],
        },
    }
    if sync_started_at:
        record["sync_started_at"] = str(sync_started_at)
    if sync_completed_at:
        record["sync_completed_at"] = str(sync_completed_at)
    return record


def _persist_sync_diagnostics(
    store: EmailStore,
    result: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
    *,
    sync_started_at: str | None = None,
    complete: bool = False,
) -> None:
    """Persist only counters/reasons; diagnostics must never contain mail data."""
    try:
        completed_at = datetime.now(UTC).isoformat() if complete else None
        values: dict[str, Any] = {
            "last_sync_diagnostics": _sync_diagnostics_record(
                result,
                diagnostics,
                sync_started_at=sync_started_at,
                sync_completed_at=completed_at,
            ),
        }
        if complete:
            status = str(result.get("status") or "unknown")
            failed = int(result.get("failed") or 0)
            values.update({
                "last_sync_completed_at": completed_at,
                "last_sync_status": status,
                "last_sync_error": None if failed == 0 and status in {"healthy", "no_history_cursor"} else status[:80],
            })
            if failed == 0 and status in {"healthy", "no_history_cursor"}:
                # Compatibility readers use last_sync_at; it now means a
                # completed sync only, never a message parse or Pub/Sub push.
                values["last_sync_at"] = completed_at
        store.save_cursor(**values)
    except Exception:  # pragma: no cover - storage failure is already reflected by the sync result
        return


def _mark_sync_started(store: EmailStore) -> str:
    started_at = datetime.now(UTC).isoformat()
    try:
        store.save_cursor(
            last_sync_started_at=started_at,
            last_sync_status="running",
            last_sync_error=None,
        )
    except Exception:  # pragma: no cover - the sync itself will report the failure
        pass
    return started_at


def _manual_replay_result(
    store: EmailStore,
    result: dict[str, Any],
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    """Make the latest-message diagnostic path permanently non-sendable."""
    counts = diagnostics.setdefault("counts", {})
    counts["manual_replay"] = max(1, int(counts.get("manual_replay") or 0))
    counts["new_event_eligible"] = 0
    diagnostics["primary_reason"] = "manual_replay"
    result["material_candidate_count"] = 0
    result["priority_candidate_count"] = 0
    _persist_sync_diagnostics(store, result, diagnostics)
    return _with_candidate_diagnostics(result, diagnostics)


def _recover_expired_cursor(store: EmailStore) -> None:
    """Clear an expired history cursor and force the next Watch renewal.

    Gmail expires history IDs after a bounded retention window.  Retrying the
    same ID forever only creates noisy failures and never recovers delivery.
    Clearing the cursor is fail-closed: the missed interval is explicitly
    reported as a gap, and the next watch renewal establishes a new baseline.
    """
    store.save_cursor(
        last_history_id=None,
        watch_expiration=None,
        watch_error="history_cursor_expired",
        watch_error_at=datetime.now(UTC).isoformat(),
        last_full_sync_at=datetime.now(UTC).isoformat(),
    )


def _header(payload: Mapping[str, Any], name: str) -> str:
    for item in payload.get("headers") or ():
        if isinstance(item, Mapping) and str(item.get("name") or "").casefold() == name.casefold():
            return _decode_header_value(item.get("value"))
    return ""


def _decode_header_value(value: Any) -> str:
    """Decode RFC 2047 Gmail headers before source/creator routing.

    Gmail's full-message API may return encoded-word values for non-ASCII
    display names and subjects.  Comparing those raw values to the canonical
    Creator markers makes valid mail look like ``source_not_recognized`` and
    silently prevents the public observation from being produced.
    """
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw))).strip()
    except (LookupError, UnicodeError, ValueError):
        # Keep ingress fail-soft for malformed third-party headers; the raw
        # value remains bounded and the normal parser will decide whether it
        # is a known source.
        return raw


def _decode(value: Any) -> str:
    if not value:
        return ""
    try:
        raw = base64.urlsafe_b64decode(str(value) + "=" * (-len(str(value)) % 4))
        return raw.decode("utf-8", errors="replace")
    except (ValueError, binascii.Error, UnicodeError):
        return ""


def _walk_text(payload: Mapping[str, Any], parts: list[tuple[str, str]] | None = None) -> list[tuple[str, str]]:
    found = parts if parts is not None else []
    mime = str(payload.get("mimeType") or "").casefold()
    body = payload.get("body") if isinstance(payload.get("body"), Mapping) else {}
    decoded = _decode(body.get("data")) if isinstance(body, Mapping) else ""
    if decoded and mime in {"text/plain", "text/html"}:
        found.append((mime, decoded))
    for child in payload.get("parts") or ():
        if isinstance(child, Mapping):
            _walk_text(child, found)
    return found


def _walk_text_attachments(
    payload: Mapping[str, Any],
    parts: list[tuple[str, str]] | None = None,
) -> list[tuple[str, str]]:
    found = parts if parts is not None else []
    mime = str(payload.get("mimeType") or "").casefold()
    body = payload.get("body") if isinstance(payload.get("body"), Mapping) else {}
    if mime in {"text/plain", "text/html"} and isinstance(body, Mapping):
        attachment_id = str(body.get("attachmentId") or "").strip()
        if attachment_id and not body.get("data"):
            found.append((mime, attachment_id))
    for child in payload.get("parts") or ():
        if isinstance(child, Mapping):
            _walk_text_attachments(child, found)
    return found


_FJ_FIELD_MARKERS = (
    "original headline", "vendor original headline", "headline",
    "translation", "chinese translation", "繁體中文翻譯", "中文翻譯", "翻譯",
    "ai commentary", "vendor analysis", "analysis", "ai 評論", "分析",
    "possible impact", "vendor impact", "impact", "可能影響", "市場影響",
    "importance", "重要性評分", "重要性", "重要度",
)
_FJ_FIELD_PATTERN = "|".join(re.escape(marker) for marker in _FJ_FIELD_MARKERS)


def _body_semantic_score(value: str) -> tuple[int, int]:
    """Score a MIME part by populated FJ labels, without retaining its body."""
    flattened = html.unescape(re.sub(r"<[^>]*>", " ", str(value or "")))
    flattened = " ".join(flattened.split())
    score = 0
    for match in re.finditer(
        rf"(?:{_FJ_FIELD_PATTERN})\s*[:：]?\s*(.*?)"
        rf"(?=(?:{_FJ_FIELD_PATTERN})\s*[:：]|$)",
        flattened,
        re.IGNORECASE,
    ):
        field_value = match.group(1).strip(" \t:-–—")
        if field_value and re.search(r"\w|[^\W\d_]", field_value, re.UNICODE):
            score += 1
    return score, len(flattened)


def _plain_body(payload: Mapping[str, Any]) -> str:
    return _select_body(_walk_text(payload))


def _select_body(parts: list[tuple[str, str]]) -> str:
    plain = next((value for mime, value in parts if mime == "text/plain"), "")
    html_parts = [value for mime, value in parts if mime == "text/html"]
    if not plain:
        return max(html_parts, key=_body_semantic_score, default="")[:256 * 1024]
    if not html_parts:
        return plain[:256 * 1024]
    best_html = max(html_parts, key=_body_semantic_score)
    if _body_semantic_score(best_html) > _body_semantic_score(plain):
        return best_html[:256 * 1024]
    return plain[:256 * 1024]


def _body_selection_summary(parts: list[tuple[str, str]], selected: str) -> dict[str, Any]:
    """Return bounded, content-free diagnostics for a replayed FJ MIME body."""
    selected_score, selected_length = _body_semantic_score(selected)
    return {
        "part_count": len(parts),
        "parts": [
            {
                "mime_type": mime,
                "semantic_marker_count": _body_semantic_score(value)[0],
                "length": _body_semantic_score(value)[1],
            }
            for mime, value in parts
        ],
        "selected_semantic_marker_count": selected_score,
        "selected_length": selected_length,
    }


def _public_projection_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    """Summarise parsed public fields without returning any email text."""
    observation = result.get("observation")
    observation = observation if isinstance(observation, Mapping) else {}
    return {
        "observation_count": int(result.get("public_observation_count") or 0),
        "rich_observation_count": int(result.get("public_rich_observation_count") or 0),
        "semantic_field_counts": result.get("public_semantic_field_counts") or {},
        "ingress_status": str(result.get("status") or ""),
        "parse_status": str(observation.get("parse_status") or ""),
    }


def _sender_domain(value: Any) -> str:
    """Return only a bounded sender domain for operator diagnostics."""
    address = parseaddr(str(value or ""))[1].strip().casefold()
    if "@" not in address:
        return ""
    domain = address.rsplit("@", 1)[-1].strip().rstrip(".")
    return domain if domain and all(char.isalnum() or char in ".-" for char in domain) else ""


async def _message_body(client: Any, token: str, message_id: str, payload: Mapping[str, Any]) -> str:
    parts = _walk_text(payload)
    seen: set[str] = set()
    for mime, attachment_id in _walk_text_attachments(payload):
        if attachment_id in seen:
            continue
        seen.add(attachment_id)
        try:
            attachment = await _get_json(
                client,
                f"{MESSAGE_URL}/{message_id}/attachments/{attachment_id}",
                token,
                {},
            )
        except (GmailHistorySyncError, httpx.TimeoutException, httpx.HTTPError):
            # An optional rich MIME part must not make the whole message
            # disappear.  The direct text/plain part remains available and
            # the parser will fail closed if it has no substantive content.
            continue
        decoded = _decode(attachment.get("data"))
        if decoded:
            parts.append((mime, decoded))
    return _select_body(parts)


def _published_at(value: str) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).astimezone(UTC).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def message_record(message: Mapping[str, Any]) -> dict[str, Any]:
    """Convert one Gmail ``format=full`` response into parser input."""
    payload = message.get("payload") if isinstance(message.get("payload"), Mapping) else {}
    labels = [str(value) for value in (message.get("labelIds") or ()) if value]
    internal_ms = message.get("internalDate")
    received_at = None
    try:
        received_at = datetime.fromtimestamp(int(str(internal_ms)) / 1000, UTC).isoformat()
    except (TypeError, ValueError, OverflowError):
        pass
    return {
        "gmail_message_id": str(message.get("id") or "").strip(),
        "gmail_thread_id": str(message.get("threadId") or "").strip(),
        "sender": _header(payload, "From"),
        "subject": _header(payload, "Subject"),
        "body": _plain_body(payload),
        "received_at": received_at,
        "source_published_at": _published_at(_header(payload, "Date")),
        "attachments": [
            {"mime_type": str(child.get("mimeType") or "")}
            for child in (payload.get("parts") or ())
            if isinstance(child, Mapping) and child.get("filename")
        ],
        "label_ids": labels,
    }


async def _access_token(config: GmailWatchConfig, client: Any) -> str:
    response = await client.post(
        TOKEN_URL,
        data={
            "client_id": config.oauth_client_id,
            "client_secret": config.oauth_client_secret,
            "refresh_token": config.refresh_token,
            "grant_type": "refresh_token",
        },
    )
    if response.status_code >= 400:
        raise GmailHistorySyncError(f"http_{response.status_code}")
    payload = response.json()
    token = payload.get("access_token") if isinstance(payload, Mapping) else None
    if not isinstance(token, str) or not token.strip():
        raise GmailHistorySyncError("access_token_missing")
    return token


async def _get_json(client: Any, url: str, token: str, params: Mapping[str, Any]) -> dict[str, Any]:
    response = await client.get(url, headers={"Authorization": f"Bearer {token}"}, params=dict(params))
    if response.status_code >= 400:
        raise GmailHistorySyncError(f"http_{response.status_code}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise GmailHistorySyncError("invalid_json_response")
    return payload


async def sync_gmail_history(
    config: GmailWatchConfig,
    store: EmailStore,
    ingress: GmailIngressService,
    *,
    client_factory: Callable[..., Any] = httpx.AsyncClient,
    max_messages: int = DEFAULT_MAX_MESSAGES,
) -> dict[str, Any]:
    """Process bounded ``messageAdded`` history and return safe counters."""
    sync_started_at = _mark_sync_started(store)
    diagnostics = _empty_candidate_diagnostics()
    if config.missing:
        result = {"status": "configuration_missing", "processed": 0, "accepted_new_count": 0, "material_candidate_count": 0, "duplicate": 0, "duplicate_count": 0, "failed": 0}
        _persist_sync_diagnostics(store, result, diagnostics, sync_started_at=sync_started_at, complete=True)
        return _with_candidate_diagnostics(result, diagnostics)
    if config.oauth_missing:
        result = {"status": "configuration_missing", "processed": 0, "accepted_new_count": 0, "material_candidate_count": 0, "duplicate": 0, "duplicate_count": 0, "failed": 0}
        _persist_sync_diagnostics(store, result, diagnostics, sync_started_at=sync_started_at, complete=True)
        return _with_candidate_diagnostics(result, diagnostics)
    cursor = store.cursor()
    history_id = str(cursor.get("last_history_id") or "").strip()
    if not history_id:
        result = {"status": "no_history_cursor", "processed": 0, "accepted_new_count": 0, "material_candidate_count": 0, "duplicate": 0, "duplicate_count": 0, "failed": 0}
        store.save_cursor(last_full_sync_at=datetime.now(UTC).isoformat())
        _persist_sync_diagnostics(store, result, diagnostics, sync_started_at=sync_started_at, complete=True)
        return _with_candidate_diagnostics(result, diagnostics)

    bounded = max(1, min(MAX_PAGE_SIZE, int(max_messages)))
    processed = accepted_new = material_candidates = priority_candidates = failed = duplicate = skipped = suppressed = 0
    failure_types: dict[str, int] = {}
    result: dict[str, Any] = {}
    try:
        async with client_factory(timeout=config.timeout_seconds, follow_redirects=True) as client:
            token = await _access_token(config, client)
            message_ids: list[str] = []
            history_page_token = ""
            history_pages = 0
            latest_history = history_id
            pagination_complete = False
            while history_pages < MAX_HISTORY_PAGES:
                params: dict[str, Any] = {
                    "startHistoryId": history_id,
                    "historyTypes": "messageAdded",
                    "maxResults": min(MAX_PAGE_SIZE, max(1, bounded - len(message_ids))),
                }
                if history_page_token:
                    params["pageToken"] = history_page_token
                history = await _get_json(client, HISTORY_URL, token, params)
                history_pages += 1
                latest_history = str(history.get("historyId") or latest_history).strip() or latest_history
                for row in history.get("history") or ():
                    if not isinstance(row, Mapping):
                        continue
                    for added in row.get("messagesAdded") or ():
                        if not isinstance(added, Mapping):
                            continue
                        message = added.get("message")
                        message_id = str(message.get("id") or "").strip() if isinstance(message, Mapping) else ""
                        if message_id and message_id not in message_ids:
                            message_ids.append(message_id)
                        if len(message_ids) >= bounded:
                            break
                    if len(message_ids) >= bounded:
                        break
                history_page_token = str(history.get("nextPageToken") or "").strip()
                if not history_page_token or len(message_ids) >= bounded:
                    pagination_complete = not history_page_token or len(message_ids) >= bounded
                    break
            if history_page_token and history_pages >= MAX_HISTORY_PAGES:
                raise GmailHistorySyncError("history_pagination_limit")
            if not pagination_complete:
                raise GmailHistorySyncError("history_pagination_incomplete")
            for message_id in message_ids:
                try:
                    message = await _get_json(client, f"{MESSAGE_URL}/{message_id}", token, {"format": "full"})
                    record = message_record(message)
                    payload = message.get("payload") if isinstance(message.get("payload"), Mapping) else {}
                    record["body"] = await _message_body(client, token, message_id, payload)
                    result = ingress.accept_email(record)
                    processed += 1
                    _merge_candidate_diagnostics(diagnostics, result.get("candidate_diagnostics"))
                    if result.get("status") == "duplicate":
                        duplicate += 1
                        material_candidates += int(result.get("material_candidate") is True)
                        priority_candidates += int(result.get("priority_candidate") is True)
                    elif result.get("accepted") is True:
                        accepted_new += 1
                        material_candidates += int(result.get("material_candidate") is True)
                        priority_candidates += int(result.get("priority_candidate") is True)
                    elif result.get("status") == "retired_source_suppressed":
                        suppressed += 1
                except GmailHistorySyncError as error:
                    if str(error) == "http_404":
                        skipped += 1
                        continue
                    failed += 1
                    failure_type = type(error).__name__
                    failure_types[failure_type] = failure_types.get(failure_type, 0) + 1
                except (ValueError, TypeError, KeyError, RuntimeError) as error:
                    failed += 1
                    failure_type = type(error).__name__
                    failure_types[failure_type] = failure_types.get(failure_type, 0) + 1
            # Do not acknowledge a Gmail history page when any message failed
            # after fetch.  Keeping the old cursor makes the failed message
            # retryable; already completed messages are idempotent on replay.
            if failed == 0:
                result = {
                    "status": "healthy", "processed": processed,
                    "accepted_new_count": accepted_new,
                    "material_candidate_count": material_candidates,
                    "priority_candidate_count": priority_candidates,
                    "failed": failed, "duplicate": duplicate,
                    "duplicate_count": duplicate,
                }
                if skipped:
                    result["skipped"] = skipped
                if suppressed:
                    result["suppressed"] = suppressed
                if failure_types:
                    result["failure_types"] = dict(sorted(failure_types.items()))
                if history_pages > 1:
                    result["history_pages"] = history_pages
                store.save_cursor(
                    last_history_id=latest_history or history_id,
                    last_full_sync_at=datetime.now(UTC).isoformat(),
                )
                _persist_sync_diagnostics(store, result, diagnostics, sync_started_at=sync_started_at, complete=True)
            else:
                result = {
                    "status": "degraded", "processed": processed,
                    "accepted_new_count": accepted_new,
                    "material_candidate_count": material_candidates,
                    "priority_candidate_count": priority_candidates,
                    "failed": failed, "duplicate": duplicate,
                    "duplicate_count": duplicate,
                }
                if skipped:
                    result["skipped"] = skipped
                if suppressed:
                    result["suppressed"] = suppressed
                if failure_types:
                    result["failure_types"] = dict(sorted(failure_types.items()))
                if history_pages > 1:
                    result["history_pages"] = history_pages
                store.save_cursor(
                    last_full_sync_at=datetime.now(UTC).isoformat(),
                )
                _persist_sync_diagnostics(store, result, diagnostics, sync_started_at=sync_started_at, complete=True)
    except (httpx.TimeoutException, httpx.HTTPError) as error:
        result = {"status": type(error).__name__.lower(), "processed": processed, "accepted_new_count": accepted_new, "material_candidate_count": material_candidates, "priority_candidate_count": priority_candidates, "failed": failed + 1, "duplicate": duplicate, "duplicate_count": duplicate}
        if suppressed:
            result["suppressed"] = suppressed
        store.save_cursor(last_full_sync_at=datetime.now(UTC).isoformat())
        _persist_sync_diagnostics(store, result, diagnostics, sync_started_at=sync_started_at, complete=True)
        return _with_candidate_diagnostics(result, diagnostics)
    except GmailHistorySyncError as error:
        if str(error) == "http_404":
            _recover_expired_cursor(store)
            result = {
                "status": "history_cursor_expired",
                "processed": processed,
                "accepted_new_count": accepted_new,
                "material_candidate_count": material_candidates,
                "priority_candidate_count": priority_candidates,
                "failed": failed + 1,
                "duplicate": duplicate,
                "duplicate_count": duplicate,
                "history_gap": True,
            }
            if suppressed:
                result["suppressed"] = suppressed
            _persist_sync_diagnostics(store, result, diagnostics, sync_started_at=sync_started_at, complete=True)
            return _with_candidate_diagnostics(result, diagnostics)
        result = {"status": str(error), "processed": processed, "accepted_new_count": accepted_new, "material_candidate_count": material_candidates, "priority_candidate_count": priority_candidates, "failed": failed + 1, "duplicate": duplicate, "duplicate_count": duplicate}
        if suppressed:
            result["suppressed"] = suppressed
        store.save_cursor(last_full_sync_at=datetime.now(UTC).isoformat())
        _persist_sync_diagnostics(store, result, diagnostics, sync_started_at=sync_started_at, complete=True)
        return _with_candidate_diagnostics(result, diagnostics)
    return _with_candidate_diagnostics(result, diagnostics)


async def sync_latest_financialjuice(
    config: GmailWatchConfig,
    store: EmailStore,
    ingress: GmailIngressService,
    *,
    client_factory: Callable[..., Any] = httpx.AsyncClient,
) -> dict[str, Any]:
    """Reprocess exactly the newest FinancialJuice mail without moving the cursor."""
    diagnostics = _empty_candidate_diagnostics()
    if config.missing or config.oauth_missing:
        return _manual_replay_result(store, {"status": "configuration_missing", "processed": 0, "accepted_new_count": 0, "material_candidate_count": 0, "failed": 0, "duplicate": 0, "duplicate_count": 0}, diagnostics)
    processed = accepted_new = material_candidates = failed = duplicate = 0
    body_summary: dict[str, Any] = {}
    try:
        async with client_factory(timeout=config.timeout_seconds, follow_redirects=True) as client:
            token = await _access_token(config, client)
            listing = await _get_json(
                client, MESSAGE_LIST_URL, token,
                {"q": LATEST_FINANCIALJUICE_QUERY, "maxResults": 1, "includeSpamTrash": "false"},
            )
            messages = listing.get("messages") if isinstance(listing, Mapping) else None
            message_id = ""
            if isinstance(messages, list) and messages and isinstance(messages[0], Mapping):
                message_id = str(messages[0].get("id") or "").strip()
            if not message_id:
                return _manual_replay_result(store, {"status": "no_financialjuice_message", "processed": 0, "accepted_new_count": 0, "material_candidate_count": 0, "failed": 0, "duplicate": 0, "duplicate_count": 0}, diagnostics)
            message = await _get_json(client, f"{MESSAGE_URL}/{message_id}", token, {"format": "full"})
            record = message_record(message)
            payload = message.get("payload") if isinstance(message.get("payload"), Mapping) else {}
            parts = _walk_text(payload)
            record["body"] = await _message_body(client, token, message_id, payload)
            result = ingress.accept_email(record)
            _merge_candidate_diagnostics(diagnostics, result.get("candidate_diagnostics"))
            processed = 1
            accepted_new = int(result.get("accepted") is True)
            material_candidates = int(result.get("material_candidate") is True)
            duplicate = int(result.get("status") == "duplicate")
            body_summary = _body_selection_summary(parts, record["body"])
            body_summary.update(_public_projection_summary(result))
            body_summary["sender_domain"] = _sender_domain(record.get("sender"))
    except GmailHistorySyncError as error:
        failed = 1
        return _manual_replay_result(store, {"status": str(error), "processed": processed, "accepted_new_count": accepted_new, "material_candidate_count": material_candidates, "failed": failed, "duplicate": duplicate, "duplicate_count": duplicate}, diagnostics)
    except (httpx.TimeoutException, httpx.HTTPError, ValueError, TypeError, KeyError) as error:
        failed = 1
        return _manual_replay_result(store, {"status": type(error).__name__.lower(), "processed": processed, "accepted_new_count": accepted_new, "material_candidate_count": material_candidates, "failed": failed, "duplicate": duplicate, "duplicate_count": duplicate}, diagnostics)
    return _manual_replay_result(store, {
        "status": "healthy", "processed": processed, "accepted_new_count": accepted_new,
        "material_candidate_count": material_candidates, "failed": failed, "duplicate": duplicate, "duplicate_count": duplicate,
        "latest_financialjuice_diagnostics": body_summary,
    }, diagnostics)


__all__ = ["GmailHistorySyncError", "message_record", "sync_gmail_history", "sync_latest_financialjuice"]
