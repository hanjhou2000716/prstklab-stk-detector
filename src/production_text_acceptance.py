"""Release-gated, single-recipient production text acceptance.

This replaces the historical photo acceptance path.  It verifies the public
release first, then sends exactly one canonical text message and writes a
privacy-safe receipt lineage.  Renderer artifacts remain CI-only.
"""

from __future__ import annotations

import argparse
import os
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.config import parse_chat_ids
from src.release_gate import ReleaseGateResult, verify_release_for_delivery
from src.telegram_client import TextDeliveryReceipt, canonical_prstk_risk_level, send_text_briefs_audited

# Keep the acceptance message on the same public presentation boundary as all
# other Telegram paths.  The internal R2 value is still passed separately to
# the sender and therefore remains available in the delivery receipt/audit.
CAPTION = "PRStK 受控驗證｜資料待核對"
ALERT_ID_PREFIX = "production-text-acceptance"


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
        raise ValueError("production text acceptance requires exactly one explicit chat ID")
    return recipients


def run(
    *, manifest: Path | str, public_url: str, token: str, chat_id: str,
    verifier: Callable[..., ReleaseGateResult] = verify_release_for_delivery,
    sender: Callable[..., tuple[TextDeliveryReceipt, ...]] = send_text_briefs_audited,
) -> dict[str, Any]:
    recipients = _single_recipient(chat_id)
    if not token.strip():
        raise ValueError("Telegram bot token is required for production acceptance")
    if not public_url.startswith("https://"):
        raise ValueError("public dashboard URL must use HTTPS")
    gate = verifier(
        manifest_path=manifest, public_url=public_url, public_attempts=3,
        public_delay=2.0, require_production_research=False,
    )
    if not gate.allowed:
        report = {"ok": False, "status": "release_blocked", "release_id": gate.release_id,
                  "snapshot_id": gate.snapshot_id, "errors": list(gate.errors),
                  "delivery_performed": False}
        _write_outputs({"sent": "false", "delivery_status": "blocked", "release_id": gate.release_id,
                        "snapshot_id": gate.snapshot_id, "delivery_mode": "text"})
        return report
    manifest_value = gate.manifest
    release_id = str(manifest_value.get("release_id") or gate.release_id)
    snapshot_id = str(manifest_value.get("market_snapshot_id") or gate.snapshot_id)
    if not release_id or not snapshot_id:
        raise ValueError("release gate did not return release and snapshot identity")
    alert_id = f"{ALERT_ID_PREFIX}-{release_id}"
    observation_id = f"{alert_id}-{uuid.uuid4().hex[:12]}"
    receipts = sender(
        token=token, chat_ids=recipients, text=CAPTION, dashboard_url=public_url,
        alert_id=alert_id, release_id=release_id, snapshot_id=snapshot_id,
        observation_id=observation_id, prstk_risk_level=canonical_prstk_risk_level({"prstk_risk_level": "R2"}),
    )
    delivered = sum(item.status == "delivered" for item in receipts)
    failed = len(receipts) - delivered
    status = "delivered" if delivered == 1 and failed == 0 else "failed"
    trace_id = f"{alert_id}-{uuid.uuid4().hex[:16]}"
    report = {"ok": status == "delivered", "status": status, "release_id": release_id,
              "snapshot_id": snapshot_id, "alert_id": alert_id, "observation_id": observation_id,
              "trace_id": trace_id, "recipient_count": 1, "delivered_count": delivered,
              "failed_count": failed, "delivery_performed": True, "delivery_mode": "text"}
    _write_outputs({"sent": "true", "trace_id": trace_id, "alert_id": alert_id,
                    "release_id": release_id, "snapshot_id": snapshot_id,
                    "observation_id": observation_id, "delivery_mode": "text",
                    "delivery_status": status, "delivered_count": delivered,
                    "failed_count": failed, "renderer_error_type": "not_applicable"})
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("site/data/release-manifest.json"))
    parser.add_argument("--public-url", default=os.environ.get("DASHBOARD_URL", ""))
    parser.add_argument("--chat-id", default=os.environ.get("TELEGRAM_CHAT_IDS", ""))
    args = parser.parse_args()
    report = run(manifest=args.manifest, public_url=args.public_url,
                 token=os.environ.get("TELEGRAM_BOT_TOKEN", ""), chat_id=args.chat_id)
    print(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
