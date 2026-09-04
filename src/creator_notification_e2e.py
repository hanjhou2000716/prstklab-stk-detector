"""Offline acceptance lane for the canonical Creator notification path.

This module deliberately stops at injected Telegram senders.  It proves the
same release-gated photo/text orchestration used in production without
contacting Telegram or persisting a real recipient identifier.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from src.creator_morning_batch import build_creator_morning_batch
from src.creator_notification import deliver_creator_episode, deliver_creator_morning_digest
from src.telegram_client import PhotoDeliveryReceipt, TelegramDelivery, TelegramResult, alert_mini_app_url

_RECIPIENTS = ("e2e-recipient-a", "e2e-recipient-b")
_RELEASE_ID = "creator-e2e-release"
_SNAPSHOT_ID = "creator-e2e-snapshot"
_MINI_APP = "https://example.test/app"


def _insight(creator: str, episode: str) -> dict[str, Any]:
    return {
        "creator_id": creator,
        "creator_name": creator.title(),
        "content_origin": creator,
        "episode_key": episode,
        "episode_title": f"{creator} public observation",
        "key_takeaways": ["等待來源核對"],
        "public_safe": True,
        "notification_type": "initial",
    }


def _run_creator_notification_e2e_impl() -> dict[str, Any]:
    """Run a deterministic photo, digest, late-delta and replay audit."""
    photo_calls: list[dict[str, Any]] = []
    text_calls: list[dict[str, Any]] = []

    def fake_photo(**kwargs: Any) -> tuple[PhotoDeliveryReceipt, ...]:
        photo_calls.append(kwargs)
        return (
            PhotoDeliveryReceipt(
                alert_id=str(kwargs["alert_id"]),
                release_id=str(kwargs["release_id"]),
                snapshot_id=str(kwargs["snapshot_id"]),
                chat_id_hash="a" * 16,
                status="delivered",
                message_id=101,
                telegram_file_id_hash="f" * 16,
                observation_id=str(kwargs["observation_id"]),
            ),
            PhotoDeliveryReceipt(
                alert_id=str(kwargs["alert_id"]),
                release_id=str(kwargs["release_id"]),
                snapshot_id=str(kwargs["snapshot_id"]),
                chat_id_hash="b" * 16,
                status="failed",
                error_class="recipient_unavailable",
                observation_id=str(kwargs["observation_id"]),
            ),
        )

    def fake_text(**kwargs: Any) -> tuple[TelegramDelivery, ...]:
        text_calls.append(kwargs)
        return (
            TelegramDelivery(_RECIPIENTS[0], TelegramResult(201)),
            TelegramDelivery(_RECIPIENTS[1], error="recipient_unavailable"),
        )

    with TemporaryDirectory(prefix="creator-notification-e2e-") as tmp:
        image = Path(tmp) / "creator-card.png"
        # The production sender receives an approved path; renderer content is
        # covered by the dedicated card tests.  A non-empty file is sufficient
        # to prove the photo branch is selected here.
        image.write_bytes(b"e2e-image-placeholder")
        insight = _insight("haojiao", "creator-e2e-episode")
        episode = deliver_creator_episode(
            insight,
            release_id=_RELEASE_ID,
            creator_snapshot_id=_SNAPSHOT_ID,
            mini_app_url=_MINI_APP,
            release_ready=True,
            token="offline-token",
            chat_ids=_RECIPIENTS,
            media_path=image,
            photo_sender=fake_photo,
            text_sender=fake_text,
        )

        records = [
            {
                "creator_id": "haojiao",
                "episode_key": "creator-e2e-morning-haojiao",
                "published_at": "2026-08-21T01:55:00+00:00",
                "received_at": "2026-08-21T02:00:00+00:00",
                "public_safe": True,
                "parse_status": "parsed",
            },
            {
                "creator_id": "jenny",
                "episode_key": "creator-e2e-morning-jenny",
                "published_at": "2026-08-21T02:00:00+00:00",
                "received_at": "2026-08-21T02:20:00+00:00",
                "public_safe": True,
                "parse_status": "parsed",
            },
        ]
        batch = build_creator_morning_batch(
            records,
            as_of="2026-08-21T03:00:00+00:00",
            expected_creators=("haojiao", "jenny"),
        )
        digest = deliver_creator_morning_digest(
            batch,
            release_id=_RELEASE_ID,
            creator_snapshot_id=_SNAPSHOT_ID,
            mini_app_url=_MINI_APP,
            release_ready=True,
            token="offline-token",
            chat_ids=_RECIPIENTS,
            text_sender=fake_text,
        )
        replay = deliver_creator_morning_digest(
            batch,
            release_id=_RELEASE_ID,
            creator_snapshot_id=_SNAPSHOT_ID,
            mini_app_url=_MINI_APP,
            release_ready=True,
            token="offline-token",
            chat_ids=_RECIPIENTS,
            delivery_history=[
                {"notification_key": digest["notification_key"], "delivery_status": "partial"}
            ],
            text_sender=fake_text,
        )
        late_records = [*records[:1], {
            "creator_id": "jenny",
            "episode_key": "creator-e2e-morning-jenny-late",
            "published_at": "2026-08-21T02:10:00+00:00",
            "received_at": "2026-08-21T02:55:00+00:00",
            "public_safe": True,
            "parse_status": "parsed",
        }]
        late_batch = build_creator_morning_batch(
            late_records,
            as_of="2026-08-21T04:00:00+00:00",
            expected_creators=("haojiao", "jenny"),
        )
        late_digest = deliver_creator_morning_digest(
            late_batch,
            release_id=_RELEASE_ID,
            creator_snapshot_id=_SNAPSHOT_ID,
            mini_app_url=_MINI_APP,
            release_ready=True,
            token="offline-token",
            chat_ids=_RECIPIENTS,
            delivery_history=[
                {"notification_key": digest["notification_key"], "delivery_status": "partial"}
            ],
            text_sender=fake_text,
        )

    photo_call = photo_calls[0] if photo_calls else {}
    photo_query = parse_qs(urlparse(alert_mini_app_url(
        str(photo_call.get("mini_app_url") or ""),
        alert_id=str(photo_call.get("alert_id") or ""),
        release_id=str(photo_call.get("release_id") or ""),
        snapshot_id=str(photo_call.get("snapshot_id") or ""),
        observation_id=str(photo_call.get("observation_id") or ""),
    )).query)
    digest_call = next((item for item in text_calls if "Creator morning" in str(item.get("text"))), {})
    receipts = list(episode.get("receipts") or [])
    receipt_privacy = all(
        isinstance(item, dict)
        and item.get("recipient_hash")
        and "chat_id" not in item
        and item.get("release_id") == _RELEASE_ID
        and item.get("creator_snapshot_id") == _SNAPSHOT_ID
        for item in receipts
    )
    checks = {
        "photo_branch_used": episode.get("media_mode") == "photo" and len(photo_calls) == 1,
        "photo_per_recipient_isolated": [item.get("delivery_status") for item in receipts] == ["delivered", "failed"],
        "photo_lineage_bound": (
            str(photo_call.get("release_id")) == _RELEASE_ID
            and str(photo_call.get("snapshot_id")) == _SNAPSHOT_ID
            and str(photo_call.get("observation_id")) == "creator-e2e-episode"
        ),
        "photo_deep_link_bound": photo_query.get("release") == [_RELEASE_ID] and photo_query.get("snapshot") == [_SNAPSHOT_ID],
        "receipt_privacy": receipt_privacy,
        "morning_batch_complete_with_late": (
            batch.get("state") == "complete"
            and batch.get("late_arrivals") == []
            and late_batch.get("late_arrivals") == ["jenny"]
        ),
        "digest_sent_once": digest.get("status") == "delivered" and replay.get("status") == "already_delivered",
        "digest_deep_link_bound": parse_qs(urlparse(str(digest_call.get("target_url") or "")).query).get("release") == [_RELEASE_ID],
        "late_delta_reachable": late_digest.get("status") == "delivered" and late_digest.get("notification_key", "").endswith(":late_delta"),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "network_used": False,
        "secrets_used": False,
        "production_side_effects": False,
        "recipient_count": len(_RECIPIENTS),
        "receipt_count": len(receipts),
        "receipt_statuses": [item.get("delivery_status") for item in receipts],
        "digest_status": digest.get("status"),
        "replay_status": replay.get("status"),
        "late_delta_status": late_digest.get("status"),
    }


def run_creator_notification_e2e() -> dict[str, Any]:
    """Run offline delivery mechanics with an explicit in-memory fixture lane.

    Production Creator providers are retired.  This audit still exercises the
    existing sender, receipt isolation and replay mechanics by enabling only
    its fixture lane; it never changes the production registry or contacts
    Telegram.
    """
    with patch("src.creator_notification.creator_ids", return_value=("haojiao", "jenny")), \
        patch("src.creator_delivery_contract.is_active_creator", return_value=True):
        return _run_creator_notification_e2e_impl()


__all__ = ["run_creator_notification_e2e"]
