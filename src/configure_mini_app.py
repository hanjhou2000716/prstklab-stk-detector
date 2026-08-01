"""Configure the recipient chat's persistent PRStK Telegram Mini App entry."""

from __future__ import annotations

import sys

from src.config import get_settings
from src.telegram_client import TelegramError, configure_mini_app_menus


def main() -> int:
    settings = get_settings()
    if not settings.telegram_ready:
        print("缺少 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_IDS，未設定選單。")
        return 2
    try:
        configure_mini_app_menus(
            token=settings.telegram_bot_token or "",
            chat_ids=settings.telegram_chat_ids,
            mini_app_url=settings.dashboard_url,
        )
    except (TelegramError, ValueError) as exc:
        print(f"Mini App 選單設定失敗：{exc}")
        return 1
    print("Mini App 選單設定成功。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
