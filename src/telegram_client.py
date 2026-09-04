"""Small, testable Telegram Bot API client."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from time import sleep, time
from urllib.parse import urlencode

import requests


class TelegramError(RuntimeError):
    """Raised when Telegram rejects a notification."""


class TelegramTransientError(TelegramError):
    """Raised after retrying a temporary Telegram transport/API failure."""


SEND_ATTEMPTS = 3
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
FAILED_RECIPIENT_RETRIES = 1
MAX_FAILED_RECIPIENT_RETRIES = 3
PUBLIC_TEXT_MAX_CHARS = 40
PRSTK_RISK_LEVELS = frozenset({"R0", "R1", "R2", "R3", "R4"})
_RISK_ICONS = {"R0": "🟢", "R1": "🟢", "R2": "🟡", "R3": "🟠", "R4": "🔴"}
_RISK_CATEGORIES = {"R0": "市場觀察", "R1": "市場觀察", "R2": "市場觀察", "R3": "市場風險", "R4": "重大風險"}
_GENERIC_PUBLIC_LABELS = frozenset({
    "市場觀察", "市場風險", "重大風險", "市場待核對", "市場資訊待核對",
    "資料待核對", "資訊待核對", "資訊待核對。", "快訊", "價格訊號", "重大事件", "重要事件",
})


def _failed_recipient_retry_count() -> int:
    """Return a bounded retry count for recipients that had transient errors.

    ``send_brief`` already performs its own transport/API retry cycle.  This
    second, recipient-scoped cycle is deliberately small: it prevents one
    Telegram edge reset from permanently losing a recipient while avoiding a
    long-running workflow or duplicate sends to recipients that already
    succeeded.  An invalid environment value falls back to the safe default.
    """
    raw = os.environ.get("TELEGRAM_FAILED_RECIPIENT_RETRIES", "").strip()
    if not raw:
        return FAILED_RECIPIENT_RETRIES
    try:
        return max(0, min(MAX_FAILED_RECIPIENT_RETRIES, int(raw)))
    except ValueError:
        return FAILED_RECIPIENT_RETRIES


@dataclass(frozen=True)
class TelegramResult:
    message_id: int


@dataclass(frozen=True)
class TelegramDelivery:
    """Outcome for one configured Telegram recipient."""

    chat_id: str
    result: TelegramResult | None = None
    error: str | None = None

    @property
    def delivered(self) -> bool:
        return self.result is not None


@dataclass(frozen=True)
class PhotoDeliveryReceipt:
    """Auditable result for one sendPhoto call without storing private content."""

    alert_id: str
    release_id: str
    snapshot_id: str
    chat_id_hash: str
    status: str
    message_id: int | None = None
    error_class: str | None = None
    # Kept internal to the process; only a short hash is safe to persist.
    telegram_file_id: str | None = None
    telegram_file_id_hash: str | None = None
    # Correlates the Telegram receipt with the exact source observation used
    # to produce the published alert.  Kept last with a default for backward
    # compatibility with existing positional test fixtures.
    observation_id: str = ""


@dataclass(frozen=True)
class TextDeliveryReceipt:
    """Auditable result for one non-Creator text delivery."""

    alert_id: str
    release_id: str
    snapshot_id: str
    chat_id_hash: str
    status: str
    message_id: int | None = None
    error_class: str | None = None
    observation_id: str = ""
    prstk_risk_level: str = "R2"


def canonical_prstk_risk_level(event: dict[str, object] | None) -> str:
    """Read the canonical R0–R4 risk field at the notification boundary.

    Production producers should always attach ``prstk_risk_level`` before a
    sender is called.  The small label mapping is retained for older event
    records so a missing canonical field is not silently turned into an
    arbitrary R2 when an unambiguous legacy label is available.
    """
    if not isinstance(event, dict):
        return "R2"
    nested = event.get("prstk_risk")
    candidates = [
        nested.get("prstk_risk_level") if isinstance(nested, dict) else None,
        event.get("prstk_risk_level"),
    ]
    for value in candidates:
        level = str(value or "").strip().upper()
        if level in PRSTK_RISK_LEVELS:
            return level
    legacy = str(event.get("risk_level") or event.get("importance") or "").strip().casefold()
    legacy_map = {
        "觀察": "R1", "持續觀察": "R1", "市場待核對": "R1", "normal": "R1",
        "警戒": "R3", "warning": "R3", "高波動": "R2", "波動擴大": "R2",
        "高風險": "R4", "high-risk": "R4", "high risk": "R4",
    }
    if legacy in legacy_map:
        return legacy_map[legacy]
    return "R2"


@dataclass(frozen=True)
class DeliverySummary:
    """Aggregate outcome without exposing recipient identifiers in logs."""

    delivered_count: int
    failed_count: int
    failed_recipient_hashes: tuple[str, ...]

    @property
    def any_delivered(self) -> bool:
        return self.delivered_count > 0


def summarize_deliveries(deliveries: tuple[TelegramDelivery, ...] | list[TelegramDelivery]) -> DeliverySummary:
    failed = [item for item in deliveries if not item.delivered]
    return DeliverySummary(
        delivered_count=len(deliveries) - len(failed),
        failed_count=len(failed),
        failed_recipient_hashes=tuple(
            hashlib.sha256(item.chat_id.encode("utf-8")).hexdigest()[:12] for item in failed
        ),
    )


def validate_brief(text: str) -> None:
    """Enforce the watch-friendly brief format before sending."""
    if not text.strip():
        raise ValueError("快報內容不可空白。")
    if len(text) > PUBLIC_TEXT_MAX_CHARS:
        raise ValueError(f"快報超過 {PUBLIC_TEXT_MAX_CHARS} 字，目前為 {len(text)} 字：{text}")


def _clean_public_fragment(value: object) -> str:
    """Remove transport/attribution noise before selecting a public clause."""
    source = " ".join(str(value or "").replace("\n", " ").split()).strip()
    source = re.sub(r"https?://\S+", "", source).strip(" ｜|,，:：")
    source = re.sub(
        r"^(?:translation|original headline|headline|ai commentary|possible impact|"
        r"possible linkage|why important|importance(?: score)?|事件|為何重要|可能連動|股市觀察)\s*[:：]\s*",
        "",
        source,
        flags=re.IGNORECASE,
    )
    source = re.sub(
        r"^(?:據|根據)\s*[《「\"']([^》」\"']+)[》」\"']\s*"
        r"(?:報導|指出|稱|消息稱)?\s*[,，:：]?\s*",
        "",
        source,
    )
    if re.match(r"^(?:據|根據)\s*[《「\"']", source) and not re.search(r"[》」\"']", source):
        return ""
    return source.strip(" ｜|,，:：")


def _semantic_excerpt(value: str, limit: int, *, allow_char_cut: bool = True) -> str:
    """Fit one fact without ellipses or an incomplete English word.

    A public alert is either a complete readable clause or no alert.  The
    ``allow_char_cut`` argument remains for compatibility with older callers,
    but character cutting is deliberately no longer permitted at this public
    boundary.
    """
    text = _clean_public_fragment(value)
    if limit <= 0 or not text or "…" in text or "..." in text:
        return ""
    if len(text) <= limit:
        return text
    clauses = [part.strip() for part in re.split(r"(?<=[。！？；.!?;])(?:\s+|$)", text) if part.strip()]
    for clause in clauses:
        # A period in U.S., Inc., etc. is not a complete sentence boundary.
        if re.search(r"(?:\b[A-Za-z]\.)+$", clause):
            continue
        if len(clause) <= limit:
            return clause
    words = text.split()
    if len(words) > 1:
        kept: list[str] = []
        for word in words:
            candidate = " ".join([*kept, word])
            if len(candidate) + 1 > limit:
                break
            kept.append(word)
        if kept:
            # A title without punctuation is treated as a compact sentence;
            # the terminal full stop makes the one-sentence contract explicit.
            return " ".join(kept) + "."
    return ""


def summarize_public_message(
    text: str,
    *,
    prstk_risk_level: str = "R2",
    limit: int = PUBLIC_TEXT_MAX_CHARS,
) -> str:
    """Create one deterministic, evidence-grounded public Telegram summary.

    Risk is deliberately an internal-only field.  The public contract keeps
    the colour cue but never exposes ``R0``-``R4``.  Existing risk tokens,
    colour icons, generic taxonomy labels and wrappers are normalized instead
    of being stacked by downstream senders.  Facts are selected at segment or
    sentence boundaries; raw source text is never blindly cut before cleanup.
    """
    if limit <= 0:
        return ""
    level = str(prstk_risk_level or "R2").upper()
    if level not in PRSTK_RISK_LEVELS:
        level = "R2"
    source = " ".join(str(text or "").split())
    # Preserve the vendor score while removing any existing severity token.
    fj_match = re.search(r"FJ\s*\d+(?:\.\d+)?\s*/\s*10", source, flags=re.IGNORECASE)
    # Remove all caller-provided icons and risk tokens before rebuilding the
    # canonical prefix. This guarantees ``R2｜...｜R2`` cannot leak through.
    source = re.sub(r"(?<![A-Za-z0-9])R[0-4](?![A-Za-z0-9])\s*[｜|:]?", "", source, flags=re.IGNORECASE)
    source = re.sub(r"^[🟢🟡🟠🔴⚪⚫🟣]\s*", "", source)
    source = re.sub(r"[🟢🟡🟠🔴⚪⚫🟣]?\s*FJ\s*\d+(?:\.\d+)?\s*/\s*10\s*[｜|:]?", "", source, flags=re.IGNORECASE)
    segments = []
    for part in re.split(r"[｜|]", source):
        cleaned = _clean_public_fragment(part)
        if (
            cleaned
            and cleaned not in _GENERIC_PUBLIC_LABELS
            and not re.search(r"\bundefined\b", cleaned, flags=re.IGNORECASE)
            and not re.match(r"^(?:https?://|www\.)", cleaned, flags=re.IGNORECASE)
            and "…" not in cleaned
            and "..." not in cleaned
        ):
            segments.append(cleaned)
    if fj_match:
        fj_score = re.sub(r"\s+", " ", fj_match.group(0)).strip()
        # FJ's vendor importance is evidence metadata, not a replacement for
        # the PRStK risk grade.  The risk remains in the receipt/audit only.
        head = f"🟣 {fj_score}｜"
        category = ""
    else:
        head = f"{_RISK_ICONS[level]} "
        category = ""
    body_segments = ([category] if category and (not segments or segments[0] != category) else []) + segments
    if not body_segments:
        # FJ metadata without an event fact is suppression-worthy.  Other
        # legacy callers retain a neutral, bounded fallback.
        return "" if fj_match else f"{head}資訊待核對。"[:limit]

    # Public text has one body sentence.  Prefer the first event fact and add
    # a second fact only when it can be joined as a complete clause; never
    # concatenate fields with another visible separator.
    first = _semantic_excerpt(body_segments[0], limit - len(head), allow_char_cut=False)
    if not first:
        return ""
    body = first
    if len(body_segments) > 1:
        second = _semantic_excerpt(body_segments[1], limit - len(head) - len(body) - 1, allow_char_cut=False)
        if second:
            left = body.rstrip("。！？；.!?;，,")
            right = second.lstrip("。！？；.!?;，,")
            joined = f"{left}，{right}"
            if len(head + joined) <= limit:
                body = joined
    if len(head + body) > limit:
        body = _semantic_excerpt(body, limit - len(head), allow_char_cut=False)
    if not body or "…" in body or "..." in body:
        return ""
    return head + body


def is_valid_public_summary(text: str, *, source: str = "") -> bool:
    """Return whether text satisfies the public one-sentence contract.

    This validator is intentionally stricter than ``validate_brief``.  The
    latter is a transport boundary and accepts legacy test/operational text;
    this function is the content gate used before a release or notification
    exposes a source event to users.
    """
    value = " ".join(str(text or "").split()).strip()
    if not value or len(value) > PUBLIC_TEXT_MAX_CHARS:
        return False
    if any(marker in value for marker in ("…", "...")):
        return False
    if re.search(r"\bundefined\b", value, flags=re.IGNORECASE) or re.search(r"https?://|www\.", value, flags=re.IGNORECASE):
        return False
    if any(label.casefold() == value.casefold() for label in _GENERIC_PUBLIC_LABELS):
        return False
    if source.casefold() == "financialjuice":
        match = re.match(r"^🟣\s*FJ\s*\d+(?:\.\d+)?\s*/\s*10｜(.+)$", value, flags=re.IGNORECASE)
        if not match or value.count("｜") != 1:
            return False
        body = match.group(1).strip()
        if not body or body.casefold() in {label.casefold() for label in _GENERIC_PUBLIC_LABELS}:
            return False
        if re.fullmatch(r"[🟢🟡🟠🔴⚪⚫🟣\s。！？!?，,、:：|｜]*", body):
            return False
        if body.endswith(("：", ":", "|", "｜")):
            return False
        return True
    body = re.sub(r"^[🟢🟡🟠🔴⚪⚫🟣]\s*", "", value).strip()
    return bool(body) and body.casefold() not in {label.casefold() for label in _GENERIC_PUBLIC_LABELS}


def canonical_short_message(text: str, *, prstk_risk_level: str = "R2") -> str:
    """Backward-compatible entry point for the shared public summarizer."""
    return summarize_public_message(text, prstk_risk_level=prstk_risk_level)


def format_text_brief(text: str, *, prstk_risk_level: str = "R2") -> str:
    """Backward-compatible bounded formatter with the public display policy."""
    level = str(prstk_risk_level or "R2").upper()
    if level not in PRSTK_RISK_LEVELS:
        level = "R2"
    return canonical_short_message(text, prstk_risk_level=level)


def sanitize_public_photo_caption(caption: str) -> str:
    """Remove internal R0-R4 tokens while preserving public caption cues."""
    source = " ".join(str(caption or "").split())
    source = re.sub(r"(?<![A-Za-z0-9])R[0-4](?![A-Za-z0-9])\s*[｜|:]?", "", source, flags=re.IGNORECASE)
    source = re.sub(r"[｜|]\s*([｜|])+", "｜", source)
    source = re.sub(r"^[｜|]\s*|\s*[｜|]$", "", source).strip()
    return source or "市場資訊待核對"


def mini_app_button(mini_app_url: str) -> dict[str, object]:
    """Build an Inline Keyboard button that opens inside Telegram."""
    if not mini_app_url.startswith("https://"):
        raise ValueError("Mini App 網址必須使用 HTTPS。")
    return {
        "text": "📡 開啟稜量速報系統",
        "web_app": {"url": mini_app_url},
    }


def versioned_mini_app_url(mini_app_url: str) -> str:
    """Give each sent Telegram button a unique URL to bypass WebView cache."""
    if not mini_app_url.startswith("https://"):
        raise ValueError("Mini App 網址必須使用 HTTPS。")
    separator = "&" if "?" in mini_app_url else "?"
    return f"{mini_app_url}{separator}v={int(time() * 1000)}"


def alert_mini_app_url(
    mini_app_url: str, *, alert_id: str, release_id: str, snapshot_id: str,
    observation_id: str = "", view: str = "event"
) -> str:
    """Build a cache-busting Mini App URL that targets one published artifact."""
    if not mini_app_url.startswith("https://"):
        raise ValueError("Mini App URL must use HTTPS")
    separator = "&" if "?" in mini_app_url else "?"
    query_values = {
        "alert": alert_id,
        "release": release_id,
        "snapshot": snapshot_id,
        "view": view,
    }
    if observation_id:
        query_values["observation"] = observation_id
    query = urlencode(query_values)
    return f"{mini_app_url}{separator}{query}"


def mini_app_menu_button(mini_app_url: str) -> dict[str, object]:
    """Build the persistent Telegram chat-menu entry for this Mini App."""
    if not mini_app_url.startswith("https://"):
        raise ValueError("Mini App 網址必須使用 HTTPS。")
    return {
        "type": "web_app",
        "text": "稜量系統",
        "web_app": {"url": mini_app_url},
    }


def configure_mini_app_menu(*, token: str, chat_id: str | None = None, mini_app_url: str) -> None:
    """Set the global or one private chat's persistent Mini App menu button."""
    body: dict[str, object] = {"menu_button": mini_app_menu_button(mini_app_url)}
    if chat_id:
        body["chat_id"] = chat_id
    response = requests.post(
        f"https://api.telegram.org/bot{token}/setChatMenuButton",
        json=body,
        timeout=20,
    )
    try:
        payload = response.json()
    except ValueError as exc:
        raise TelegramError("Telegram 回傳了無法辨識的內容。") from exc

    if not response.ok or not payload.get("ok"):
        raise TelegramError(payload.get("description", "Mini App 選單設定失敗。"))


def _recipient_unavailable(error: TelegramError) -> bool:
    """Recognise recipient-only failures without hiding a broken Bot configuration."""
    description = str(error).lower()
    return any(
        phrase in description
        for phrase in ("chat not found", "bot was blocked by the user", "user is deactivated")
    )


def classify_telegram_error(error: BaseException) -> str:
    """Reduce a transport/API error to a safe operational category.

    Telegram descriptions can contain recipient-specific details.  Delivery
    receipts and workflow summaries therefore keep only a stable category.
    """
    if isinstance(error, TelegramTransientError) or isinstance(error, (OSError, requests.RequestException)):
        return "temporary_transport"
    if isinstance(error, TelegramError) and _recipient_unavailable(error):
        return "recipient_unavailable"
    description = str(error).casefold()
    if "429" in description or "rate limit" in description or "too many requests" in description:
        return "rate_limited"
    return "telegram_api"


def configure_mini_app_menus(*, token: str, chat_ids: tuple[str, ...], mini_app_url: str) -> tuple[TelegramDelivery, ...]:
    """Configure every reachable private-chat Mini App entry.

    Telegram requires a person to press Start before a Bot can configure that
    private chat. One unavailable recipient must not block every other user.
    """
    # Set Telegram's default menu first, so new users see the icon after they
    # press Start. Per-chat calls below preserve compatibility with existing
    # users who previously received an override.
    configure_mini_app_menu(token=token, mini_app_url=mini_app_url)
    deliveries: list[TelegramDelivery] = []
    for chat_id in chat_ids:
        try:
            configure_mini_app_menu(token=token, chat_id=chat_id, mini_app_url=mini_app_url)
        except TelegramError as exc:
            if not _recipient_unavailable(exc):
                raise
            deliveries.append(TelegramDelivery(chat_id=chat_id, error=str(exc)))
        else:
            deliveries.append(TelegramDelivery(chat_id=chat_id, result=TelegramResult(message_id=0)))
    return tuple(deliveries)


def send_brief(
    *, token: str, chat_id: str, text: str, dashboard_url: str,
    target_url: str | None = None,
) -> TelegramResult:
    """Send a brief with one dashboard button through Telegram Bot API."""
    validate_brief(text)
    if not is_valid_public_summary(text):
        raise ValueError("公開訊息內容不完整，已停止發送。")
    payload_to_send = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
        "reply_markup": {"inline_keyboard": [[mini_app_button(versioned_mini_app_url(target_url or dashboard_url))]]},
    }
    endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
    response = None
    last_error: Exception | None = None

    for attempt in range(SEND_ATTEMPTS):
        retry_after = None
        try:
            response = requests.post(endpoint, json=payload_to_send, timeout=20)
        except requests.RequestException as exc:
            last_error = exc
        else:
            if getattr(response, "status_code", 200) not in RETRYABLE_STATUS_CODES:
                break
            retry_after = None
            if getattr(response, "status_code", 200) == 429:
                try:
                    retry_after = int((response.json() or {}).get("parameters", {}).get("retry_after", 0))
                except (TypeError, ValueError, AttributeError):
                    retry_after = None
            last_error = TelegramTransientError(f"HTTP {response.status_code}")

        if attempt < SEND_ATTEMPTS - 1:
            # Short exponential backoff covers GitHub Runner / Telegram edge
            # resets without delaying a watch-sized alert for long.
            # Telegram's Retry-After is authoritative for rate limits.  Bound
            # it so one stale response cannot hold a GitHub runner forever.
            sleep(min(60, max(1, retry_after)) if retry_after else 2**attempt)

    if response is None or getattr(response, "status_code", 200) in RETRYABLE_STATUS_CODES:
        detail = str(last_error or "temporary Telegram delivery failure")
        raise TelegramTransientError(f"Telegram temporary delivery failure: {detail}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise TelegramError("Telegram 回傳了無法辨識的內容。") from exc

    if not response.ok or not payload.get("ok"):
        raise TelegramError(payload.get("description", "Telegram 發送失敗。"))

    return TelegramResult(message_id=payload["result"]["message_id"])


def send_briefs(
    *, token: str, chat_ids: tuple[str, ...], text: str, dashboard_url: str,
    target_url: str | None = None, prstk_risk_level: str = "R2",
) -> tuple[TelegramDelivery, ...]:
    """Send one identical brief to every reachable configured recipient.

    A recipient who has not started the Bot produces a local Telegram error.
    Temporary Telegram transport failures are retried, then recorded without
    interrupting the public-market refresh, Pages deployment, or delivery to
    the remaining recipients. Configuration failures still raise normally.
    """
    if not chat_ids:
        raise ValueError("至少需要一個 Telegram 收件人。")
    text = canonical_short_message(text, prstk_risk_level=prstk_risk_level)
    if not is_valid_public_summary(text):
        raise ValueError("公開訊息內容不完整，已停止發送。")
    deliveries: list[TelegramDelivery] = []
    for chat_id in chat_ids:
        try:
            result = send_brief(token=token, chat_id=chat_id, text=text, dashboard_url=dashboard_url, target_url=target_url)
        except TelegramError as exc:
            if not (_recipient_unavailable(exc) or isinstance(exc, TelegramTransientError)):
                raise
            deliveries.append(TelegramDelivery(chat_id=chat_id, error=str(exc)))
        else:
            deliveries.append(TelegramDelivery(chat_id=chat_id, result=result))
    # A transient outage affecting only some recipients must not cause a
    # second send to everyone. Retry only the failed recipients, with a
    # bounded number of rounds configurable for a deployment environment.
    pending = {
        index
        for index, delivery in enumerate(deliveries)
        if not delivery.delivered and "temporary delivery failure" in (delivery.error or "")
    }
    for _ in range(_failed_recipient_retry_count()):
        if not pending:
            break
        next_pending: set[int] = set()
        for index in pending:
            delivery = deliveries[index]
            try:
                result = send_brief(
                    token=token,
                    chat_id=delivery.chat_id,
                    text=text,
                    dashboard_url=dashboard_url,
                    target_url=target_url,
                )
            except TelegramError as exc:
                deliveries[index] = TelegramDelivery(chat_id=delivery.chat_id, error=str(exc))
                if isinstance(exc, TelegramTransientError):
                    next_pending.add(index)
            else:
                deliveries[index] = TelegramDelivery(chat_id=delivery.chat_id, result=result)
        pending = next_pending
    return tuple(deliveries)


def send_text_briefs_audited(
    *, token: str, chat_ids: tuple[str, ...], text: str, dashboard_url: str,
    alert_id: str, release_id: str, snapshot_id: str,
    observation_id: str = "", target_url: str | None = None,
    prstk_risk_level: str = "R2",
) -> tuple[TextDeliveryReceipt, ...]:
    """Send one text-only Mini App message per recipient with bounded receipts."""
    if not chat_ids:
        raise ValueError("Telegram recipient list is empty")
    if prstk_risk_level not in PRSTK_RISK_LEVELS:
        raise ValueError("PRStK risk level must be one of R0-R4")
    text = canonical_short_message(text, prstk_risk_level=prstk_risk_level)
    if not is_valid_public_summary(text):
        raise ValueError("公開訊息內容不完整，已停止發送。")
    receipts: list[TextDeliveryReceipt] = []
    for chat_id in chat_ids:
        recipient_hash = hashlib.sha256(chat_id.encode("utf-8")).hexdigest()[:12]
        try:
            result = send_brief(
                token=token, chat_id=chat_id, text=text,
                dashboard_url=dashboard_url, target_url=target_url,
            )
        except (TelegramError, OSError, requests.RequestException) as exc:
            receipts.append(TextDeliveryReceipt(
                alert_id, release_id, snapshot_id, recipient_hash, "failed",
                error_class=classify_telegram_error(exc), observation_id=observation_id,
                prstk_risk_level=prstk_risk_level,
            ))
        else:
            receipts.append(TextDeliveryReceipt(
                alert_id, release_id, snapshot_id, recipient_hash, "delivered",
                message_id=result.message_id, observation_id=observation_id,
                prstk_risk_level=prstk_risk_level,
            ))
    return tuple(receipts)


def send_photo_brief(
    *, token: str, chat_id: str, caption: str, photo_path: str | Path,
    mini_app_url: str, alert_id: str, release_id: str, snapshot_id: str,
    telegram_file_id: str | None = None,
    observation_id: str = "",
) -> PhotoDeliveryReceipt:
    """Send one caption-above-photo message with an alert-specific Mini App URL.

    The function is deliberately small and injectable via monkeypatching
    `requests.post` for CI. It never logs the token, chat ID, or API payload.
    """
    if not caption.strip():
        raise ValueError("photo caption must be 1-40 characters")
    caption = sanitize_public_photo_caption(caption)
    if len(caption) > 40:
        raise ValueError("photo caption must be 1-40 characters")
    path = Path(photo_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    if not mini_app_url.startswith("https://"):
        raise ValueError("Mini App URL must use HTTPS")
    target = alert_mini_app_url(
        mini_app_url,
        alert_id=alert_id,
        release_id=release_id,
        snapshot_id=snapshot_id,
        observation_id=observation_id,
    )
    endpoint = f"https://api.telegram.org/bot{token}/sendPhoto"
    recipient_hash = hashlib.sha256(chat_id.encode("utf-8")).hexdigest()[:12]
    response = None
    last_error: Exception | None = None
    for attempt in range(SEND_ATTEMPTS):
        retry_after = None
        try:
            payload = {
                "chat_id": chat_id,
                "caption": caption,
                "parse_mode": "HTML",
                "show_caption_above_media": "true",
                "reply_markup": json.dumps({"inline_keyboard": [[mini_app_button(target)]]}),
            }
            if telegram_file_id:
                response = requests.post(
                    endpoint,
                    data={**payload, "photo": telegram_file_id},
                    timeout=30,
                )
            else:
                with path.open("rb") as photo:
                    response = requests.post(
                        endpoint,
                        data=payload,
                        files={"photo": photo},
                        timeout=30,
                    )
        except requests.RequestException as exc:
            last_error = exc
        else:
            if getattr(response, "status_code", 200) not in RETRYABLE_STATUS_CODES:
                break
            last_error = TelegramTransientError(f"HTTP {response.status_code}")
            if getattr(response, "status_code", 0) == 429:
                try:
                    retry_after = int((response.json() or {}).get("parameters", {}).get("retry_after", 0))
                except (TypeError, ValueError, AttributeError):
                    retry_after = None
        if attempt < SEND_ATTEMPTS - 1:
            sleep(min(60, max(1, retry_after)) if retry_after else 2**attempt)

    if response is None or getattr(response, "status_code", 200) in RETRYABLE_STATUS_CODES:
        return PhotoDeliveryReceipt(
            alert_id, release_id, snapshot_id, recipient_hash, "failed",
            error_class="temporary_transport" if last_error else "temporary_api",
            observation_id=observation_id,
        )
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not response.ok or not payload.get("ok"):
        error_class = "rate_limit" if getattr(response, "status_code", 0) == 429 else "telegram_api"
        return PhotoDeliveryReceipt(
            alert_id, release_id, snapshot_id, recipient_hash, "failed",
            error_class=error_class, observation_id=observation_id,
        )
    raw_result = payload.get("result")
    result: dict[str, object] = raw_result if isinstance(raw_result, dict) else {}
    file_id = None
    if not telegram_file_id:
        photos = result.get("photo")
        if isinstance(photos, list) and photos:
            last_photo = photos[-1]
            if isinstance(last_photo, dict):
                candidate = last_photo.get("file_id")
                if isinstance(candidate, str) and candidate:
                    file_id = candidate
    file_id = telegram_file_id or file_id
    raw_message_id = result.get("message_id")
    message_id = raw_message_id if isinstance(raw_message_id, int) else None
    return PhotoDeliveryReceipt(
        alert_id, release_id, snapshot_id, recipient_hash, "delivered",
        message_id=message_id,
        telegram_file_id=file_id,
        telegram_file_id_hash=hashlib.sha256(file_id.encode("utf-8")).hexdigest()[:12] if file_id else None,
        observation_id=observation_id,
    )


def summarize_photo_deliveries(deliveries: tuple[PhotoDeliveryReceipt, ...] | list[PhotoDeliveryReceipt]) -> DeliverySummary:
    """Aggregate sendPhoto receipts without exposing chat IDs or file IDs."""
    failed = [item for item in deliveries if item.status != "delivered"]
    return DeliverySummary(
        delivered_count=len(deliveries) - len(failed),
        failed_count=len(failed),
        failed_recipient_hashes=tuple(item.chat_id_hash for item in failed),
    )


def send_photo_briefs(
    *, token: str, chat_ids: tuple[str, ...], caption: str, photo_path: str | Path,
    mini_app_url: str, alert_id: str, release_id: str, snapshot_id: str,
    observation_id: str = "",
) -> tuple[PhotoDeliveryReceipt, ...]:
    """Deliver one identical photo message per recipient without fail-fast.

    Each recipient receives an independent receipt.  A blocked chat, a 429 or
    a transient transport failure is recorded and cannot prevent delivery to
    the remaining configured chats.  The function never logs identifiers or
    Telegram response bodies.
    """
    if not chat_ids:
        raise ValueError("Telegram recipient list is empty")
    receipts: list[PhotoDeliveryReceipt] = []
    shared_file_id: str | None = None
    for chat_id in chat_ids:
        recipient_hash = hashlib.sha256(chat_id.encode("utf-8")).hexdigest()[:12]
        try:
            receipt = send_photo_brief(
                token=token,
                chat_id=chat_id,
                caption=caption,
                photo_path=photo_path,
                mini_app_url=mini_app_url,
                alert_id=alert_id,
                release_id=release_id,
                snapshot_id=snapshot_id,
                telegram_file_id=shared_file_id,
                observation_id=observation_id,
            )
        except (TelegramError, OSError, requests.RequestException) as exc:
            receipt = PhotoDeliveryReceipt(
                alert_id, release_id, snapshot_id, recipient_hash, "failed",
                error_class=type(exc).__name__.lower(),
                observation_id=observation_id,
            )
        receipts.append(receipt)
        if receipt.status == "delivered" and receipt.telegram_file_id:
            shared_file_id = receipt.telegram_file_id
    return tuple(receipts)
