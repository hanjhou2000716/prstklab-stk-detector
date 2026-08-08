"""Small, testable Telegram Bot API client."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from time import sleep, time

import requests


class TelegramError(RuntimeError):
    """Raised when Telegram rejects a notification."""


class TelegramTransientError(TelegramError):
    """Raised after retrying a temporary Telegram transport/API failure."""


SEND_ATTEMPTS = 3
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
FAILED_RECIPIENT_RETRIES = 1
MAX_FAILED_RECIPIENT_RETRIES = 3


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
    if len(text) > 30:
        raise ValueError(f"快報超過 30 字，目前為 {len(text)} 字：{text}")


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
    *, token: str, chat_id: str, text: str, dashboard_url: str
) -> TelegramResult:
    """Send a brief with one dashboard button through Telegram Bot API."""
    validate_brief(text)
    payload_to_send = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
        "reply_markup": {"inline_keyboard": [[mini_app_button(versioned_mini_app_url(dashboard_url))]]},
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
    *, token: str, chat_ids: tuple[str, ...], text: str, dashboard_url: str
) -> tuple[TelegramDelivery, ...]:
    """Send one identical brief to every reachable configured recipient.

    A recipient who has not started the Bot produces a local Telegram error.
    Temporary Telegram transport failures are retried, then recorded without
    interrupting the public-market refresh, Pages deployment, or delivery to
    the remaining recipients. Configuration failures still raise normally.
    """
    if not chat_ids:
        raise ValueError("至少需要一個 Telegram 收件人。")
    deliveries: list[TelegramDelivery] = []
    for chat_id in chat_ids:
        try:
            result = send_brief(token=token, chat_id=chat_id, text=text, dashboard_url=dashboard_url)
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
                )
            except TelegramError as exc:
                deliveries[index] = TelegramDelivery(chat_id=delivery.chat_id, error=str(exc))
                if isinstance(exc, TelegramTransientError):
                    next_pending.add(index)
            else:
                deliveries[index] = TelegramDelivery(chat_id=delivery.chat_id, result=result)
        pending = next_pending
    return tuple(deliveries)


def send_photo_brief(
    *, token: str, chat_id: str, caption: str, photo_path: str | Path,
    mini_app_url: str, alert_id: str, release_id: str, snapshot_id: str,
) -> PhotoDeliveryReceipt:
    """Send one caption-above-photo message with an alert-specific Mini App URL.

    The function is deliberately small and injectable via monkeypatching
    `requests.post` for CI. It never logs the token, chat ID, or API payload.
    """
    if not caption.strip() or len(caption) > 40:
        raise ValueError("photo caption must be 1-40 characters")
    path = Path(photo_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    if not mini_app_url.startswith("https://"):
        raise ValueError("Mini App URL must use HTTPS")
    separator = "&" if "?" in mini_app_url else "?"
    target = f"{mini_app_url}{separator}alert={alert_id}&release={release_id}&view=event"
    endpoint = f"https://api.telegram.org/bot{token}/sendPhoto"
    recipient_hash = hashlib.sha256(chat_id.encode("utf-8")).hexdigest()[:12]
    response = None
    last_error: Exception | None = None
    for attempt in range(SEND_ATTEMPTS):
        retry_after = None
        try:
            with path.open("rb") as photo:
                response = requests.post(
                    endpoint,
                    data={
                        "chat_id": chat_id,
                        "caption": caption,
                        "parse_mode": "HTML",
                        "show_caption_above_media": "true",
                        "reply_markup": json.dumps({"inline_keyboard": [[mini_app_button(target)]]}),
                    },
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
        )
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not response.ok or not payload.get("ok"):
        error_class = "rate_limit" if getattr(response, "status_code", 0) == 429 else "telegram_api"
        return PhotoDeliveryReceipt(alert_id, release_id, snapshot_id, recipient_hash, "failed", error_class=error_class)
    result = payload.get("result") or {}
    return PhotoDeliveryReceipt(alert_id, release_id, snapshot_id, recipient_hash, "delivered", message_id=result.get("message_id"))


def send_photo_briefs(
    *, token: str, chat_ids: tuple[str, ...], caption: str, photo_path: str | Path,
    mini_app_url: str, alert_id: str, release_id: str, snapshot_id: str,
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
            )
        except (TelegramError, OSError, requests.RequestException) as exc:
            receipt = PhotoDeliveryReceipt(
                alert_id, release_id, snapshot_id, recipient_hash, "failed",
                error_class=type(exc).__name__.lower(),
            )
        receipts.append(receipt)
    return tuple(receipts)
