"""Run a release-gated, single-recipient production photo acceptance check.

Unlike the generic photo smoke test, this command first verifies that the
checked-in release and the deployed Pages release are the same immutable
bundle.  It then renders one card using that release lineage and sends one
``sendPhoto`` message to exactly one explicitly supplied recipient.  The
command is intentionally opt-in and fail-closed; it is not used by scheduled
broadcasts.
"""

from __future__ import annotations

import argparse
import os
import struct
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.alert_card_renderer import HEIGHT, WIDTH, render_alert_card
from src.config import parse_chat_ids
from src.release_gate import ReleaseGateResult, verify_release_for_delivery
from src.telegram_client import PhotoDeliveryReceipt, send_photo_briefs

CAPTION = "🧪 PRStK 正式圖卡驗證｜觀察"
ALERT_ID_PREFIX = "production-photo-smoke"


def _png_dimensions(path: Path) -> tuple[int, int]:
    header = path.read_bytes()
    if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ValueError("renderer did not produce a PNG")
    return struct.unpack(">II", header[16:24])


def _write_outputs(values: dict[str, object]) -> None:
    destination = os.environ.get("GITHUB_OUTPUT")
    if not destination:
        return
    with Path(destination).open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            text = str(value).replace("%", "%25").replace("\n", "%0A").replace("\r", "%0D")
            handle.write(f"{key}={text}\n")


def _single_recipient(value: str) -> tuple[str, ...]:
    recipients = parse_chat_ids(value)
    if len(recipients) != 1 or recipients[0] != value.strip():
        raise ValueError("production photo acceptance requires exactly one explicit chat ID")
    return recipients


def run(
    *,
    manifest: Path | str,
    public_url: str,
    token: str,
    chat_id: str,
    verifier: Callable[..., ReleaseGateResult] = verify_release_for_delivery,
    renderer: Callable[[dict[str, Any], str | Path], Path] = render_alert_card,
    sender: Callable[..., tuple[PhotoDeliveryReceipt, ...]] = send_photo_briefs,
) -> dict[str, Any]:
    """Verify, render and send one release-bound photo acceptance message."""
    recipients = _single_recipient(chat_id)
    if not token.strip():
        raise ValueError("Telegram bot token is required for production acceptance")
    if not public_url.startswith("https://"):
        raise ValueError("public dashboard URL must use HTTPS")

    gate = verifier(
        manifest_path=manifest,
        public_url=public_url,
        public_attempts=3,
        public_delay=2.0,
        require_production_research=False,
    )
    if not gate.allowed:
        report = {
            "ok": False,
            "status": "release_blocked",
            "release_id": gate.release_id,
            "snapshot_id": gate.snapshot_id,
            "errors": list(gate.errors),
            "delivery_performed": False,
        }
        _write_outputs({"sent": "false", "delivery_status": "blocked", "release_id": gate.release_id, "snapshot_id": gate.snapshot_id})
        return report

    manifest_value = gate.manifest
    release_id = str(manifest_value.get("release_id") or gate.release_id)
    snapshot_id = str(manifest_value.get("market_snapshot_id") or gate.snapshot_id)
    if not release_id or not snapshot_id:
        raise ValueError("release gate did not return release and snapshot identity")
    alert_id = f"{ALERT_ID_PREFIX}-{release_id}"
    observation_id = f"{alert_id}-{uuid.uuid4().hex[:12]}"
    alert = {
        "title": "PRStK 正式圖卡驗證",
        "lifecycle_state": "observation",
        "trigger_reason": "受控單一收件人驗證：Pages release、圖卡與 Telegram lineage",
        "event": "本次僅驗證公開 release 與圖卡傳送，不代表市場訊號。",
        "importance": "測試訊息不改變任何市場風險判定。",
        "market_transmission": "無交易或風險推論；等待正式事件證據。",
        "watch": "確認 Telegram 圖卡、caption 與 Mini App 深連結可用。",
        "source_evidence": [f"Pages release {release_id}"],
        "market_evidence": [f"market snapshot {snapshot_id}"],
        "release_id": release_id,
        "snapshot_id": snapshot_id,
        "invalidation_condition": "驗證完成後此測試訊息立即失效。",
    }
    with tempfile.TemporaryDirectory(prefix="prstk-production-photo-") as temporary:
        photo_path = renderer(alert, Path(temporary) / "production-photo-smoke.png")
        dimensions = _png_dimensions(Path(photo_path))
        if dimensions != (WIDTH, HEIGHT):
            raise ValueError(f"renderer dimensions are {dimensions}, expected {(WIDTH, HEIGHT)}")
        receipts = sender(
            token=token,
            chat_ids=recipients,
            caption=CAPTION,
            photo_path=photo_path,
            mini_app_url=public_url,
            alert_id=alert_id,
            release_id=release_id,
            snapshot_id=snapshot_id,
            observation_id=observation_id,
        )

    delivered = sum(item.status == "delivered" for item in receipts)
    failed = len(receipts) - delivered
    status = "delivered" if delivered == 1 and failed == 0 else "failed"
    trace_id = f"{alert_id}-{uuid.uuid4().hex[:16]}"
    report = {
        "ok": status == "delivered",
        "status": status,
        "release_id": release_id,
        "snapshot_id": snapshot_id,
        "alert_id": alert_id,
        "observation_id": observation_id,
        "trace_id": trace_id,
        "card_dimensions": {"width": dimensions[0], "height": dimensions[1]},
        "recipient_count": 1,
        "delivered_count": delivered,
        "failed_count": failed,
        "delivery_performed": True,
        "renderer_error_type": None,
    }
    _write_outputs({
        "sent": "true",
        "trace_id": trace_id,
        "alert_id": alert_id,
        "release_id": release_id,
        "snapshot_id": snapshot_id,
        "observation_id": observation_id,
        "delivery_mode": "photo",
        "delivery_status": status,
        "delivered_count": delivered,
        "failed_count": failed,
        "renderer_error_type": "",
    })
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("site/data/release-manifest.json"))
    parser.add_argument("--public-url", default=os.environ.get("DASHBOARD_URL", ""))
    parser.add_argument("--chat-id", default=os.environ.get("TELEGRAM_CHAT_IDS", ""))
    args = parser.parse_args()
    report = run(
        manifest=args.manifest,
        public_url=args.public_url,
        token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        chat_id=args.chat_id,
    )
    print(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

