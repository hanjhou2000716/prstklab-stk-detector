"""Legacy smoke command now performs a scoped text-only delivery check.

The module name is retained for existing workflow links, but no non-Creator
production path may render or upload a Telegram photo.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from src.config import get_settings
from src.telegram_client import send_text_briefs_audited

CAPTION = "🟡 PRStK 受控驗證｜資料待核對"
ALERT_ID = "text-smoke-test"
RELEASE_ID = "text-smoke-test"
SNAPSHOT_ID = "text-smoke-test"


def run() -> int:
    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_ids:
        raise RuntimeError("Telegram configuration is incomplete for text smoke test")
    receipts = send_text_briefs_audited(
        token=settings.telegram_bot_token, chat_ids=settings.telegram_chat_ids,
        text=CAPTION, dashboard_url=settings.dashboard_url, alert_id=ALERT_ID,
        release_id=RELEASE_ID, snapshot_id=SNAPSHOT_ID,
        observation_id=f"{ALERT_ID}-{uuid.uuid4().hex[:12]}", prstk_risk_level="R2",
    )
    delivered = sum(receipt.status == "delivered" for receipt in receipts)
    failed = len(receipts) - delivered
    trace_id = f"text-smoke-{uuid.uuid4().hex[:16]}"
    output_path = Path(os.environ["GITHUB_OUTPUT"]) if os.environ.get("GITHUB_OUTPUT") else None
    if output_path:
        output_path.open("a", encoding="utf-8").write(
            "\n".join((
                "sent=true", f"trace_id={trace_id}", f"alert_id={ALERT_ID}",
                f"release_id={RELEASE_ID}", f"snapshot_id={SNAPSHOT_ID}",
                "delivery_mode=text", f"delivery_status={'delivered' if failed == 0 else 'partial'}",
                f"delivered_count={delivered}", f"failed_count={failed}",
                "renderer_error_type=not_applicable",
            )) + "\n"
        )
    if failed:
        raise RuntimeError("text smoke test did not deliver to every scoped recipient")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
