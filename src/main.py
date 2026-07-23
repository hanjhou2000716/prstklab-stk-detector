"""First-stage notification command for PRStK."""

from __future__ import annotations

import argparse
import sys

from src.config import get_settings
from src.telegram_client import TelegramError, send_brief, validate_brief


DEFAULT_TEST_MESSAGE = "測試｜PRStK 通知系統已啟動🟰"


def configure_console() -> None:
    """Prevent a legacy Windows terminal encoding from crashing on emoji."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PRStK Telegram 快報工具")
    parser.add_argument(
        "--message", default=DEFAULT_TEST_MESSAGE, help="30 字內的快報內容"
    )
    parser.add_argument(
        "--send", action="store_true", help="實際發送至 Telegram；預設只模擬"
    )
    return parser.parse_args()


def main() -> int:
    configure_console()
    args = parse_args()
    try:
        validate_brief(args.message)
    except ValueError as exc:
        print(f"驗證失敗：{exc}")
        return 2

    settings = get_settings()
    print(f"快報（{len(args.message)} 字）：{args.message}")
    print(f"儀表板按鈕：{settings.dashboard_url}")

    if not args.send:
        print("模擬成功：未發送 Telegram。加入 --send 才會實際推播。")
        return 0

    if not settings.telegram_ready:
        print("缺少 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID，未發送。")
        return 2

    try:
        result = send_brief(
            token=settings.telegram_bot_token or "",
            chat_id=settings.telegram_chat_id or "",
            text=args.message,
            dashboard_url=settings.dashboard_url,
        )
    except TelegramError as exc:
        print(f"Telegram 發送失敗：{exc}")
        return 1

    print(f"Telegram 發送成功，訊息 ID：{result.message_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
