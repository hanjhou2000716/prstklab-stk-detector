"""Send one deterministic alert-card smoke test to the configured recipient.

This command is intentionally separate from the scheduled broadcast.  CI can
scope ``TELEGRAM_CHAT_IDS`` to one explicitly requested chat for a real
``sendPhoto`` check without risking a broadcast to the production list.
"""

from __future__ import annotations

import struct
import tempfile
from pathlib import Path

from src.alert_card_renderer import HEIGHT, WIDTH, render_alert_card
from src.config import get_settings
from src.telegram_client import send_photo_briefs

CAPTION = "🧪 PRStK 圖卡測試｜觀察"
ALERT_ID = "photo-smoke-test"
RELEASE_ID = "photo-smoke-test"
SNAPSHOT_ID = "photo-smoke-test"


def _png_dimensions(path: Path) -> tuple[int, int]:
    """Read dimensions from a PNG IHDR without requiring Pillow."""
    header = path.read_bytes()
    if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ValueError("renderer did not produce a PNG")
    return struct.unpack(">II", header[16:24])


def run() -> int:
    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_ids:
        raise RuntimeError("Telegram configuration is incomplete for photo smoke test")

    alert = {
        "title": "PRStK 圖卡推播測試",
        "lifecycle_state": "observation",
        "trigger_reason": "測試固定 1080×1350 圖卡、caption 與 Mini App 深連結",
        "market": "test",
        "source_tier": "test",
        "release_id": RELEASE_ID,
        "snapshot_id": SNAPSHOT_ID,
    }
    with tempfile.TemporaryDirectory(prefix="prstk-photo-smoke-") as temporary:
        photo_path = render_alert_card(alert, Path(temporary) / "photo-smoke.png")
        if _png_dimensions(photo_path) != (WIDTH, HEIGHT):
            raise RuntimeError("alert card dimensions are not 1080x1350")
        receipts = send_photo_briefs(
            token=settings.telegram_bot_token,
            chat_ids=settings.telegram_chat_ids,
            caption=CAPTION,
            photo_path=photo_path,
            mini_app_url=settings.dashboard_url,
            alert_id=ALERT_ID,
            release_id=RELEASE_ID,
            snapshot_id=SNAPSHOT_ID,
        )

    delivered = sum(receipt.status == "delivered" for receipt in receipts)
    failed = len(receipts) - delivered
    print(f"photo_card_dimensions={WIDTH}x{HEIGHT}")
    print(f"photo_delivery_delivered={delivered}")
    print(f"photo_delivery_failed={failed}")
    if failed:
        raise RuntimeError("photo smoke test did not deliver to every scoped recipient")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
