"""Two-phase scheduled brief delivery: prepare, publish, then notify."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from src.alert_card_renderer import RendererError, render_alert_card
from src.briefing_cards import build_briefing_snapshot
from src.config import get_settings
from src.event_ledger import EventLedger
from src.market_data import build_market_snapshot
from src.refresh_market_data import merge_published_metadata, write_snapshot
from src.release_gate import verify_release_for_delivery
from src.scheduled_brief import (
    _pick_event,
    _write_output,
    briefing_correlation,
    build_brief,
    write_event_lock_key,
)
from src.telegram_client import send_photo_briefs


def prepare(slot: str, snapshot_path: Path) -> dict:
    """Create the exact snapshot that will later be deployed and delivered."""
    snapshot = build_market_snapshot()
    snapshot["briefing"] = build_briefing_snapshot(snapshot, slot)
    if not write_snapshot(snapshot, snapshot_path):
        _write_output({"prepared": "false", "sent": "false", "reason": "snapshot_publish_skipped"})
        return snapshot
    event = _pick_event(snapshot, slot)
    correlation = briefing_correlation(snapshot, slot, event)
    metadata = {
        "trace_id": correlation["trace_id"],
        "snapshot_id": correlation["snapshot_id"],
        "observation_id": correlation["observation_id"],
    }
    snapshot.setdefault("briefing", {}).update(metadata)
    if not merge_published_metadata(metadata, destination=snapshot_path, expected_snapshot_id=correlation["snapshot_id"]):
        _write_output({"prepared": "false", "sent": "false", "reason": "snapshot_metadata_merge_skipped"})
        return snapshot
    _write_output({"prepared": "true", **metadata})
    return snapshot


def send(
    snapshot_path: Path,
    slot: str,
    manifest_path: Path,
    public_url: str | None = None,
) -> None:
    """Send only after local and deployed release manifests agree."""
    try:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _write_output({"sent": "false", "delivery_status": "blocked", "reason": f"snapshot_unreadable:{type(exc).__name__}"})
        return
    if not isinstance(snapshot, dict):
        _write_output({"sent": "false", "delivery_status": "blocked", "reason": "snapshot_not_object"})
        return
    snapshot_id = str(snapshot.get("snapshot_id") or "")
    gate = verify_release_for_delivery(
        manifest_path=manifest_path,
        expected_snapshot_id=snapshot_id,
        public_url=public_url,
    )
    if not gate.allowed:
        _write_output({
            "sent": "false",
            "delivery_status": "blocked",
            "reason": "release_gate_blocked",
            "release_id": gate.release_id,
            "snapshot_id": snapshot_id,
            "release_gate_errors": ";".join(gate.errors),
        })
        print("Release gate blocked Telegram delivery: " + "; ".join(gate.errors))
        return

    settings = get_settings()
    if not settings.telegram_ready:
        raise RuntimeError("Telegram configuration is incomplete")
    event = _pick_event(snapshot, slot)
    briefing = snapshot.get("briefing") or {}
    correlation = briefing_correlation(snapshot, slot, event)
    trace_id = str(briefing.get("trace_id") or correlation["trace_id"])
    observation_id = str(briefing.get("observation_id") or correlation["observation_id"])
    caption = build_brief(snapshot, slot)
    alert_id = str(
        (event or {}).get("event_cluster_key")
        or (event or {}).get("event_key")
        or trace_id
    )
    card_payload = {
        **(event or {}),
        "title": (event or {}).get("title") or (snapshot.get("briefing") or {}).get("title") or caption,
        "lifecycle_state": (event or {}).get("lifecycle_state") or "observation",
        "trigger_reason": (event or {}).get("trigger_reason") or caption,
        "release_id": gate.release_id,
        "snapshot_id": snapshot_id,
        "trace_id": trace_id,
    }
    # The release has already passed its public gate.  The card is generated
    # locally after that check and is never committed to the public snapshot.
    try:
        with tempfile.TemporaryDirectory(prefix="prstk-alert-card-") as temporary:
            photo_path = render_alert_card(card_payload, Path(temporary) / "alert-card.png")
            receipts = send_photo_briefs(
                token=settings.telegram_bot_token or "",
                chat_ids=settings.telegram_chat_ids,
                caption=caption,
                photo_path=photo_path,
                mini_app_url=settings.dashboard_url,
                alert_id=alert_id,
                release_id=gate.release_id,
                snapshot_id=snapshot_id,
            )
    except RendererError as exc:
        _write_output({
            "sent": "false",
            "delivery_status": "blocked",
            "reason": "renderer_error",
            "renderer_error_type": exc.error_type,
            "release_id": gate.release_id,
            "snapshot_id": snapshot_id,
            "alert_id": alert_id,
            "trace_id": trace_id,
        })
        print(f"Renderer blocked Telegram delivery: {exc.error_type}")
        return
    delivered = sum(receipt.status == "delivered" for receipt in receipts)
    failed = sum(receipt.status != "delivered" for receipt in receipts)
    _write_output({
        "sent": "true",
        "reason": "sent_partial" if failed else "sent",
        "release_id": gate.release_id,
        "trace_id": trace_id,
        "snapshot_id": snapshot_id,
        "observation_id": observation_id,
        "delivery_status": "delivered" if not failed else "partial" if delivered else "failed",
        "delivered_count": delivered,
        "failed_count": failed,
        "delivery_mode": "photo",
        "alert_id": alert_id,
    })
    if event:
        write_event_lock_key(event)
        ledger = EventLedger()
        ledger.mark_reminded({**event, "trace_id": trace_id})
        ledger.save()


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare or deliver a scheduled brief")
    parser.add_argument("--slot", required=True)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--send-only", action="store_true")
    parser.add_argument("--snapshot", type=Path, default=Path("site/data/market.json"))
    parser.add_argument("--manifest", type=Path, default=Path("site/data/release-manifest.json"))
    parser.add_argument("--public-url", default=None)
    args = parser.parse_args()
    if args.prepare_only == args.send_only:
        parser.error("choose exactly one of --prepare-only or --send-only")
    if args.prepare_only:
        prepare(args.slot, args.snapshot)
    else:
        send(args.snapshot, args.slot, args.manifest, args.public_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
