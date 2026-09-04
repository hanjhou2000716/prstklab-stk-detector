"""Two-phase scheduled brief delivery: prepare, publish, then notify."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.alert_budget import decide_alert_budget
from src.alert_orchestrator import content_is_incomplete, notification_key_for_event, recipient_hash
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
from src.financialjuice_notification import deliver_financialjuice_event, financialjuice_caption
from src.financialjuice_priority import (
    project_financialjuice_priority,
    public_financialjuice_observations,
    replace_financialjuice_event_lane,
)
from src.financialjuice_release_contract import validate_financialjuice_release
from src.market_data import build_market_snapshot
from src.notification_observability import decision_summary, merge_decision_health, write_summary
from src.railway_observation_client import load_railway_observations
from src.railway_secret import delivery_shared_secret
from src.refresh_market_data import merge_published_metadata, write_snapshot
from src.release_gate import verify_release_for_delivery
from src.scheduled_brief import (
    _pick_event,
    _write_output,
    briefing_correlation,
    build_brief,
    write_event_lock_key,
)
from src.telegram_client import alert_mini_app_url, canonical_prstk_risk_level, send_text_briefs_audited

_DEFAULT_CREATOR_RECORDS_PATH = Path("creator/public-records.json")


def _write_decision_output(
    values: dict[str, Any],
    *,
    event: dict[str, Any] | None = None,
    notification_status: str = "not_attempted",
    notification_reason: str = "",
    notification_expected: bool | None = None,
    delivered_count: int | None = None,
    failed_count: int | None = None,
    last_telegram_attempt_at: str | None = None,
    last_receipt_status: str | None = None,
) -> None:
    """Write workflow outputs and a matching safe Actions summary."""
    summary = decision_summary(
        event=event,
        scan_status="completed",
        notification_expected=notification_expected if notification_expected is not None else bool(event),
        notification_status=notification_status,
        notification_reason=notification_reason,
        delivered_count=delivered_count,
        failed_count=failed_count,
        last_telegram_attempt_at=last_telegram_attempt_at,
        last_receipt_status=last_receipt_status or notification_status,
    )
    workflow_summary = {
        key: ("true" if value is True else "false" if value is False else "" if value is None else value)
        for key, value in summary.items()
    }
    _write_output({**workflow_summary, **values})
    write_summary("Scheduled brief notification decision", summary)


def _railway_observations_configured() -> bool:
    """Return whether the optional sanitized Railway ingress is configured."""
    return bool(
        os.getenv("RAILWAY_OBSERVATIONS_URL", "").strip()
        or os.getenv("RAILWAY_STATUS_URL", "").strip()
        or delivery_shared_secret()
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


def _financialjuice_delivery_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten durable FJ receipts for recipient-level replay protection.

    The general event ledger stores one delivery row per event.  FinancialJuice
    additionally needs to know which individual recipients already succeeded,
    so the FJ adapter persists a redacted ``delivery_receipts`` list inside
    that row and this boundary projects it back to the adapter's contract.
    Legacy rows without the nested list remain valid and simply have no FJ
    recipient history to replay.
    """
    flattened: list[dict[str, Any]] = []
    for row in history:
        if not isinstance(row, dict):
            continue
        receipts = row.get("delivery_receipts")
        if isinstance(receipts, list):
            for receipt in receipts:
                if not isinstance(receipt, dict):
                    continue
                flattened.append({
                    "notification_key": receipt.get("notification_key") or row.get("notification_key"),
                    "recipient_hash": receipt.get("recipient_hash") or receipt.get("chat_id_hash"),
                    "delivery_status": receipt.get("delivery_status") or receipt.get("status"),
                })
        elif row.get("notification_key") and row.get("recipient_hash"):
            flattened.append({
                "notification_key": row.get("notification_key"),
                "recipient_hash": row.get("recipient_hash"),
                "delivery_status": row.get("delivery_status") or row.get("status"),
            })
    return flattened


def _select_scheduled_candidate(
    snapshot: dict[str, Any],
    slot: str,
    ledger: EventLedger,
) -> tuple[dict[str, Any] | None, dict[str, Any], str]:
    """Select the first sendable candidate without letting one suppression starve the slot."""
    excluded: set[str] = set()
    last_reason = "no_event"
    for _ in range(32):
        try:
            event = _pick_event(snapshot, slot, excluded_event_keys=excluded)
        except TypeError:
            # Preserve compatibility with narrow test/adapter doubles that
            # implement the pre-queue two-argument selector.
            event = _pick_event(snapshot, slot)
        if not isinstance(event, dict):
            break
        identity = notification_key_for_event(event)
        if not identity:
            last_reason = "notification_key_missing"
            break
        if event.get("alert_eligible") is False:
            reasons = event.get("quality_reasons") or event.get("suppression_reasons") or []
            last_reason = str(next((item for item in reasons if str(item).strip()), "quality_gate_blocked"))
            if hasattr(ledger, "record_decision"):
                ledger.record_decision(event, {"allowed": False, "status": "suppressed", "reason": last_reason})
                ledger.save()
            excluded.add(identity)
            continue
        if hasattr(ledger, "theme_decision"):
            claim_state = getattr(ledger, "delivery_claims", {}).get(identity, {})
            claim_status = str(claim_state.get("status") or "")
            if claim_status in {"in_flight", "uncertain"}:
                last_reason = f"notification_{claim_status}"
                excluded.add(identity)
                continue
            if claim_status != "retryable":
                theme = ledger.theme_decision(event)
                ledger.save()
                if not theme.get("allowed", False):
                    last_reason = str(theme.get("reason") or "same_theme_unchanged")
                    excluded.add(identity)
                    continue
        if str(event.get("source_key") or event.get("source") or "").strip().casefold() == "financialjuice":
            text = financialjuice_caption(event)
        else:
            text = build_brief(snapshot, slot)
        if content_is_incomplete(event, text):
            last_reason = "content_incomplete"
            if hasattr(ledger, "record_decision"):
                ledger.record_decision(event, {"allowed": False, "status": "suppressed", "reason": last_reason})
                ledger.save()
            excluded.add(identity)
            continue
        budget = decide_alert_budget(event, ledger.delivery_history())
        if not budget.get("allowed", False):
            last_reason = str(budget.get("reason") or "alert_budget_suppressed")
            if hasattr(ledger, "record_decision"):
                ledger.record_decision(event, {**budget, "status": "suppressed", "reason": last_reason})
                ledger.save()
            excluded.add(identity)
            continue
        return event, budget, "candidate_ready"
    return None, {"allowed": True, "reason": last_reason, "event_key": ""}, last_reason


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
    # All sanitized external rows belong to the release-bound observation
    # lineage.  FinancialJuice rows feed the market-event lane; Creator rows
    # remain in the attributed-content lane and must not be counted as FJ
    # market evidence or shown under the FJ source-health label.  Keeping the
    # complete set on the snapshot is important: the release manifest must
    # prove that the same reviewed observations returned by Railway reached
    # Pages, not only the subset used by one classifier.
    creator_records = _load_creator_records(all_external_observations)
    financialjuice_observations = [
        row for row in all_external_observations
        if str(row.get("content_origin") or row.get("source") or "").strip().casefold() == "financialjuice"
    ]
    # Project FinancialJuice into the same release-bound event lane as other
    # public events.  The vendor score is kept separate from PRStK risk and
    # every non-send decision remains visible to Mini App/audit consumers.
    existing_events = ((snapshot.get("events") or {}).get("items") or []) if isinstance(snapshot.get("events"), dict) else []
    fj_projection = project_financialjuice_priority(
        financialjuice_observations, existing_events=existing_events, market_snapshot=snapshot,
    )
    if not isinstance(snapshot.get("events"), dict):
        snapshot["events"] = {"items": []}
    existing_events = snapshot["events"].get("items")
    snapshot["events"]["items"] = replace_financialjuice_event_lane(
        existing_events if isinstance(existing_events, list) else [],
        fj_projection["events"],
    )
    snapshot["financialjuice_priority_decisions"] = fj_projection["decisions"]
    snapshot["financialjuice_priority_events"] = [
        event for event in fj_projection["events"] if event.get("notification_status") == "eligible"
    ]
    snapshot["financialjuice_observations"] = financialjuice_observations
    # Persist the contract result in the same release snapshot and stop before
    # publication if a qualifying FJ item is no longer aligned with its
    # decision/event lineage.  This prevents a partial or hand-edited bundle
    # from reaching Pages or the Telegram gate.
    financialjuice_contract = validate_financialjuice_release(snapshot)
    snapshot["financialjuice_release_contract"] = financialjuice_contract
    if not financialjuice_contract["ok"]:
        _write_decision_output({
            "prepared": "false",
            "sent": "false",
            "reason": "financialjuice_release_contract_blocked",
            "financialjuice_contract_errors": ";".join(financialjuice_contract["errors"]),
        }, notification_status="blocked", notification_reason="financialjuice_release_contract_blocked")
        return snapshot
    remote_rejected = remote_health.get("rejected_count")
    external_rejected = local_rejected + (int(remote_rejected) if isinstance(remote_rejected, (int, str, float)) else 0)
    snapshot["external_observations"] = public_financialjuice_observations(
        all_external_observations, fj_projection["events"],
    )
    # Preserve an explicit classifier input so downstream consumers cannot
    # accidentally treat editorial Creator material as FinancialJuice market
    # evidence.  This field is derived from the same release-bound set.
    checked_at = datetime.now(UTC)
    external_health: dict[str, Any] | None
    if _railway_observations_configured():
        external_health = external_source_health_from_remote(
            remote_health,
            accepted=financialjuice_observations,
            rejected=external_rejected,
            checked_at=checked_at,
        )
    else:
        external_health = external_source_health(
            path=external_path,
            accepted=financialjuice_observations,
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
    event = _pick_event(snapshot, slot)
    prepared_decision = decision_summary(
        event=event,
        scan_status="completed",
        notification_expected=bool(event),
        notification_status="candidate_ready" if event else "no_event",
        notification_reason="candidate_ready" if event else "no_event",
    )
    snapshot["source_health"] = merge_decision_health(
        snapshot.get("source_health"), "scheduled_brief", prepared_decision,
    )
    if not write_snapshot(snapshot, snapshot_path):
        _write_decision_output(
            {"prepared": "false", "sent": "false", "reason": "snapshot_publish_skipped"},
            event=event, notification_status="blocked", notification_reason="snapshot_publish_skipped",
        )
        return snapshot
    correlation = briefing_correlation(snapshot, slot, event)
    metadata: dict[str, object] = {
        "trace_id": correlation["trace_id"],
        "snapshot_id": correlation["snapshot_id"],
        "observation_id": correlation["observation_id"],
    }
    snapshot.setdefault("briefing", {}).update(metadata)
    if not merge_published_metadata(metadata, destination=snapshot_path, expected_snapshot_id=correlation["snapshot_id"]):
        _write_decision_output(
            {"prepared": "false", "sent": "false", "reason": "snapshot_metadata_merge_skipped"},
            event=event, notification_status="blocked", notification_reason="snapshot_metadata_merge_skipped",
        )
        return snapshot
    _write_decision_output(
        {"prepared": "true", **metadata},
        event=event,
        notification_status=prepared_decision["notification_status"],
        notification_reason=prepared_decision["notification_reason"],
    )
    return snapshot


def send(
    snapshot_path: Path,
    slot: str,
    manifest_path: Path,
    public_url: str | None = None,
    *,
    require_production_research: bool = False,
    slot_key: str | None = None,
    run_id: str | None = None,
) -> None:
    """Send only after local and deployed release manifests agree."""
    try:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _write_decision_output(
            {"sent": "false", "delivery_status": "blocked", "reason": f"snapshot_unreadable:{type(exc).__name__}"},
            notification_status="blocked", notification_reason=f"snapshot_unreadable:{type(exc).__name__}",
        )
        return
    if not isinstance(snapshot, dict):
        _write_decision_output(
            {"sent": "false", "delivery_status": "blocked", "reason": "snapshot_not_object"},
            notification_status="blocked", notification_reason="snapshot_not_object",
        )
        return
    snapshot_id = str(snapshot.get("snapshot_id") or "")
    gate = verify_release_for_delivery(
        manifest_path=manifest_path,
        expected_snapshot_id=snapshot_id,
        public_url=public_url,
        require_production_research=require_production_research,
    )
    if not gate.allowed:
        _write_decision_output({
            "sent": "false",
            "delivery_status": "blocked",
            "reason": "release_gate_blocked",
            "release_id": gate.release_id,
            "snapshot_id": snapshot_id,
            "release_gate_errors": ";".join(gate.errors),
            "notification_expected": "false",
            "notification_status": "blocked",
            "notification_reason": "release_gate_blocked",
        }, notification_status="blocked", notification_reason="release_gate_blocked")
        print("Release gate blocked Telegram delivery: " + "; ".join(gate.errors))
        return

    settings = get_settings()
    if not settings.telegram_ready:
        raise RuntimeError("Telegram configuration is incomplete")
    ledger = EventLedger()
    history = ledger.delivery_history()
    event, budget, selection_reason = _select_scheduled_candidate(snapshot, slot, ledger)
    event_risk = canonical_prstk_risk_level(event) if isinstance(event, dict) else ""
    effective_slot_key = str(slot_key or os.getenv("SCHEDULED_SLOT_KEY") or f"{datetime.now().astimezone().date().isoformat()}-{slot}")
    effective_run_id = str(run_id or os.getenv("GITHUB_RUN_ID", ""))
    notification_key = notification_key_for_event(event, slot_key=effective_slot_key)
    send_chat_ids = settings.telegram_chat_ids
    if event is None:
        if selection_reason != "no_event":
            _write_decision_output(
                {
                    "sent": "false",
                    "delivery_status": "suppressed",
                    "reason": selection_reason,
                    "notification_status": "suppressed",
                    "notification_reason": selection_reason,
                },
                notification_status="suppressed",
                notification_reason=selection_reason,
            )
            return
        notification_key = notification_key_for_event(None, slot_key=effective_slot_key)
        budget = {"allowed": True, "reason": selection_reason or "no_event", "event_key": notification_key}
    if not notification_key:
        _write_decision_output({"sent": "false", "delivery_status": "suppressed", "reason": "notification_key_missing"}, notification_status="suppressed", notification_reason="notification_key_missing")
        return
    briefing = snapshot.get("briefing") or {}
    correlation = briefing_correlation(snapshot, slot, event)
    trace_id = str(briefing.get("trace_id") or correlation["trace_id"])
    observation_id = str(briefing.get("observation_id") or correlation["observation_id"])
    caption = build_brief(snapshot, slot) if event else "市場簡報｜本輪無觸發"
    alert_id = str(
        (event or {}).get("notification_id")
        or (event or {}).get("event_cluster_key")
        or (event or {}).get("event_key")
        or notification_key
        or trace_id
    )
    target_url = (
        alert_mini_app_url(
            settings.dashboard_url,
            alert_id=alert_id,
            release_id=gate.release_id or "",
            snapshot_id=snapshot_id,
            observation_id=observation_id,
        )
        if event else alert_mini_app_url(
            settings.dashboard_url,
            alert_id=alert_id,
            release_id=gate.release_id or "",
            snapshot_id=snapshot_id,
            observation_id=observation_id,
        )
    )
    if event is None:
        claim = (
            ledger.claim_notification(
                notification_key,
                slot_key=effective_slot_key,
                recipient_hashes=tuple(recipient_hash(chat_id) for chat_id in settings.telegram_chat_ids),
                run_id=effective_run_id,
            )
            if hasattr(ledger, "claim_notification") else {"status": "claimed"}
        )
        if claim.get("status") != "claimed":
            _write_decision_output(
                {"sent": "false", "delivery_status": "suppressed", "reason": f"scheduled_slot_{claim.get('status', 'blocked')}", "notification_key": notification_key},
                notification_status="suppressed", notification_reason=f"scheduled_slot_{claim.get('status', 'blocked')}", last_receipt_status=str(claim.get("status") or "blocked"),
            )
            return
        pending_hashes = set(str(item) for item in claim.get("pending_recipient_hashes") or [])
        if pending_hashes:
            send_chat_ids = tuple(
                chat_id for chat_id in settings.telegram_chat_ids if recipient_hash(chat_id) in pending_hashes
            )
    elif str(event.get("source_key") or event.get("source") or "").strip().casefold() != "financialjuice":
        claim = (
            ledger.claim_notification(
                notification_key,
                slot_key=effective_slot_key,
                recipient_hashes=tuple(recipient_hash(chat_id) for chat_id in settings.telegram_chat_ids),
                run_id=effective_run_id,
            )
            if hasattr(ledger, "claim_notification") else {"status": "claimed"}
        )
        if claim.get("status") != "claimed":
            _write_decision_output(
                {"sent": "false", "delivery_status": "suppressed", "reason": f"notification_{claim.get('status', 'blocked')}", "notification_key": notification_key},
                event=event, notification_status="suppressed", notification_reason=f"notification_{claim.get('status', 'blocked')}", last_receipt_status=str(claim.get("status") or "blocked"),
            )
            return
        pending_hashes = set(str(item) for item in claim.get("pending_recipient_hashes") or [])
        if pending_hashes:
            send_chat_ids = tuple(
                chat_id for chat_id in settings.telegram_chat_ids if recipient_hash(chat_id) in pending_hashes
            )
    telegram_attempted_at = datetime.now().astimezone().isoformat()
    fj_delivery: dict[str, Any] | None = None
    deliveries: tuple[Any, ...] = ()
    try:
        if isinstance(event, dict) and str(event.get("source_key") or "").strip().casefold() == "financialjuice":
            fj_delivery = deliver_financialjuice_event(
                event,
                release_id=gate.release_id or "",
                snapshot_id=snapshot_id,
                mini_app_url=settings.dashboard_url,
                release_ready=True,
                token=settings.telegram_bot_token or "",
                chat_ids=send_chat_ids,
                delivery_history=_financialjuice_delivery_history(history),
                text_sender=send_text_briefs_audited,
                ledger=ledger,
                slot_key=effective_slot_key,
                run_id=effective_run_id,
            )
        else:
            deliveries = send_text_briefs_audited(
                token=settings.telegram_bot_token or "",
                chat_ids=send_chat_ids,
                text=caption,
                dashboard_url=settings.dashboard_url,
                alert_id=alert_id,
                release_id=gate.release_id or "",
                snapshot_id=snapshot_id,
                observation_id=observation_id,
                target_url=target_url,
                prstk_risk_level=canonical_prstk_risk_level(event),
            )
    except (OSError, ValueError) as exc:
        if event is None or str(event.get("source_key") or event.get("source") or "").strip().casefold() != "financialjuice":
            ledger.complete_notification_claim(notification_key, uncertain=True)
        _write_decision_output(
            {"sent": "false", "delivery_status": "blocked", "reason": "text_delivery_failed", "error_type": type(exc).__name__, "release_id": gate.release_id, "snapshot_id": snapshot_id, "trace_id": trace_id, "risk": event_risk},
            event=event, notification_status="failed", notification_reason="text_delivery_failed",
        )
        return
    if fj_delivery is not None:
        fj_receipts = [row for row in fj_delivery.get("receipts", []) if isinstance(row, dict)]
        delivered = sum(str(row.get("delivery_status") or "") == "delivered" for row in fj_receipts)
        failed = len(fj_receipts) - delivered
        fj_status = str(fj_delivery.get("status") or "failed")
        if fj_status == "already_delivered":
            # The FJ event was already delivered by the immediate lane.  The
            # scheduled slot still owns one public message, so continue with
            # the slot-scoped market brief instead of re-sending FJ or leaving
            # the slot silent.
            fallback_key = notification_key_for_event(None, slot_key=effective_slot_key)
            fallback_claim = ledger.claim_notification(
                fallback_key,
                slot_key=effective_slot_key,
                recipient_hashes=tuple(recipient_hash(chat_id) for chat_id in settings.telegram_chat_ids),
                run_id=effective_run_id,
            ) if hasattr(ledger, "claim_notification") else {"status": "claimed"}
            if fallback_claim.get("status") != "claimed":
                _write_decision_output({
                    "sent": "false",
                    "delivery_status": "suppressed",
                    "reason": f"scheduled_slot_{fallback_claim.get('status', 'blocked')}",
                    "notification_key": fallback_key,
                    "release_id": gate.release_id,
                    "snapshot_id": snapshot_id,
                    "trace_id": trace_id,
                    "notification_expected": "true",
                    "notification_status": "suppressed",
                    "notification_reason": f"scheduled_slot_{fallback_claim.get('status', 'blocked')}",
                    "risk": event_risk,
                }, event=None, notification_status="suppressed", notification_reason=f"scheduled_slot_{fallback_claim.get('status', 'blocked')}", last_receipt_status=str(fallback_claim.get("status") or "blocked"))
                return
            pending_hashes = set(str(item) for item in fallback_claim.get("pending_recipient_hashes") or [])
            fallback_chat_ids = tuple(
                chat_id for chat_id in settings.telegram_chat_ids
                if not pending_hashes or recipient_hash(chat_id) in pending_hashes
            )
            fallback_url = alert_mini_app_url(
                settings.dashboard_url,
                alert_id=fallback_key,
                release_id=gate.release_id or "",
                snapshot_id=snapshot_id,
                observation_id=observation_id,
            )
            fallback_attempt_at = datetime.now().astimezone().isoformat()
            try:
                fallback_deliveries = send_text_briefs_audited(
                    token=settings.telegram_bot_token or "",
                    chat_ids=fallback_chat_ids,
                    text="市場簡報｜本輪無觸發",
                    dashboard_url=settings.dashboard_url,
                    alert_id=fallback_key,
                    release_id=gate.release_id or "",
                    snapshot_id=snapshot_id,
                    observation_id=observation_id,
                    target_url=fallback_url,
                    prstk_risk_level="",
                )
            except (OSError, ValueError) as exc:
                ledger.complete_notification_claim(fallback_key, uncertain=True)
                _write_decision_output({
                    "sent": "false",
                    "delivery_status": "blocked",
                    "reason": "text_delivery_failed",
                    "error_type": type(exc).__name__,
                    "release_id": gate.release_id,
                    "snapshot_id": snapshot_id,
                    "trace_id": trace_id,
                    "alert_id": fallback_key,
                    "notification_key": fallback_key,
                }, event=None, notification_status="failed", notification_reason="text_delivery_failed")
                return
            fallback_delivered = sum(delivery.status == "delivered" for delivery in fallback_deliveries)
            fallback_failed = len(fallback_deliveries) - fallback_delivered
            ledger.complete_notification_claim(
                fallback_key,
                delivered_recipient_hashes=tuple(delivery.chat_id_hash for delivery in fallback_deliveries if delivery.status == "delivered"),
                failed_recipient_hashes=tuple(delivery.chat_id_hash for delivery in fallback_deliveries if delivery.status != "delivered"),
            )
            fallback_status = "delivered" if not fallback_failed else "partial" if fallback_delivered else "failed"
            _write_decision_output({
                "sent": "true",
                "reason": "scheduled_brief_after_financialjuice",
                "notification_key": fallback_key,
                "release_id": gate.release_id,
                "snapshot_id": snapshot_id,
                "trace_id": trace_id,
                "alert_id": fallback_key,
                "delivery_mode": "text",
                "delivery_status": fallback_status,
                "delivered_count": fallback_delivered,
                "failed_count": fallback_failed,
                "failed_recipient_hashes": ",".join(
                    delivery.chat_id_hash for delivery in fallback_deliveries if delivery.status != "delivered"
                ),
                "notification_expected": "true",
                "notification_status": "ready" if fallback_status == "delivered" else fallback_status,
                "notification_reason": "scheduled_brief_after_financialjuice",
                "risk": "",
            }, event=None, notification_status="ready" if fallback_status == "delivered" else fallback_status, notification_reason="scheduled_brief_after_financialjuice", notification_expected=True, delivered_count=fallback_delivered, failed_count=fallback_failed, last_telegram_attempt_at=fallback_attempt_at, last_receipt_status=fallback_status)
            ledger.record_delivery(
                {
                    "source_key": "scheduled_brief",
                    "event_type": "scheduled_brief",
                    "event_key": fallback_key,
                    "notification_key": fallback_key,
                    "notification_theme_key": f"scheduled:{effective_slot_key}",
                    "title": "市場簡報｜本輪無觸發",
                    "trace_id": trace_id,
                    "release_id": gate.release_id,
                    "snapshot_id": snapshot_id,
                    "delivery_status": fallback_status,
                },
                trace_id=trace_id,
                reason="scheduled_delivery_after_financialjuice",
            )
            ledger.save()
            return
        if fj_status == "blocked" and not fj_receipts:
            _write_decision_output({
                "sent": "false",
                "delivery_status": "blocked",
                "reason": "financialjuice_delivery_blocked",
                "notification_key": fj_delivery.get("notification_key", ""),
                "delivery_reasons": ";".join(str(item) for item in (fj_delivery.get("reasons") or [])),
                "release_id": gate.release_id,
                "snapshot_id": snapshot_id,
                "trace_id": trace_id,
                "notification_expected": "false",
                "notification_status": "blocked",
                "notification_reason": "financialjuice_delivery_blocked",
                "risk": event_risk,
            }, event=event, notification_status="blocked", notification_reason="financialjuice_delivery_blocked")
            return
        delivery_status = "delivered" if fj_status == "delivered" else "partial" if delivered else "failed"
        failed_recipient_hashes = [
            str(row.get("recipient_hash") or row.get("chat_id_hash") or "")
            for row in fj_receipts
            if str(row.get("delivery_status") or "") != "delivered"
        ]
        if not delivered:
            failure_classes = sorted({
                str(row.get("error_class") or "").strip()
                for row in fj_receipts
                if str(row.get("error_class") or "").strip()
            })
            failure_reason = "recipient_delivery_failed"
            if failure_classes:
                failure_reason = f"{failure_reason}:{','.join(failure_classes)}"
            _write_decision_output({
                "sent": "false",
                "delivery_status": "failed",
                "reason": "all_recipients_failed",
                "failure_classes": ",".join(failure_classes),
                "release_id": gate.release_id,
                "snapshot_id": snapshot_id,
                "alert_id": alert_id,
                "trace_id": trace_id,
                "delivered_count": 0,
                "failed_count": max(failed, len(settings.telegram_chat_ids)),
                # This value is written to GITHUB_OUTPUT, where a JSON list
                # would become the literal string ``[]`` and be misread by
                # the receipt callback as one failed recipient hash.
                "failed_recipient_hashes": ",".join(failed_recipient_hashes),
                "notification_expected": "true",
                "notification_status": "failed",
                "notification_reason": failure_reason,
                "risk": event_risk,
            }, event=event, notification_status="failed", notification_reason=failure_reason, delivered_count=0, failed_count=max(failed, len(settings.telegram_chat_ids)), last_receipt_status="failed")
            raise RuntimeError("Telegram FinancialJuice delivery failed for every configured recipient")
    else:
        delivered = sum(delivery.status == "delivered" for delivery in deliveries)
        failed = len(deliveries) - delivered
        delivery_status = "delivered" if not failed else "partial" if delivered else "failed"
        failed_recipient_hashes = [delivery.chat_id_hash for delivery in deliveries if delivery.status != "delivered"]
        if hasattr(ledger, "complete_notification_claim"):
            ledger.complete_notification_claim(
                notification_key,
                delivered_recipient_hashes=tuple(delivery.chat_id_hash for delivery in deliveries if delivery.status == "delivered"),
                failed_recipient_hashes=tuple(delivery.chat_id_hash for delivery in deliveries if delivery.status != "delivered"),
            )
    output: dict[str, Any] = {
        "sent": "true",
        "reason": "sent_partial" if failed else "sent",
        "release_id": gate.release_id,
        "trace_id": trace_id,
        "snapshot_id": snapshot_id,
        "observation_id": observation_id,
        "delivery_status": delivery_status,
        "delivered_count": delivered,
        "failed_count": failed,
        "delivery_mode": "text",
        "alert_id": alert_id,
        "alert_budget": budget,
        # Keep the workflow output comma-delimited; the callback turns it
        # back into a bounded list and an empty value remains a true empty
        # list for delivered=1/failed=0 receipts.
        "failed_recipient_hashes": ",".join(failed_recipient_hashes),
        "notification_expected": "true",
        "notification_status": ("ready" if delivery_status == "delivered" else delivery_status),
        "notification_reason": ("sent" if delivery_status == "delivered" else "recipient_delivery_partial" if delivery_status == "partial" else "recipient_delivery_failed") if event else "no_trigger",
        "event_key": alert_id,
        "risk": event_risk,
    }
    if isinstance(event, dict) and str(event.get("source_key") or "").strip().casefold() == "financialjuice":
        output["financialjuice_delivery_trace"] = {
            "observation_id_hash": event.get("observation_id_hash"),
            "item_id": event.get("item_id"),
            "event_cluster_key": event.get("event_cluster_key"),
            "vendor_importance": event.get("vendor_importance"),
            "prstk_risk": event.get("prstk_risk"),
            "notification_reason": event.get("notification_reason"),
            "release_id": gate.release_id,
            "snapshot_id": snapshot_id,
            "delivery_status": delivery_status,
            "notification_key": fj_delivery.get("notification_key") if fj_delivery else None,
            "delivery_reasons": fj_delivery.get("reasons", []) if fj_delivery else [],
        }
    _write_decision_output(
        output,
        event=event,
        notification_status=output["notification_status"],
        notification_reason=output["notification_reason"],
        notification_expected=True,
        delivered_count=delivered,
        failed_count=failed,
        last_telegram_attempt_at=telegram_attempted_at,
        last_receipt_status=delivery_status,
    )
    if event:
        write_event_lock_key(event)
        if ledger is None:
            ledger = EventLedger()
        ledger_event = {
            **event,
            "trace_id": trace_id,
            "release_id": gate.release_id,
            "snapshot_id": snapshot_id,
            "delivery_status": delivery_status,
            "notification_key": notification_key,
        }
        if fj_delivery is not None:
            ledger_event["notification_key"] = fj_delivery.get("notification_key")
            ledger_event["delivery_receipts"] = fj_delivery.get("receipts", [])
        ledger.record_delivery(
            ledger_event,
            trace_id=trace_id,
            reason="scheduled_delivery",
        )
        ledger.save()
    else:
        ledger.record_delivery(
            {
                "source_key": "scheduled_brief",
                "event_type": "scheduled_brief",
                "event_key": notification_key,
                "notification_key": notification_key,
                "notification_theme_key": f"scheduled:{effective_slot_key}",
                "title": "市場簡報｜本輪無觸發",
                "trace_id": trace_id,
                "release_id": gate.release_id,
                "snapshot_id": snapshot_id,
                "delivery_status": delivery_status,
            },
            trace_id=trace_id,
            reason="scheduled_delivery_no_event",
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
    parser.add_argument("--slot-key", default=None)
    parser.add_argument(
        "--require-production-research",
        action="store_true",
        help="require a fresh production research artifact for research-only delivery",
    )
    args = parser.parse_args()
    if args.prepare_only == args.send_only:
        parser.error("choose exactly one of --prepare-only or --send-only")
    if args.prepare_only:
        prepare(args.slot, args.snapshot)
    else:
        send(
            args.snapshot,
            args.slot,
            args.manifest,
            args.public_url,
            require_production_research=args.require_production_research,
            slot_key=args.slot_key,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
