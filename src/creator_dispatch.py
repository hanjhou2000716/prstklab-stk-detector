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
from src.creator_delivery_store import append_creator_delivery_receipts, load_creator_delivery_history
from src.creator_notification import deliver_creator_episode
from src.creator_release import validate_creator_release
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
    """Resolve only a bounded, filename-derived private media path."""
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
        if candidate.is_file():
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
    insights = cast(list[Any], creator.get("insights")) if isinstance(creator.get("insights"), list) else []
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
        receipts.extend(row for row in rows if isinstance(row, dict))
        if outcome.get("status") in {"delivered", "media_degraded"}:
            sent += 1
        else:
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
