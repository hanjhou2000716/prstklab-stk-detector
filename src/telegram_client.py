"""Small, testable Telegram Bot API client."""

from __future__ import annotations

from dataclasses import dataclass
from time import sleep, time

import requests


class TelegramError(RuntimeError):
    """Raised when Telegram rejects a notification."""


class TelegramTransientError(TelegramError):
    """Raised after retrying a temporary Telegram transport/API failure."""


SEND_ATTEMPTS = 3
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


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


def configure_mini_app_menu(*, token: str, chat_id: str, mini_app_url: str) -> None:
    """Set this private chat's persistent Telegram Mini App menu button."""
    response = requests.post(
        f"https://api.telegram.org/bot{token}/setChatMenuButton",
        json={"chat_id": chat_id, "menu_button": mini_app_menu_button(mini_app_url)},
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
        try:
            response = requests.post(endpoint, json=payload_to_send, timeout=20)
        except requests.RequestException as exc:
            last_error = exc
        else:
            if getattr(response, "status_code", 200) not in RETRYABLE_STATUS_CODES:
                break
            last_error = TelegramTransientError(f"HTTP {response.status_code}")

        if attempt < SEND_ATTEMPTS - 1:
            # Short exponential backoff covers GitHub Runner / Telegram edge
            # resets without delaying a watch-sized alert for long.
            sleep(2**attempt)

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
    return tuple(deliveries)
