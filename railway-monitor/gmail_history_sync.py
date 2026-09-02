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
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from email_store import EmailStore
from gmail_watch import GmailWatchConfig

from gmail_ingress import GmailIngressService

TOKEN_URL = "https://oauth2.googleapis.com/token"
HISTORY_URL = "https://gmail.googleapis.com/gmail/v1/users/me/history"
MESSAGE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
DEFAULT_MAX_MESSAGES = 50
MAX_PAGE_SIZE = 100


class GmailHistorySyncError(RuntimeError):
    """Bounded, non-sensitive synchronisation failure."""


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
    if config.missing:
        return {"status": "configuration_missing", "processed": 0, "failed": 0}
    if config.oauth_missing:
        return {"status": "configuration_missing", "processed": 0, "failed": 0}
    cursor = store.cursor()
    history_id = str(cursor.get("last_history_id") or "").strip()
    if not history_id:
        store.save_cursor(last_full_sync_at=datetime.now(UTC).isoformat())
        return {"status": "no_history_cursor", "processed": 0, "failed": 0}

    bounded = max(1, min(MAX_PAGE_SIZE, int(max_messages)))
    processed = failed = duplicate = 0
    failure_types: dict[str, int] = {}
    try:
        async with client_factory(timeout=config.timeout_seconds, follow_redirects=True) as client:
            token = await _access_token(config, client)
            history = await _get_json(
                client,
                HISTORY_URL,
                token,
                {"startHistoryId": history_id, "historyTypes": "messageAdded", "maxResults": bounded},
            )
            message_ids: list[str] = []
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
            for message_id in message_ids:
                try:
                    message = await _get_json(client, f"{MESSAGE_URL}/{message_id}", token, {"format": "full"})
                    record = message_record(message)
                    payload = message.get("payload") if isinstance(message.get("payload"), Mapping) else {}
                    record["body"] = await _message_body(client, token, message_id, payload)
                    result = ingress.accept_email(record)
                    processed += 1
                    if result.get("status") == "duplicate":
                        duplicate += 1
                except (GmailHistorySyncError, ValueError, TypeError, KeyError) as error:
                    failed += 1
                    failure_type = type(error).__name__
                    failure_types[failure_type] = failure_types.get(failure_type, 0) + 1
            latest_history = str(history.get("historyId") or "").strip()
            store.save_cursor(
                last_history_id=latest_history or history_id,
                last_full_sync_at=datetime.now(UTC).isoformat(),
            )
    except (httpx.TimeoutException, httpx.HTTPError) as error:
        store.save_cursor(last_full_sync_at=datetime.now(UTC).isoformat())
        return {"status": type(error).__name__.lower(), "processed": processed, "failed": failed + 1, "duplicate": duplicate}
    except GmailHistorySyncError as error:
        if str(error) == "http_404":
            _recover_expired_cursor(store)
            return {
                "status": "history_cursor_expired",
                "processed": processed,
                "failed": failed + 1,
                "duplicate": duplicate,
                "history_gap": True,
            }
        store.save_cursor(last_full_sync_at=datetime.now(UTC).isoformat())
        return {"status": str(error), "processed": processed, "failed": failed + 1, "duplicate": duplicate}
    result = {"status": "healthy" if failed == 0 else "degraded", "processed": processed, "failed": failed, "duplicate": duplicate}
    if failure_types:
        result["failure_types"] = dict(sorted(failure_types.items()))
    return result


__all__ = ["GmailHistorySyncError", "message_record", "sync_gmail_history"]
