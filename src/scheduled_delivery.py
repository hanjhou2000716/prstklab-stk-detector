"""Two-phase scheduled brief delivery: prepare, publish, then notify."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from src.alert_budget import decide_alert_budget
from src.alert_orchestrator import content_is_incomplete, notification_key_for_event, recipient_hash
from src.briefing_cards import build_briefing_snapshot
from src.config import get_settings
from src.creator_provider_registry import creator_ids
from src.event_ledger import EventLedger, event_source_url
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
    anchor_key,
    briefing_correlation,
    build_brief,
    write_event_lock_key,
)
from src.telegram_client import (
    alert_mini_app_url,
    canonical_prstk_risk_level,
    is_valid_public_summary,
    send_text_briefs_audited,
)

_DEFAULT_CREATOR_RECORDS_PATH = Path("creator/public-records.json")


def _briefing_evidence_ready(briefing: dict[str, Any]) -> bool:
    """Require scheduled Telegram briefs to meet the market evidence floor."""
    assessment = briefing.get("market_assessment")
    if not isinstance(assessment, dict):
        return False
    if str(assessment.get("confidence") or "").casefold() == "low":
        return False
    try:
        factor_count = int(assessment.get("factor_count") or 0)
    except (TypeError, ValueError):
        factor_count = 0
    dimensions = assessment.get("evidence_dimensions")
    return factor_count >= 3 and isinstance(dimensions, list) and len(dimensions) >= 2


def _briefing_delivery_event(snapshot: dict[str, Any], slot: str) -> dict[str, Any] | None:
    """Project the shared digest into the existing notification contract."""
    briefing = snapshot.get("briefing")
    if (
        not isinstance(briefing, dict)
        or briefing.get("notification_eligible") is not True
        or not _briefing_evidence_ready(briefing)
    ):
        return None
    public_message = str(briefing.get("public_short_message") or "").strip()
    briefing_id = str(briefing.get("briefing_id") or "").strip()
    if not public_message or not briefing_id:
        return None
    primary = briefing.get("primary_theme")
    if not isinstance(primary, dict):
        themes = briefing.get("themes")
        primary = themes[0] if isinstance(themes, list) and themes and isinstance(themes[0], dict) else {}
    assessment_value = briefing.get("market_assessment")
    assessment: dict[str, Any] = assessment_value if isinstance(assessment_value, dict) else {}
    return {
        "kind": "market_briefing",
        "source_key": "scheduled_brief",
        "source": "PRStK 多來源市場判讀",
        "notification_id": briefing_id,
        "alert_id": briefing_id,
        "event_cluster_key": briefing_id,
        "observation_id": briefing.get("observation_id"),
        "public_short_message": public_message,
        "brief_title": public_message,
        "title": public_message,
        "event": primary.get("what_happened") or briefing.get("assessment_summary") or briefing.get("overview") or public_message,
        "why_important": primary.get("why_important"),
        "possible_linkage": primary.get("market_implication"),
        "stock_observation": primary.get("stock_observation"),
        "market_evidence": primary.get("quote_evidence") or briefing.get("quote_evidence") or [],
        "source_evidence": primary.get("source_evidence") or briefing.get("source_evidence") or [],
        "canonical_event_key": primary.get("canonical_event_key"),
        "briefing": briefing,
        "notification_status": "eligible",
        "alert_eligible": True,
        "slot": slot,
        "alert_lane": "scheduled_brief",
        "anchor_key": anchor_key(
            slot,
            str(((briefing.get("slot_context") or {}).get("slot_date") if isinstance(briefing.get("slot_context"), dict) else "") or datetime.now().astimezone().date().isoformat()),
        ),
        "notification_key": briefing.get("notification_key"),
        "decision_fingerprint": briefing.get("decision_fingerprint"),
        "evidence_fingerprint": briefing.get("evidence_fingerprint"),
        "market_scope": assessment.get("market_scope"),
        "material_changes": briefing.get("material_changes") or [],
        "delivery_eligible": briefing.get("delivery_eligible", True),
        "suppression_reason": briefing.get("suppression_reason") or "",
    }


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
        if provider not in creator_ids(enabled_only=True):
            continue
        key = str(row.get("episode_key") or row.get("observation_id") or "").strip()
        if not key or key in seen or str(row.get("parse_status") or "normalized").casefold() in {"parse_failed", "unsupported_template", "invalid_source", "duplicate", "retired_source_suppressed"}:
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
    blocked_states = {"parse_failed", "unsupported_template", "invalid_source", "duplicate", "retired_source_suppressed"}
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
                provider = str(item.get("content_origin") or item.get("source") or "").strip().casefold()
                if provider not in creator_ids(enabled_only=True):
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
        return {provider: "creator_records_unavailable" for provider in creator_ids(enabled_only=True)}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {provider: "creator_records_parse_failed" for provider in creator_ids(enabled_only=True)}
    if isinstance(payload, dict):
        payload = payload.get("records")
    if not isinstance(payload, list):
        return {provider: "creator_records_invalid_shape" for provider in creator_ids(enabled_only=True)}
    blocked_states = {"parse_failed", "unsupported_template", "invalid_source", "duplicate"}
    private_fields = {"body", "raw_body", "local_path", "private_url", "attachments", "data"}
    failures: dict[str, str] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        provider = str(item.get("content_origin") or item.get("source") or "").strip().lower()
        if provider not in creator_ids(enabled_only=True):
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
    *,
    release_alert_ids: set[str] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any], str]:
    """Select the first sendable candidate without letting one suppression starve the slot."""
    excluded: set[str] = set()
    last_reason = "no_eligible_candidate"
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
            identity = str(
                event.get("notification_id")
                or event.get("event_key")
                or event.get("item_id")
                or event.get("observation_id")
                or f"invalid-{len(excluded)}"
            ).strip()
            excluded.add(identity)
            continue
        if release_alert_ids is not None:
            alert_id = str(
                event.get("notification_id")
                or event.get("alert_id")
                or event.get("event_cluster_key")
                or event.get("event_key")
                or event.get("item_id")
                or ""
            ).strip()
            if not alert_id or alert_id not in release_alert_ids:
                last_reason = "alert_artifact_missing"
                if hasattr(ledger, "record_decision"):
                    ledger.record_decision(event, {
                        "allowed": False, "status": "suppressed", "reason": last_reason,
                    })
                    ledger.save()
                excluded.add(identity)
                continue
        if event.get("alert_eligible") is False:
            reasons = event.get("quality_reasons") or event.get("suppression_reasons") or event.get("notification_reasons") or []
            last_reason = str(next((item for item in reasons if str(item).strip()), "quality_gate_blocked"))
            if hasattr(ledger, "record_decision"):
                ledger.record_decision(event, {"allowed": False, "status": "suppressed", "reason": last_reason})
                ledger.save()
            excluded.add(identity)
            continue
        if hasattr(ledger, "theme_decision"):
            claim_state = getattr(ledger, "delivery_claims", {}).get(identity, {})
            claim_status = str(claim_state.get("status") or "")
            if claim_status == "delivered":
                last_reason = "already_delivered"
                excluded.add(identity)
                continue
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
        source = str(event.get("source_key") or event.get("source") or "").strip().casefold()
        if source == "financialjuice" and (
            str(event.get("notification_status") or "") != "eligible"
            or event.get("vendor_priority_notification") is not True
        ):
            last_reason = "vendor_priority_not_eligible"
            if hasattr(ledger, "record_decision"):
                ledger.record_decision(event, {"allowed": False, "status": "suppressed", "reason": last_reason})
                ledger.save()
            excluded.add(identity)
            continue
        if source == "financialjuice":
            text = financialjuice_caption(event)
        else:
            text = build_brief(snapshot, slot)
        if content_is_incomplete(event, text) or (
            source == "financialjuice" and not is_valid_public_summary(text, source="financialjuice")
        ):
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


def _release_alert_ids(manifest_path: Path, manifest: dict[str, Any]) -> set[str] | None:
    """Return alert identities proven present in the release-bound index."""
    paths = manifest.get("artifact_paths")
    index_name = "alert-index.json"
    relative = paths.get(index_name) if isinstance(paths, dict) else None
    if not isinstance(relative, str) or not relative.strip():
        # Minimal adapter doubles and releases without event artifacts do not
        # advertise an alert index.  The real release gate always includes it
        # whenever event delivery is possible.
        return None
    site_root = manifest_path.parent.parent if manifest_path.parent.name == "data" else manifest_path.parent
    path = site_root / relative
    try:
        index = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return set()
    if not isinstance(index, dict) or not isinstance(index.get("alerts"), list):
        return set()
    release_id = str(manifest.get("release_id") or "")
    snapshot_id = str(manifest.get("market_snapshot_id") or "")
    return {
        str(row.get("notification_id") or "").strip()
        for row in index["alerts"]
        if isinstance(row, dict)
        and str(row.get("release_id") or "") == release_id
        and str(row.get("snapshot_id") or snapshot_id) == snapshot_id
        and str(row.get("notification_id") or "").strip()
    }


def _closed_market_slot_context(
    snapshot: dict[str, Any], slot: str, context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Suppress routine non-morning anchors on exchange holidays.

    The clock still determines the report label on a closed day, but only the
    06:00 morning anchor is a routine delivery.  This check is intentionally
    applied after the market snapshot is built so the Pages artifact retains
    the closed-day evidence and the delivery decision remains auditable.
    """
    if not isinstance(context, dict) or str(context.get("delivery_intent") or "").strip() != "notify_candidate":
        return context
    market_key = "us" if slot == "us_premarket" else "taiwan" if slot in {"pre_open", "post_close"} else ""
    if not market_key:
        return context
    markets = snapshot.get("markets")
    status = markets.get(market_key) if isinstance(markets, dict) else None
    slot_date = str(context.get("slot_date") or "").strip()
    weekend = False
    try:
        weekend = datetime.fromisoformat(slot_date).date().weekday() >= 5
    except ValueError:
        pass
    if not weekend and (not isinstance(status, dict) or status.get("is_trading_day") is not False):
        return context
    return {
        **context,
        "delivery_intent": "publish_only",
        "suppression_reason": "closed_market_publish_only",
        "resolution_reason": "closed_market_publish_only",
    }


def _load_schedule_decision_history(snapshot_path: Path) -> list[dict[str, Any]]:
    """Load only the bounded, public decision trail from the prior release."""
    try:
        previous = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    rows = previous.get("scheduled_decision_history") if isinstance(previous, dict) else None
    if not isinstance(rows, list):
        return []
    return [dict(row) for row in rows[-7:] if isinstance(row, dict)]


def _schedule_decision_category(
    context: dict[str, Any] | None,
    *,
    briefing: dict[str, Any],
    decision_event: dict[str, Any] | None,
    delivery_eligible: bool,
    comparison_reason: str,
    notification_requested: bool | None = None,
) -> tuple[str, str]:
    """Map a run to an auditable operational outcome."""
    ctx = context or {}
    contract_status = str(ctx.get("contract_status") or "").strip()
    if contract_status == "invalid":
        reason = str(ctx.get("resolution_reason") or "invalid_schedule_context")
        return "contract_error", reason
    context_suppression = str(ctx.get("suppression_reason") or "").strip()
    context_reason = context_suppression
    if (
        not context_reason
        and str(ctx.get("delivery_intent") or "").strip() != "notify_candidate"
    ):
        context_reason = str(ctx.get("resolution_reason") or "").strip()
    if notification_requested is False and not context_suppression and (
        str(ctx.get("delivery_intent") or "notify_candidate").strip()
        == "notify_candidate"
    ):
        return "not_requested", "manual_notification_opt_in_required"
    reason = str(
        ctx.get("suppression_reason")
        or comparison_reason
        or briefing.get("notification_reason")
        or ""
    ).strip()
    if reason.startswith("closed_market"):
        return "market_closed", reason
    if reason.startswith("late_schedule") or reason.startswith("late_dispatch"):
        return "late_schedule", reason
    if reason in {"insufficient_market_evidence", "data_insufficient", "no_eligible_candidate"}:
        return "data_insufficient", reason
    if delivery_eligible and decision_event is not None:
        return "notification_candidate", "candidate_ready"
    if reason in {"same_decision_unchanged", "anchor_already_delivered", "no_material_change"}:
        return "no_material_change", reason
    if not decision_event:
        return "data_insufficient", reason or "no_eligible_candidate"
    return "suppressed", reason or "notification_not_eligible"


def _attach_schedule_decision(
    snapshot: dict[str, Any],
    *,
    snapshot_path: Path,
    slot: str,
    context: dict[str, Any] | None,
    production_started_at: str,
    completed_at: str,
    decision_event: dict[str, Any] | None,
    briefing: dict[str, Any],
    comparison_notification_key: str = "",
    material_changes: list[Any] | None = None,
    delivery_eligible: bool = False,
    comparison_reason: str = "",
    production_status: str = "ready",
    notification_requested: bool | None = None,
) -> dict[str, Any]:
    """Persist the latest anchor production/notification decision in Pages."""
    ctx = context if isinstance(context, dict) else {}
    status, reason = _schedule_decision_category(
        ctx,
        briefing=briefing,
        decision_event=decision_event,
        delivery_eligible=delivery_eligible,
        comparison_reason=comparison_reason,
        notification_requested=notification_requested,
    )
    row: dict[str, Any] = {
        "anchor_key": anchor_key(
            str(ctx.get("effective_slot") or slot),
            str(ctx.get("slot_date") or datetime.now().astimezone().date().isoformat()),
        ),
        "scheduled_slot": str(ctx.get("scheduled_slot") or slot),
        "effective_market_phase": str(ctx.get("effective_market_phase") or ctx.get("effective_slot") or slot),
        "slot_date": str(ctx.get("slot_date") or ""),
        "scheduled_for_at": str(ctx.get("scheduled_for_at") or ""),
        "dispatch_unix": str(ctx.get("dispatch_unix") or ""),
        "dispatch_trace_id": str(ctx.get("dispatch_trace_id") or ""),
        "arrival_at": str(ctx.get("arrival_at") or ctx.get("run_started_at") or ""),
        "run_started_at": str(ctx.get("run_started_at") or production_started_at),
        "production_started_at": production_started_at,
        "completed_at": completed_at,
        "delay_seconds": int(str(ctx.get("delay_seconds") or "0")),
        "trigger_kind": str(ctx.get("trigger_kind") or "unknown"),
        "schedule_contract_version": str(ctx.get("schedule_contract_version") or ""),
        "time_zone": str(ctx.get("time_zone") or ""),
        "contract_status": str(ctx.get("contract_status") or "unknown"),
        "production_status": production_status,
        "comparison_notification_key": comparison_notification_key,
        "material_changes": list(material_changes or []),
        "delivery_eligible": bool(delivery_eligible),
        "notification_requested": notification_requested,
        "notification_status": status,
        "suppression_reason": reason if status != "notification_candidate" else "",
        "decision_fingerprint": str(briefing.get("decision_fingerprint") or ""),
        "evidence_fingerprint": str(briefing.get("evidence_fingerprint") or ""),
    }
    history = [*_load_schedule_decision_history(snapshot_path), row]
    history = history[-8:]
    snapshot["scheduled_decision_history"] = history
    morning = snapshot.get("briefing", {}).get("morning_analysis")
    if isinstance(morning, dict):
        system = morning.get("system_analysis")
        if not isinstance(system, dict):
            system = {}
            morning["system_analysis"] = system
        system["schedule_decisions"] = history
    snapshot.setdefault("briefing", {})["schedule_decision"] = row
    return row


def prepare(
    slot: str,
    snapshot_path: Path,
    *,
    slot_context: dict[str, Any] | None = None,
    notification_requested: bool | None = None,
) -> dict:
    """Create the exact snapshot that will later be deployed and delivered."""
    production_started_at = datetime.now(UTC).isoformat()
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
            providers=creator_ids(enabled_only=True),
        )
        snapshot["source_health"] = merge_creator_sources(snapshot.get("source_health") or {}, creator_rows)
        snapshot["creator_source_health"] = creator_rows
    if creator_records:
        snapshot["creator_insights"] = creator_records
    snapshot["briefing"] = build_briefing_snapshot(snapshot, slot)
    effective_context = _closed_market_slot_context(snapshot, slot, slot_context)
    if isinstance(effective_context, dict):
        snapshot["briefing"]["slot_context"] = effective_context
        if str(effective_context.get("delivery_intent") or "").strip() != "notify_candidate":
            # Keep the full briefing visible on Pages, but do not manufacture
            # an immutable alert artifact for a publish-only refresh.
            snapshot["briefing"]["notification_eligible"] = False
            snapshot["briefing"]["status"] = "suppressed"
            snapshot["briefing"]["notification_reason"] = str(
                effective_context.get("suppression_reason")
                or effective_context.get("resolution_reason")
                or "delivery_intent_not_notify"
            )
    if (
        notification_requested is False
        and isinstance(snapshot.get("briefing"), dict)
        and not str(
            (effective_context or {}).get("suppression_reason")
            or (effective_context or {}).get("resolution_reason")
            or ""
        ).strip()
    ):
        # A manual notify=false refresh is a real production publication, but
        # it is not a notification attempt. Persist that policy decision in
        # the public audit row instead of leaving a misleading candidate.
        snapshot["briefing"]["notification_eligible"] = False
        snapshot["briefing"]["status"] = "suppressed"
        snapshot["briefing"]["notification_reason"] = "manual_notification_opt_in_required"
    if (
        isinstance(snapshot.get("briefing"), dict)
        and str((effective_context or {}).get("delivery_intent") or "notify_candidate") == "notify_candidate"
        and not _briefing_evidence_ready(snapshot["briefing"])
    ):
        # Keep the full evidence record on Pages, but do not turn an
        # insufficient market state into a generic Telegram placeholder.
        snapshot["briefing"]["notification_eligible"] = False
        snapshot["briefing"]["status"] = "suppressed"
        snapshot["briefing"]["notification_reason"] = "insufficient_market_evidence"
    # Read the latest delivered decision before publication.  This is a
    # read-only comparison, so notify=false never consumes the delivery lock.
    # The result is persisted in the same briefing object that the sender and
    # Mini App consume.
    briefing_for_comparison = snapshot.get("briefing")
    comparison_notification_key = ""
    comparison_material_changes: list[Any] = []
    comparison_delivery_eligible = False
    comparison_reason = ""
    if isinstance(briefing_for_comparison, dict) and isinstance(effective_context, dict):
        comparison_slot = str(effective_context.get("effective_slot") or slot or "").strip()
        comparison_date = str(effective_context.get("slot_date") or "").strip()
        comparison_fingerprint = str(briefing_for_comparison.get("decision_fingerprint") or "").strip()
        assessment_for_comparison = briefing_for_comparison.get("market_assessment")
        if (
            comparison_slot and comparison_date and comparison_fingerprint
            and isinstance(assessment_for_comparison, dict)
        ):
            comparison = EventLedger().scheduled_decision_preview(
                anchor_key(comparison_slot, comparison_date),
                decision_fingerprint=comparison_fingerprint,
                market_scope=str(assessment_for_comparison.get("market_scope") or ""),
            )
            briefing_for_comparison.update({
                "comparison_notification_key": comparison.get("comparison_notification_key") or "",
                "material_changes": comparison.get("material_changes") or [],
                "delivery_eligible": comparison.get("delivery_eligible") is True,
                "suppression_reason": comparison.get("suppression_reason") or "",
            })
            comparison_notification_key = str(comparison.get("comparison_notification_key") or "")
            comparison_material_changes = list(comparison.get("material_changes") or [])
            comparison_delivery_eligible = comparison.get("delivery_eligible") is True
            comparison_reason = str(comparison.get("suppression_reason") or "")
            if (
                notification_requested is not False
                and str(effective_context.get("delivery_intent") or "") == "notify_candidate"
                and comparison.get("delivery_eligible") is not True
            ):
                briefing_for_comparison["notification_eligible"] = False
                briefing_for_comparison["status"] = "suppressed"
                briefing_for_comparison["notification_reason"] = str(
                    comparison.get("suppression_reason") or "same_decision_unchanged"
                )
    raw_briefing_record = snapshot.get("briefing")
    briefing_record: dict[str, Any] = raw_briefing_record if isinstance(raw_briefing_record, dict) else {}
    briefing_suppressed = bool(
        briefing_record.get("briefing_id")
        and briefing_record.get("notification_eligible") is not True
    )
    event = None if briefing_suppressed else _pick_event(snapshot, slot)
    briefing_event = None if briefing_suppressed else _briefing_delivery_event(snapshot, slot)
    decision_event = briefing_event or event
    context_reason = ""
    if isinstance(effective_context, dict):
        context_reason = str(
            effective_context.get("suppression_reason")
            or effective_context.get("resolution_reason")
            or ""
        ).strip()
    if briefing_suppressed and not context_reason:
        context_reason = str(briefing_record.get("notification_reason") or "").strip()
    prepared_reason = (
        context_reason
        if context_reason and str((effective_context or {}).get("delivery_intent") or "") != "notify_candidate"
        else "candidate_ready"
        if decision_event
        else str((snapshot.get("briefing") or {}).get("notification_reason") or "no_eligible_candidate")
    )
    delivery_eligible = bool(
        comparison_delivery_eligible
        or briefing_record.get("delivery_eligible") is True
    )
    if str((effective_context or {}).get("delivery_intent") or "") != "notify_candidate":
        delivery_eligible = False
    if notification_requested is False:
        delivery_eligible = False
    completed_at = datetime.now(UTC).isoformat()
    schedule_decision = _attach_schedule_decision(
        snapshot,
        snapshot_path=snapshot_path,
        slot=slot,
        context=effective_context,
        production_started_at=production_started_at,
        completed_at=completed_at,
        decision_event=decision_event,
        briefing=briefing_record,
        comparison_notification_key=comparison_notification_key,
        material_changes=comparison_material_changes,
        delivery_eligible=delivery_eligible,
        comparison_reason=comparison_reason,
        notification_requested=notification_requested,
    )
    prepared_decision = decision_summary(
        event=decision_event,
        scan_status="completed",
        notification_expected=bool(decision_event) and delivery_eligible,
        notification_status=str(schedule_decision["notification_status"]),
        notification_reason=str(schedule_decision["suppression_reason"] or prepared_reason),
    )
    snapshot["source_health"] = merge_decision_health(
        snapshot.get("source_health"), "scheduled_brief", prepared_decision,
    )
    if not write_snapshot(snapshot, snapshot_path):
        _write_decision_output(
            {"prepared": "false", "sent": "false", "reason": "snapshot_publish_skipped"},
            event=decision_event, notification_status="blocked", notification_reason="snapshot_publish_skipped",
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
        {
            "prepared": "true",
            "production_status": schedule_decision["production_status"],
            "schedule_contract_status": schedule_decision["contract_status"],
            "scheduled_slot": schedule_decision["scheduled_slot"],
            "effective_market_phase": schedule_decision["effective_market_phase"],
            "scheduled_for_at": schedule_decision["scheduled_for_at"],
            "dispatch_unix": schedule_decision["dispatch_unix"],
            "dispatch_trace_id": schedule_decision["dispatch_trace_id"],
            "run_started_at": schedule_decision["run_started_at"],
            "completed_at": schedule_decision["completed_at"],
            "delay_seconds": schedule_decision["delay_seconds"],
            "trigger_kind": schedule_decision["trigger_kind"],
            "comparison_notification_key": schedule_decision["comparison_notification_key"],
            "material_changes": schedule_decision["material_changes"],
            "delivery_eligible": schedule_decision["delivery_eligible"],
            "suppression_reason": schedule_decision["suppression_reason"],
            **metadata,
        },
        event=decision_event,
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

    ledger = EventLedger()
    history = ledger.delivery_history()
    release_alert_ids = _release_alert_ids(manifest_path, gate.manifest)
    briefing_raw = snapshot.get("briefing")
    briefing: dict[str, Any] = briefing_raw if isinstance(briefing_raw, dict) else {}
    raw_slot_context = briefing.get("slot_context")
    slot_context: dict[str, Any] = raw_slot_context if isinstance(raw_slot_context, dict) else {}
    delivery_intent = str(slot_context.get("delivery_intent") or "").strip()
    if delivery_intent and delivery_intent != "notify_candidate":
        reason = str(slot_context.get("resolution_reason") or "delivery_intent_not_notify")
        _write_decision_output(
            {
                "sent": "false",
                "delivery_status": "suppressed",
                "reason": reason,
                "notification_expected": "false",
                "notification_status": "suppressed",
                "notification_reason": reason,
                "last_receipt_status": "not_attempted",
            },
            notification_status="suppressed",
            notification_reason=reason,
            notification_expected=False,
            last_receipt_status="not_attempted",
        )
        return
    if briefing.get("briefing_id") and briefing.get("notification_eligible") is not True:
        reason = str(briefing.get("notification_reason") or "briefing_not_eligible")
        _write_decision_output(
            {
                "sent": "false",
                "delivery_status": "suppressed",
                "reason": reason,
                "notification_expected": "false",
                "notification_status": "suppressed",
                "notification_reason": reason,
                "last_receipt_status": "not_attempted",
            },
            notification_status="suppressed",
            notification_reason=reason,
            notification_expected=False,
            last_receipt_status="not_attempted",
        )
        return
    briefing_event = _briefing_delivery_event(snapshot, slot)
    if briefing_event is not None:
        briefing_id = str(briefing_event.get("notification_id") or "")
        if release_alert_ids is not None and briefing_id not in release_alert_ids:
            event, budget, selection_reason = None, {"allowed": False}, "briefing_alert_artifact_missing"
        else:
            event = briefing_event
            budget = decide_alert_budget(event, history)
            selection_reason = "candidate_ready" if budget.get("allowed", False) else str(budget.get("reason") or "alert_budget_suppressed")
            if not budget.get("allowed", False):
                event = None
    else:
        event, budget, selection_reason = _select_scheduled_candidate(
            snapshot, slot, ledger, release_alert_ids=release_alert_ids,
        )
    if event is None:
        # A scheduled slot with no complete, release-bound candidate is a
        # successful scan with no Telegram attempt.  Do not turn suppression
        # into a second generic message such as "本輪無觸發".
        reason = selection_reason or "no_eligible_candidate"
        _write_decision_output(
            {
                "sent": "false",
                "delivery_status": "suppressed",
                "reason": reason,
                "notification_expected": "false",
                "notification_status": "suppressed",
                "notification_reason": reason,
                "last_receipt_status": "not_attempted",
            },
            notification_status="suppressed",
            notification_reason=reason,
            notification_expected=False,
            last_receipt_status="not_attempted",
        )
        return
    settings = get_settings()
    if not settings.telegram_ready:
        raise RuntimeError("Telegram configuration is incomplete")
    event_risk = canonical_prstk_risk_level(event)
    effective_slot_key = str(
        slot_key
        or os.getenv("SCHEDULED_SLOT_KEY")
        or anchor_key(slot, datetime.now().astimezone().date().isoformat())
    )
    effective_run_id = str(run_id or os.getenv("GITHUB_RUN_ID", ""))
    notification_key = notification_key_for_event(event, slot_key=effective_slot_key)
    decision_fingerprint = str(
        event.get("decision_fingerprint")
        or briefing.get("decision_fingerprint")
        or briefing.get("canonical_content_hash")
        or notification_key
    ).strip()
    send_chat_ids = settings.telegram_chat_ids
    if not notification_key:
        _write_decision_output({"sent": "false", "delivery_status": "suppressed", "reason": "notification_key_missing"}, notification_status="suppressed", notification_reason="notification_key_missing")
        return
    correlation = briefing_correlation(snapshot, slot, event)
    trace_id = str(briefing.get("trace_id") or correlation["trace_id"])
    observation_id = str(briefing.get("observation_id") or correlation["observation_id"])
    caption = str(briefing.get("public_short_message") or "").strip() if briefing_event is not None else build_brief(snapshot, slot)
    alert_id = str(
        (event or {}).get("notification_id")
        or (event or {}).get("event_cluster_key")
        or (event or {}).get("event_key")
        or notification_key
        or trace_id
    )
    target_url = alert_mini_app_url(
        settings.dashboard_url,
        alert_id=alert_id,
        release_id=gate.release_id or "",
        snapshot_id=snapshot_id,
        observation_id=observation_id,
    )
    # A scheduled briefing is itself the report source.  Bind that internal
    # HTTPS deep link before any claim or Telegram attempt so its delivery can
    # be persisted and replayed without inventing an external news URL.
    if briefing_event is not None:
        event["source_url"] = target_url
        event["source_domain"] = urlsplit(target_url).hostname or ""
    preflight = (
        ledger.preflight_delivery(event)
        if hasattr(ledger, "preflight_delivery")
        else {"ok": bool(event_source_url(event))}
    )
    if not preflight.get("ok"):
        _write_decision_output(
            {
                "sent": "false",
                "delivery_status": "suppressed",
                "reason": str(preflight.get("reason") or "ledger_preflight_failed"),
                "notification_expected": "false",
                "notification_status": "suppressed",
                "notification_reason": str(preflight.get("reason") or "ledger_preflight_failed"),
                "last_receipt_status": "not_attempted",
            },
            notification_status="suppressed",
            notification_reason=str(preflight.get("reason") or "ledger_preflight_failed"),
            notification_expected=False,
            last_receipt_status="not_attempted",
        )
        return
    claim: dict[str, Any] = {}
    if str(event.get("source_key") or event.get("source") or "").strip().casefold() != "financialjuice":
        recipient_hashes = tuple(recipient_hash(chat_id) for chat_id in settings.telegram_chat_ids)
        if hasattr(ledger, "claim_scheduled_brief"):
            claim = ledger.claim_scheduled_brief(
                effective_slot_key,
                decision_fingerprint=decision_fingerprint,
                market_scope=str((briefing.get("market_assessment") or {}).get("market_scope") or ""),
                evidence_fingerprint=str(briefing.get("evidence_fingerprint") or ""),
                material_changes=tuple(
                    str(item) for item in briefing.get("material_changes") or []
                    if str(item).strip()
                ),
                recipient_hashes=recipient_hashes,
                run_id=effective_run_id,
            )
        elif hasattr(ledger, "claim_notification"):
            claim = ledger.claim_notification(
                notification_key,
                slot_key=effective_slot_key,
                recipient_hashes=recipient_hashes,
                run_id=effective_run_id,
            )
        else:
            # Minimal test/compatibility doubles predate the scheduled-anchor
            # claim API. The real EventLedger always takes one of the paths.
            claim = {"status": "claimed", "pending_recipient_hashes": []}
        if claim.get("status") != "claimed":
            _write_decision_output(
                {
                    "sent": "false",
                    "delivery_status": "suppressed",
                    "reason": f"notification_{claim.get('status', 'blocked')}",
                    "notification_key": notification_key,
                    "comparison_notification_key": claim.get("comparison_notification_key") or "",
                    "material_changes": claim.get("material_changes") or [],
                    "delivery_eligible": False,
                    "suppression_reason": claim.get("suppression_reason") or f"notification_{claim.get('status', 'blocked')}",
                },
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
                message_kind="scheduled_brief",
            )
    except (OSError, ValueError) as exc:
        if event is None or str(event.get("source_key") or event.get("source") or "").strip().casefold() != "financialjuice":
            ledger.complete_notification_claim(
                claim.get("notification_key") or notification_key,
                uncertain=True,
            )
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
            # The immediate lane already delivered this event.  The selector
            # skips durable delivered claims and considers the next candidate;
            # this branch only handles a race between selection and delivery.
            _write_decision_output({
                "sent": "false",
                "delivery_status": "suppressed",
                "reason": "already_delivered",
                "notification_key": fj_delivery.get("notification_key", notification_key),
                "release_id": gate.release_id,
                "snapshot_id": snapshot_id,
                "trace_id": trace_id,
                "notification_expected": "false",
                "notification_status": "suppressed",
                "notification_reason": "already_delivered",
                "risk": event_risk,
                "last_receipt_status": "already_delivered",
            }, event=event, notification_status="suppressed", notification_reason="already_delivered", notification_expected=False, last_receipt_status="already_delivered")
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
                claim.get("notification_key") or notification_key,
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
        "comparison_notification_key": claim.get("comparison_notification_key") if isinstance(claim, dict) else "",
        "material_changes": claim.get("material_changes") if isinstance(claim, dict) else [],
        "delivery_eligible": True,
        "suppression_reason": "",
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
    write_event_lock_key(event)
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare or deliver a scheduled brief")
    parser.add_argument("--slot", required=True)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--send-only", action="store_true")
    parser.add_argument("--snapshot", type=Path, default=Path("site/data/market.json"))
    parser.add_argument("--manifest", type=Path, default=Path("site/data/release-manifest.json"))
    parser.add_argument("--public-url", default=None)
    parser.add_argument("--slot-key", default=None)
    parser.add_argument("--slot-context", default=None)
    parser.add_argument(
        "--notification-requested",
        choices=("true", "false"),
        default=None,
        help="record whether this run was explicitly allowed to notify",
    )
    parser.add_argument(
        "--require-production-research",
        action="store_true",
        help="require a fresh production research artifact for research-only delivery",
    )
    args = parser.parse_args()
    if args.prepare_only == args.send_only:
        parser.error("choose exactly one of --prepare-only or --send-only")
    if args.prepare_only:
        context = None
        if args.slot_context:
            try:
                parsed = json.loads(args.slot_context)
                context = parsed if isinstance(parsed, dict) else None
            except (TypeError, ValueError):
                parser.error("--slot-context must be a JSON object")
        notification_requested = (
            None
            if args.notification_requested is None
            else args.notification_requested == "true"
        )
        prepare(
            args.slot,
            args.snapshot,
            slot_context=context,
            notification_requested=notification_requested,
        )
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
