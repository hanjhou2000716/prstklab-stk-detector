"""Offline Actions-to-Mini-App-to-Telegram delivery verification.

The harness composes the existing release dry-run and Telegram photo sender
with a local HTTP mock.  It never reads production secrets or contacts the
Telegram API, but still verifies the one-message/photo/file-id contract.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

from src.alert_card_renderer import render_alert_card
from src.system_dry_run import run_dry_run
from src.telegram_client import send_photo_briefs


class _Response:
    ok = True
    status_code = 200

    def __init__(self, message_id: int) -> None:
        self._message_id = message_id

    def json(self) -> dict[str, Any]:
        return {
            "ok": True,
            "result": {"message_id": self._message_id, "photo": [{"file_id": "ci-file-id"}]},
        }


def run_full_offline_e2e() -> dict[str, Any]:
    """Run the composed release, renderer, deep-link and mocked delivery gate."""
    release = run_dry_run()
    calls: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any) -> _Response:
        calls.append({"url": url, **kwargs})
        return _Response(len(calls))

    with tempfile.TemporaryDirectory(prefix="prstk-full-e2e-") as temporary:
        photo = render_alert_card(
            {"title": "CI offline verification", "lifecycle_state": "observation"},
            str(Path(temporary) / "alert.png"),
        )
        with patch("src.telegram_client.requests.post", side_effect=fake_post):
            receipts = send_photo_briefs(
                token="ci-only-token",
                chat_ids=("ci-recipient-a", "ci-recipient-b"),
                caption="🔵 CI 圖卡觀察｜等待核對",
                photo_path=photo,
                mini_app_url="https://example.test/app",
                alert_id="ci-alert",
                release_id="ci-release",
                snapshot_id="ci-snapshot",
            )
    delivered = [item.status == "delivered" for item in receipts]
    first_uploaded = bool(calls and calls[0].get("files"))
    second_reused = len(calls) == 2 and calls[1].get("data", {}).get("photo") == "ci-file-id"
    return {
        "ok": bool(release.get("ok")) and all(delivered) and first_uploaded and second_reused,
        "release": release,
        "delivery_count": len(receipts),
        "delivered_count": sum(delivered),
        "file_id_reused": second_reused,
        "network_calls_mocked": len(calls),
    }


if __name__ == "__main__":
    import json

    print(json.dumps(run_full_offline_e2e(), ensure_ascii=False, sort_keys=True))
