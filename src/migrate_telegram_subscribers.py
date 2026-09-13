"""One-time, idempotent migration of the legacy Telegram recipient secret."""

from __future__ import annotations

import os

from src.config import parse_chat_ids
from src.telegram_subscriptions import TelegramSubscriptionError, migrate_legacy_chat_ids


def main() -> int:
    try:
        migrated = migrate_legacy_chat_ids(
            parse_chat_ids(os.getenv("TELEGRAM_CHAT_IDS")),
            editor_chat_id=os.getenv("TELEGRAM_EDITOR_CHAT_ID", "8869592162").strip() or "8869592162",
        )
    except TelegramSubscriptionError as exc:
        print(f"Telegram 訂閱遷移失敗：{exc}")
        return 1
    print(f"Telegram 訂閱遷移完成；新增或核對 {migrated} 筆，不重新啟用既有退訂。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
