"""First-stage notification command for PRStK."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

from src.config import get_settings
from src.telegram_client import TelegramError, send_briefs, validate_brief

DEFAULT_TEST_MESSAGE = "測試｜PRStK 通知系統已啟動🟰"


def configure_console() -> None:
    """Prevent a legacy Windows terminal encoding from crashing on emoji."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PRStK Telegram 快報工具")
    parser.add_argument(
        "--message", default=DEFAULT_TEST_MESSAGE, help="60 字內的快報內容"
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
        print("缺少 TELEGRAM_BOT_TOKEN 或有效 Telegram 訂閱，未發送。")
        return 2

    notification_key = os.environ.get("TELEGRAM_NOTIFICATION_KEY", "").strip()
    if not notification_key:
        print("缺少持久通知識別，已停止發送。")
        return 2

    try:
        results = send_briefs(
            token=settings.telegram_bot_token or "",
            chat_ids=settings.telegram_chat_ids,
            text=args.message,
            dashboard_url=settings.dashboard_url,
            notification_key=notification_key,
        )
    except TelegramError as exc:
        print(f"Telegram 發送失敗：{exc}")
        return 1

    delivered = sum(result.delivered for result in results)
    failed = len(results) - delivered
    trace_id = f"manual-notify-{hashlib.sha256(notification_key.encode('utf-8')).hexdigest()[:32]}"
    alert_id = trace_id
    values = {
        "sent": "true",
        "trace_id": trace_id,
        "alert_id": alert_id,
        "release_id": "manual-notify",
        "snapshot_id": "manual-notify",
        "delivery_mode": "text",
        "delivery_status": "delivered" if failed == 0 else "partial" if delivered else "failed",
        "delivered_count": str(delivered),
        "failed_count": str(failed),
        "failed_recipient_hashes": ",".join(
            hashlib.sha256(result.chat_id.encode("utf-8")).hexdigest()[:12]
            for result in results if not result.delivered
        ),
        "notification_keys": hashlib.sha256(notification_key.encode("utf-8")).hexdigest(),
    }
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as handle:
            for key, value in values.items():
                escaped = value.replace("%", "%25").replace("\n", "%0A").replace("\r", "%0D")
                handle.write(f"{key}={escaped}\n")
    print(f"Telegram delivery recorded for {delivered}/{len(results)} recipients.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
