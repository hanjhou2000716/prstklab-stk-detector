"""Small, testable Telegram Bot API client."""

from __future__ import annotations

from dataclasses import dataclass

import requests


class TelegramError(RuntimeError):
    """Raised when Telegram rejects a notification."""


@dataclass(frozen=True)
class TelegramResult:
    message_id: int


def validate_brief(text: str) -> None:
    """Enforce the watch-friendly brief format before sending."""
    if not text.strip():
        raise ValueError("快報內容不可空白。")
    if len(text) > 30:
        raise ValueError(f"快報超過 30 字，目前為 {len(text)} 字：{text}")


def send_brief(
    *, token: str, chat_id: str, text: str, dashboard_url: str
) -> TelegramResult:
    """Send a brief with one dashboard button through Telegram Bot API."""
    validate_brief(text)
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
            "reply_markup": {
                "inline_keyboard": [
                    [{"text": "🔘 查看完整儀表板", "url": dashboard_url}]
                ]
            },
        },
        timeout=20,
    )
    try:
        payload = response.json()
    except ValueError as exc:
        raise TelegramError("Telegram 回傳了無法辨識的內容。") from exc

    if not response.ok or not payload.get("ok"):
        raise TelegramError(payload.get("description", "Telegram 發送失敗。"))

    return TelegramResult(message_id=payload["result"]["message_id"])

