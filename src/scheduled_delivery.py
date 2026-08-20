"""Two-phase scheduled brief delivery: prepare, publish, then notify."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.alert_budget import decide_alert_budget
from src.alert_card_renderer import RendererError, render_alert_card
from src.briefing_cards import build_briefing_snapshot
from src.config import get_settings
from src.creator_provider_registry import creator_ids
from src.event_ledger import EventLedger
from src.external_observation_input import (
    external_observations_path,
    external_source_health,
    external_source_health_from_remote,
    load_external_observations,
    merge_external_source_health,
)
from src.market_data import build_market_snapshot
from src.railway_observation_client import load_railway_observations
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

_DEFAULT_CREATOR_RECORDS_PATH = Path("creator/public-records.json")


def _railway_observations_configured() -> bool:
    """Return whether the optional sanitized Railway ingress is configured."""
    return bool(
        os.getenv("RAILWAY_OBSERVATIONS_URL", "").strip()
        or os.getenv("RAILWAY_STATUS_URL", "").strip()
        or os.getenv("RAILWAY_STATUS_SHARED_SECRET", "").strip()
    )


def _merge_external_observations(
    local_rows: list[dict],
    remote_rows: list[dict],
) -> list[dict]:
    """Merge remote reviewed rows over local fallback rows by observation ID."""
    merged: dict[str, dict] = {}
    for row in [*local_rows, *remote_rows]:
        if not isinstance(row, dict):
            continue
        key = str(row.get("observation_id") or "").strip()
        if key:
            merged[key] = row
    return list(merged.values())


def _creator_records_path() -> Path | None:
    """Resolve an external, public-safe Creator records file.

    The checked-in default contains only reviewed public observations.  It is
    deliberately outside the Pages tree and travels through the same privacy
    boundary as an operator-provided ingress file.
    """
    configured = os.getenv("CREATOR_RECORDS_PATH", "").strip()
    candidate = Path(configured).expanduser() if configured else _DEFAULT_CREATOR_RECORDS_PATH
    path = candidate.resolve()
    public_root = (Path.cwd() / "site").resolve()
    if path.is_relative_to(public_root) or not path.is_file():
        return None
    return path


def _creator_records_from_observations(rows: list[dict]) -> list[dict]:
    """Project Railway's reviewed Creator observations into release records."""
    records: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or not row.get("public_safe"):
            continue
        provider = str(row.get("content_origin") or row.get("source") or "").strip().casefold()
        if provider not in creator_ids():
            continue
        key = str(row.get("episode_key") or row.get("observation_id") or "").strip()
        if not key or key in seen or str(row.get("parse_status") or "normalized").casefold() in {"parse_failed", "unsupported_template", "invalid_source", "duplicate"}:
            continue
        record = dict(row)
        record.setdefault("creator_id", provider)
        record.setdefault("content_origin", provider)
        record.setdefault("episode_key", key)
        record["public_safe"] = True
        seen.add(key)
        records.append(record)
    return records


def _load_creator_records(extra_rows: list[dict] | None = None) -> list[dict]:
    """Load only the optional sanitized creator input outside the Pages tree."""
    path = _creator_records_path()
    safe_records: list[dict] = []
    blocked_states = {"parse_failed", "unsupported_template", "invalid_source", "duplicate"}
    private_fields = {"body", "raw_body", "local_path", "private_url", "attachments", "data"}
    if path is not None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            payload = []
        if isinstance(payload, dict):
            payload = payload.get("records")
        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    continue
                if any(item.get(field) not in (None, "", [], {}) for field in private_fields):
                    continue
                if str(item.get("parse_status") or "").strip() in blocked_states:
                    continue
                safe_records.append(item)
    combined = [*safe_records, *(_creator_records_from_observations(extra_rows or []))]
    deduped: dict[str, dict] = {}
    for index, item in enumerate(combined):
        key = str(item.get("episode_key") or item.get("observation_id") or "").strip()
        # Historical sanitized fixtures predate episode_key.  Preserve them
        # for backward compatibility while still making duplicate merging
        # deterministic within one refresh.
        deduped[key or f"legacy:{index}"] = item
    return list(deduped.values())


def _creator_input_failures() -> dict[str, str]:
    """Classify configured input failures without exposing paths or payloads."""
    configured = bool(os.getenv("CREATOR_RECORDS_PATH", "").strip()) or _DEFAULT_CREATOR_RECORDS_PATH.is_file()
    if not configured or os.getenv("CREATOR_NOTIFICATION_ENABLED", "").strip().lower() != "true":
        return {}
    path = _creator_records_path()
    if path is None:
        return {provider: "creator_records_unavailable" for provider in creator_ids()}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {provider: "creator_records_parse_failed" for provider in creator_ids()}
    if isinstance(payload, dict):
        payload = payload.get("records")
    if not isinstance(payload, list):
        return {provider: "creator_records_invalid_shape" for provider in creator_ids()}
    blocked_states = {"parse_failed", "unsupported_template", "invalid_source", "duplicate"}
    private_fields = {"body", "raw_body", "local_path", "private_url", "attachments", "data"}
    failures: dict[str, str] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        provider = str(item.get("content_origin") or item.get("source") or "").strip().lower()
        if provider not in creator_ids():
            continue
        if str(item.get("parse_status") or "").strip().lower() in blocked_states:
            failures[provider] = "creator_records_parse_failed"
        elif any(item.get(field) not in (None, "", [], {}) for field in private_fields):
            failures[provider] = "creator_records_private_fields"
    return failures


def prepare(slot: str, snapshot_path: Path) -> dict:
    """Create the exact snapshot that will later be deployed and delivered."""
    snapshot = build_market_snapshot()
    external_path = external_observations_path()
    local_observations, local_rejected = load_external_observations(external_path)
    remote_observations: list[dict] = []
    remote_health: dict[str, Any] = {}
    if _railway_observations_configured():
        remote_observations, remote_health = load_railway_observations()
    all_external_observations = _merge_external_observations(local_observations, remote_observations)
    # FinancialJuice observations feed the event pipeline; Creator rows use
    # the separate attributed-content lane and must not be counted as FJ
    # market evidence or shown under the FJ source-health label.
    creator_records = _load_creator_records(all_external_observations)
    external_observations = [
        row for row in all_external_observations
        if str(row.get("content_origin") or row.get("source") or "").strip().casefold() == "financialjuice"
    ]
    # Project FinancialJuice into the same release-bound event lane as other
    # public events.  The vendor score is kept separate from PRStK risk and
    # every non-send decision remains visible to Mini App/audit consumers.
    from src.financialjuice_priority import project_financialjuice_priority

    existing_events = ((snapshot.get("events") or {}).get("items") or []) if isinstance(snapshot.get("events"), dict) else []
    fj_projection = project_financialjuice_priority(external_observations, existing_events=existing_events)
    if fj_projection["events"]:
        if not isinstance(snapshot.get("events"), dict):
            snapshot["events"] = {"items": []}
        snapshot["events"].setdefault("items", []).extend(fj_projection["events"])
    snapshot["financialjuice_priority_decisions"] = fj_projection["decisions"]
    snapshot["financialjuice_priority_events"] = [
        event for event in fj_projection["events"] if event.get("notification_status") == "eligible"
    ]
    remote_rejected = remote_health.get("rejected_count")
    external_rejected = local_rejected + (int(remote_rejected) if isinstance(remote_rejected, (int, str, float)) else 0)
    if external_observations:
        snapshot["external_observations"] = external_observations
    elif "external_observations" not in snapshot:
        snapshot["external_observations"] = []
    checked_at = datetime.now(UTC)
    external_health: dict[str, Any] | None
    if _railway_observations_configured():
        external_health = external_source_health_from_remote(
            remote_health,
            accepted=external_observations,
            rejected=external_rejected,
            checked_at=checked_at,
        )
    else:
        external_health = external_source_health(
            path=external_path,
            accepted=external_observations,
            rejected=external_rejected,
            checked_at=checked_at,
        )
    if external_health:
        snapshot["source_health"] = merge_external_source_health(
            snapshot.get("source_health") or {}, external_health
        )
        snapshot["external_source_health"] = external_health
    # Creator feeds are optional, but their operational state belongs in the
    # same source-health contract as the published market snapshot.  Keep this
    # merge after loading the external file so the market builder remains
    # reusable for non-Creator refreshes.
    if _creator_records_path() is not None or os.getenv("CREATOR_NOTIFICATION_ENABLED", "").strip():
        from src.creator_source_health import build_creator_source_health, merge_creator_sources

        creator_rows = build_creator_source_health(
            creator_records,
            checked_at=datetime.now(UTC),
            enabled=os.getenv("CREATOR_NOTIFICATION_ENABLED", "").strip().lower() == "true",
            configured=_creator_records_path() is not None,
            failures=_creator_input_failures(),
        )
        snapshot["source_health"] = merge_creator_sources(snapshot.get("source_health") or {}, creator_rows)
        snapshot["creator_source_health"] = creator_rows
    if creator_records:
        snapshot["creator_insights"] = creator_records
    snapshot["briefing"] = build_briefing_snapshot(snapshot, slot)
    if not write_snapshot(snapshot, snapshot_path):
        _write_output({"prepared": "false", "sent": "false", "reason": "snapshot_publish_skipped"})
        return snapshot
    event = _pick_event(snapshot, slot)
    correlation = briefing_correlation(snapshot, slot, event)
    metadata: dict[str, object] = {
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
        require_production_research=True,
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
    budget = {"allowed": True, "reason": "no_event", "event_key": ""}
    if event:
        ledger = EventLedger()
        history = ledger.delivery_history()
        budget = decide_alert_budget(event, history)
        if not budget["allowed"]:
            _write_output({
                "sent": "false",
                "delivery_status": "suppressed",
                "reason": budget["reason"],
                "event_key": budget.get("event_key", ""),
                "snapshot_id": snapshot_id,
                "release_id": gate.release_id,
            })
            return
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
    try:
        with tempfile.TemporaryDirectory(prefix="prstk-alert-card-") as temporary:
            card_alert = {
                    "title": (event or {}).get("title") or f"{slot} market briefing",
                    "lifecycle_state": (event or {}).get("lifecycle_state") or "observation",
                    "trigger_reason": caption,
                    "release_id": gate.release_id,
                    "snapshot_id": snapshot_id,
                }
            if isinstance(event, dict):
                for key in ("event", "importance", "market_transmission", "watch", "source_evidence", "market_evidence", "invalidation_condition"):
                    if event.get(key) not in (None, "", []):
                        card_alert[key] = event[key]
            photo_path = render_alert_card(
                card_alert,
                Path(temporary) / "alert.png",
            )
            deliveries = send_photo_briefs(
                token=settings.telegram_bot_token or "",
                chat_ids=settings.telegram_chat_ids,
                caption=caption,
                photo_path=photo_path,
                mini_app_url=settings.dashboard_url,
                alert_id=alert_id,
                release_id=gate.release_id or "",
                snapshot_id=snapshot_id,
                observation_id=observation_id,
            )
    except (RendererError, OSError, ValueError) as exc:
        _write_output({
            "sent": "false",
            "delivery_status": "blocked",
            "reason": "renderer_failed",
            "renderer_error_type": getattr(exc, "error_type", type(exc).__name__),
            "release_id": gate.release_id,
            "snapshot_id": snapshot_id,
        })
        return
    delivered = sum(delivery.status == "delivered" for delivery in deliveries)
    failed = len(deliveries) - delivered
    failed_recipient_hashes = [delivery.chat_id_hash for delivery in deliveries if delivery.status != "delivered"]
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
        "alert_budget": budget,
        "failed_recipient_hashes": failed_recipient_hashes,
    })
    if event:
        write_event_lock_key(event)
        ledger = EventLedger()
        ledger.record_delivery(
            {**event, "trace_id": trace_id},
            trace_id=trace_id,
            reason="scheduled_delivery",
        )
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
