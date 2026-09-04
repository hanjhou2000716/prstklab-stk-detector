"""Release-gated Creator notification entrypoint for production workflows.

The scheduled market workflow may call this module only after the parent
release gate succeeds.  The Creator lane is opt-in (``CREATOR_NOTIFICATION_ENABLED``)
and fail-soft: a disabled or unavailable Creator input never blocks the core
market release.  Raw mail, attachment bytes and Telegram identifiers are never
written to the public release or receipt output.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, cast

from src.config import get_settings
from src.creator_delivery_store import (
    append_creator_delivery_receipts,
    load_creator_delivery_history,
    load_remote_creator_delivery_history,
)
from src.creator_media import MAX_MEDIA_BYTES, validate_creator_media
from src.creator_notification import deliver_creator_episode, deliver_creator_morning_digest
from src.creator_release import validate_creator_release
from src.railway_secret import delivery_shared_secret
from src.release_manifest import verify_release_files
from src.scheduled_brief import _write_output


def _enabled(value: str | None) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def _read_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _media_path(root: Path | None, episode_key: str) -> Path | None:
    """Resolve and validate a bounded private media attachment.

    A file existing under the private media root is not sufficient evidence
    that it is safe to send.  Validate the filename, size, MIME signature and
    bytes before crossing into the Telegram transport; invalid media must
    degrade to the text-only path rather than producing a blank/invalid photo.
    """
    if root is None or not root.is_dir():
        return None
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", episode_key).strip("._")
    if not stem:
        return None
    for suffix in (".png", ".jpg", ".jpeg"):
        candidate = (root / f"{stem}{suffix}").resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            continue
        if not candidate.is_file():
            continue
        try:
            if candidate.stat().st_size > MAX_MEDIA_BYTES:
                continue
            validation = validate_creator_media({
                "filename": candidate.name,
                "data": candidate.read_bytes(),
            })
        except (OSError, ValueError):
            continue
        if validation["availability"] == "private_ready":
            return candidate
    return None


def _load_creator_release(manifest_path: Path) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[str]]:
    manifest = _read_object(manifest_path)
    if manifest is None:
        return None, None, ["manifest_unreadable"]
    site_root = manifest_path.parent.parent
    errors = verify_release_files(manifest, root=site_root)
    if manifest.get("status") != "ready":
        errors.append("parent_release_not_ready")
    paths = cast(dict[str, Any], manifest.get("artifact_paths")) if isinstance(manifest.get("artifact_paths"), dict) else {}
    raw_creator_path = paths.get("creator-release.json")
    if not isinstance(raw_creator_path, str):
        return manifest, None, sorted(set(errors + ["creator_release_missing"]))
    creator_path = site_root / raw_creator_path
    creator = _read_object(creator_path)
    if creator is None:
        return manifest, None, sorted(set(errors + ["creator_release_unreadable"]))
    errors.extend(validate_creator_release(creator, parent_manifest=manifest))
    if manifest.get("creator_status") != "ready" or creator.get("status") != "ready":
        errors.append("creator_release_not_ready")
    return manifest, creator, sorted(set(errors))


def dispatch(
    *,
    manifest_path: Path,
    public_url: str,
    media_root: Path | None = None,
    receipt_path: Path | None = None,
    token: str | None = None,
    chat_ids: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Dispatch every new Creator episode and persist privacy-safe receipts."""
    if not _enabled(os.getenv("CREATOR_NOTIFICATION_ENABLED")):
        result = {"enabled": False, "status": "disabled", "sent": 0, "blocked": 0, "receipts": []}
        _write_output({"creator_enabled": "false", "creator_status": "disabled", "creator_sent": "0"})
        return result

    manifest, creator, errors = _load_creator_release(manifest_path)
    if errors or manifest is None or creator is None:
        result = {"enabled": True, "status": "blocked", "sent": 0, "blocked": 1, "reasons": errors, "receipts": []}
        _write_output({"creator_enabled": "true", "creator_status": "blocked", "creator_sent": "0", "creator_blocking_reason": ";".join(errors)})
        return result

    settings = get_settings()
    bot_token = token if token is not None else settings.telegram_bot_token
    recipients = chat_ids if chat_ids is not None else settings.telegram_chat_ids
    history = load_creator_delivery_history(receipt_path)
    railway_url = os.getenv("RAILWAY_STATUS_URL", "").strip()
    worker_url = os.getenv("RECEIPT_CALLBACK_URL", "").strip()
    history_url = worker_url or railway_url
    history_secret = (os.getenv("DELIVERY_RECEIPT_SHARED_SECRET", "").strip() or delivery_shared_secret()) if worker_url else delivery_shared_secret()
    remote_history, remote_history_status = load_remote_creator_delivery_history(history_url, history_secret)
    # The zero-cost Worker is canonical.  Railway remains an explicit rollback
    # path when the Worker history endpoint is unavailable.
    if worker_url and remote_history_status != "healthy" and railway_url:
        remote_history, remote_history_status = load_remote_creator_delivery_history(railway_url, delivery_shared_secret())
    if history_url and remote_history_status not in {"healthy", "not_configured"}:
        reason = f"creator_delivery_history_{remote_history_status}"
        _write_output({
            "creator_enabled": "true",
            "creator_status": "blocked",
            "creator_sent": "0",
            "creator_blocked": "1",
            "creator_blocking_reason": reason,
            "creator_remote_history_status": remote_history_status,
        })
        return {
            "enabled": True,
            "status": "blocked",
            "sent": 0,
            "blocked": 1,
            "reasons": [reason],
            "receipts": [],
            "remote_history_status": remote_history_status,
        }
    history.extend(remote_history)
    insights = cast(list[Any], creator.get("insights")) if isinstance(creator.get("insights"), list) else []
    morning_batch = creator.get("morning_batch") if isinstance(creator.get("morning_batch"), dict) else None
    if morning_batch is not None:
        # The release may contain historical Creator insights for the Mini App,
        # but the 10:30 notification is limited to the current batch.  A late
        # arrival is an additive delta: previously delivered episodes remain
        # protected by their normal episode idempotency keys.
        batch_records = morning_batch.get("records") if isinstance(morning_batch.get("records"), list) else []
        batch_episode_keys = {
            str(item.get("episode_key") or "").strip()
            for item in batch_records
            if isinstance(item, dict) and str(item.get("episode_key") or "").strip()
        }
        selected = [
            item for item in insights
            if isinstance(item, dict) and str(item.get("episode_key") or "").strip() in batch_episode_keys
        ]
        if morning_batch.get("late_arrivals"):
            late_creators = {
                str(item).strip().casefold()
                for item in morning_batch.get("late_arrivals") or []
                if str(item).strip()
            }
            selected = [
                item for item in selected
                if str(item.get("creator_id") or item.get("content_origin") or "").strip().casefold() in late_creators
                or bool(item.get("batch_late_arrival"))
            ]
        insights = selected if morning_batch.get("state") != "no_new_content" else []
    receipts: list[dict[str, Any]] = []
    sent = blocked = 0
    for insight in insights:
        if not isinstance(insight, dict):
            continue
        episode_key = str(insight.get("episode_key") or "").strip()
        if not episode_key:
            blocked += 1
            continue
        outcome = deliver_creator_episode(
            insight,
            release_id=str(manifest.get("release_id") or ""),
            creator_snapshot_id=str(manifest.get("creator_snapshot_id") or creator.get("snapshot_id") or ""),
            mini_app_url=public_url,
            release_ready=True,
            token=bot_token or "",
            chat_ids=recipients,
            media_path=_media_path(media_root, episode_key),
            delivery_history=history,
        )
        rows = cast(list[Any], outcome.get("receipts")) if isinstance(outcome.get("receipts"), list) else []
        valid_rows = [row for row in rows if isinstance(row, dict)]
        receipts.extend(valid_rows)
        # The release can contain duplicate insight rows after a source
        # reconciliation.  Feed receipts from this run back into the same
        # history used by the shared Creator gate so a duplicate cannot send
        # twice before the local receipt file is persisted.
        history.extend(valid_rows)
        if outcome.get("status") in {"delivered", "media_degraded"}:
            sent += 1
        elif "already_delivered" not in set(outcome.get("reasons") or []):
            blocked += 1
    if morning_batch is not None:
        digest = deliver_creator_morning_digest(
            morning_batch,
            release_id=str(manifest.get("release_id") or ""),
            creator_snapshot_id=str(manifest.get("creator_snapshot_id") or creator.get("snapshot_id") or ""),
            mini_app_url=public_url,
            release_ready=True,
            token=bot_token or "",
            chat_ids=recipients,
            delivery_history=history,
        )
        digest_receipts = cast(list[Any], digest.get("receipts")) if isinstance(digest.get("receipts"), list) else []
        valid_digest_receipts = [row for row in digest_receipts if isinstance(row, dict)]
        receipts.extend(valid_digest_receipts)
        history.extend(valid_digest_receipts)
        if digest.get("status") == "delivered":
            sent += 1
        elif digest.get("status") not in {"no_new_content", "already_delivered"}:
            blocked += 1
    if receipt_path and receipts:
        append_creator_delivery_receipts(receipt_path, receipts)
    result = {
        "enabled": True,
        "status": "delivered" if sent else "no_new_content" if not blocked else "blocked",
        "sent": sent,
        "blocked": blocked,
        "receipt_count": len(receipts),
        "receipts": receipts,
        "release_id": manifest.get("release_id"),
        "creator_release_id": creator.get("release_id"),
        "creator_snapshot_id": manifest.get("creator_snapshot_id") or creator.get("snapshot_id"),
    }
    delivered_receipts = sum(1 for row in receipts if row.get("delivery_status") == "delivered")
    failed_receipts = len(receipts) - delivered_receipts
    delivery_status = "delivered" if receipts and failed_receipts == 0 else "partial" if delivered_receipts else "failed"
    trace_id = f"creator-{str(result['release_id'] or 'release')}-{uuid.uuid4().hex[:12]}"
    _write_output({
        "creator_enabled": "true",
        "creator_status": result["status"],
        "creator_sent": str(sent),
        "creator_blocked": str(blocked),
        "creator_receipt_count": str(len(receipts)),
        "creator_release_id": result["release_id"],
        "creator_snapshot_id": result["creator_snapshot_id"],
        "creator_trace_id": trace_id,
        "creator_alert_id": result["creator_release_id"],
        "creator_delivery_mode": "photo" if any(row.get("media_mode") == "photo" for row in receipts) else "text",
        "creator_delivery_status": delivery_status,
        "creator_delivered_count": str(delivered_receipts),
        "creator_failed_count": str(failed_receipts),
        "creator_remote_history_status": remote_history_status,
        "creator_notification_keys": ",".join(sorted({
            str(row.get("notification_key") or "").strip()
            for row in receipts
            if str(row.get("notification_key") or "").strip()
        })[:200]),
    })
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Release-gated Creator notification dispatch")
    parser.add_argument("--manifest", type=Path, default=Path("site/data/release-manifest.json"))
    parser.add_argument("--public-url", default=os.getenv("DASHBOARD_URL", ""))
    parser.add_argument("--media-root", type=Path, default=Path(os.getenv("CREATOR_MEDIA_ROOT", "")) if os.getenv("CREATOR_MEDIA_ROOT") else None)
    parser.add_argument("--receipt-path", type=Path, default=Path(os.getenv("CREATOR_DELIVERY_RECEIPTS_PATH", "")) if os.getenv("CREATOR_DELIVERY_RECEIPTS_PATH") else None)
    args = parser.parse_args()
    if not str(args.public_url).startswith("https://"):
        raise SystemExit("Creator dispatch requires an HTTPS DASHBOARD_URL")
    dispatch(manifest_path=args.manifest, public_url=args.public_url, media_root=args.media_root, receipt_path=args.receipt_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["dispatch", "main"]
