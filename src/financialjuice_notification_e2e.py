"""Offline end-to-end acceptance for the FinancialJuice delivery lane."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from src.external_source_parsers import parse_financialjuice_email
from src.financialjuice_notification import (
    deliver_financialjuice_event,
    financialjuice_caption,
)
from src.financialjuice_priority import project_financialjuice_priority
from src.telegram_client import PhotoDeliveryReceipt

_FIXTURE = (
    "Item 1\nImportance: 9/10\nOriginal headline: Oil supply disruption\n"
    "Translation: Public oil supply update\nEntities: Iran, oil\n"
    "AI commentary: Supply risk remains under observation.\n"
    "Possible impact: Oil volatility.\n"
    "Item 2\nImportance: 7/10\nOriginal headline: Semiconductor policy update\n"
    "Translation: Public semiconductor update\nEntities: China, semiconductor\n"
    "AI commentary: Requires confirmation.\nPossible impact: Technology volatility."
)


def run_financialjuice_notification_e2e() -> dict[str, Any]:
    """Exercise FJ policy, release binding, partial delivery and replay safety."""
    parsed = parse_financialjuice_email(
        sender="alerts@financialjuice.com",
        subject="priority alert",
        body=_FIXTURE,
        message_id="fj-notification-e2e-message",
    )
    raw_items = parsed.get("items")
    items = [item for item in raw_items if isinstance(item, dict)] if isinstance(raw_items, list) else []
    projection = project_financialjuice_priority(items)
    events = [item for item in projection.get("events", []) if isinstance(item, dict)]
    event = events[0] if events else {}
    sent_calls: list[tuple[str, ...]] = []
    call_number = 0

    def fake_sender(**kwargs: Any) -> tuple[PhotoDeliveryReceipt, ...]:
        nonlocal call_number
        call_number += 1
        recipients = tuple(str(item) for item in kwargs["chat_ids"])
        sent_calls.append(recipients)
        result: list[PhotoDeliveryReceipt] = []
        for index, chat_id in enumerate(recipients):
            recipient_hash = __import__("hashlib").sha256(chat_id.encode("utf-8")).hexdigest()[:12]
            if call_number == 1 and index == 1:
                result.append(PhotoDeliveryReceipt(
                    kwargs["alert_id"], kwargs["release_id"], kwargs["snapshot_id"],
                    recipient_hash, "failed", error_class="temporary_api",
                    observation_id=kwargs.get("observation_id", ""),
                ))
            else:
                result.append(PhotoDeliveryReceipt(
                    kwargs["alert_id"], kwargs["release_id"], kwargs["snapshot_id"],
                    recipient_hash, "delivered", message_id=100 + call_number,
                    telegram_file_id="file-e2e", telegram_file_id_hash="file-hash",
                    observation_id=kwargs.get("observation_id", ""),
                ))
        return tuple(result)

    with tempfile.TemporaryDirectory(prefix="prstk-fj-e2e-") as directory:
        photo_path = Path(directory) / "alert.png"
        photo_path.write_bytes(b"synthetic-rendered-png")
        recipients = ("e2e-fj-recipient-a", "e2e-fj-recipient-b")
        first = deliver_financialjuice_event(
            event,
            release_id="e2e-release-fj",
            snapshot_id="e2e-snapshot-fj",
            mini_app_url="https://example.test/app",
            release_ready=True,
            token="offline-token",
            chat_ids=recipients,
            photo_path=photo_path,
            photo_sender=fake_sender,
        )
        history = [
            {
                "notification_key": first.get("notification_key"),
                "recipient_hash": row.get("recipient_hash"),
                "delivery_status": row.get("delivery_status"),
            }
            for row in first.get("receipts", [])
        ]
        second = deliver_financialjuice_event(
            event,
            release_id="e2e-release-fj",
            snapshot_id="e2e-snapshot-fj",
            mini_app_url="https://example.test/app",
            release_ready=True,
            token="offline-token",
            chat_ids=recipients,
            photo_path=photo_path,
            delivery_history=history,
            photo_sender=fake_sender,
        )
        replay_history = history + [
            {
                "notification_key": second.get("notification_key"),
                "recipient_hash": row.get("recipient_hash"),
                "delivery_status": row.get("delivery_status"),
            }
            for row in second.get("receipts", [])
        ]
        replay = deliver_financialjuice_event(
            event,
            release_id="e2e-release-fj",
            snapshot_id="e2e-snapshot-fj",
            mini_app_url="https://example.test/app",
            release_ready=True,
            token="offline-token",
            chat_ids=recipients,
            photo_path=photo_path,
            delivery_history=replay_history,
            photo_sender=fake_sender,
        )

    first_receipts = first.get("receipts", [])
    second_receipts = second.get("receipts", [])
    check = {
        "compound_item_is_eligible": event.get("notification_status") == "eligible",
        "vendor_threshold_preserved": event.get("vendor_importance") == 9,
        "vendor_score_does_not_change_risk": event.get("source_trace", {}).get("vendor_importance_is_not_risk") is True,
        "caption_bounded": len(financialjuice_caption(event)) <= 40,
        "release_bound_deep_link": "release=e2e-release-fj" in str(first.get("mini_app_url")),
        "partial_delivery_isolated": first.get("status") == "partial" and len(first_receipts) == 2,
        "retry_only_failed_recipient": sent_calls == [recipients, (recipients[1],)],
        "replay_suppressed": replay.get("status") == "already_delivered",
        "receipt_lineage": all(
            row.get("release_id") == "e2e-release-fj"
            and row.get("snapshot_id") == "e2e-snapshot-fj"
            for row in [*first_receipts, *second_receipts]
        ),
        "recipient_ids_hashed": all(
            all("e2e-fj-recipient" not in str(value) for value in row.values())
            for row in [*first_receipts, *second_receipts]
        ),
    }
    return {
        "mode": "SIMULATED",
        "ok": all(check.values()),
        "checks": check,
        "first_status": first.get("status"),
        "second_status": second.get("status"),
        "replay_status": replay.get("status"),
        "receipt_count": len(first_receipts) + len(second_receipts),
        "network_used": False,
        "secrets_used": False,
        "production_side_effects": False,
    }


__all__ = ["run_financialjuice_notification_e2e"]
