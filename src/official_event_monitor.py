"""De-duplicated Telegram alerting for fresh first-party macro releases."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.alert_budget import decide_alert_budget
from src.alert_orchestrator import content_is_incomplete, notification_key_for_event, recipient_hash
from src.config import get_settings
from src.event_alert_policy import decide_event_alert_policy, event_market_scope
from src.event_ledger import (
    EventLedger,
    canonical_event_key,
    is_secondary_commentary,
    taiwan_investor_priority,
)
from src.external_observation_input import (
    external_observations_path,
    external_source_health,
    external_source_health_from_remote,
    load_external_observations,
    merge_external_source_health,
)
from src.financialjuice_notification import (
    deliver_financialjuice_event,
    financialjuice_notification_aliases,
)
from src.financialjuice_priority import (
    bind_financialjuice_semantic_views,
    is_financialjuice_priority_event,
    project_financialjuice_priority,
    public_financialjuice_observations,
    replace_financialjuice_event_lane,
)
from src.financialjuice_release_contract import (
    apply_financialjuice_release_boundary,
    attach_financialjuice_release_diagnostic,
    is_financialjuice_row,
    validate_financialjuice_release,
)
from src.market_data import build_market_snapshot
from src.notification_observability import decision_summary, merge_decision_health, write_summary
from src.railway_observation_client import load_railway_observations
from src.railway_secret import delivery_shared_secret
from src.refresh_market_data import write_snapshot
from src.release_gate import verify_release_for_delivery
from src.telegram_client import alert_mini_app_url, canonical_prstk_risk_level, send_text_briefs_audited, validate_brief


def _is_taiwan_market_window(now: datetime | None = None) -> bool:
    """Return whether Taiwan-session price alerts should lead the queue."""
    local_now = now or datetime.now(ZoneInfo("Asia/Taipei"))
    if local_now.tzinfo is None:
        local_now = local_now.replace(tzinfo=ZoneInfo("Asia/Taipei"))
    else:
        local_now = local_now.astimezone(ZoneInfo("Asia/Taipei"))
    return local_now.weekday() < 5 and time(8, 45) <= local_now.time() <= time(13, 30)


def _external_observations_configured() -> bool:
    """Return whether the signed Worker/Railway observation export is enabled."""
    return bool(
        os.getenv("PUBLIC_OBSERVATIONS_URL", "").strip()
        or os.getenv("RAILWAY_OBSERVATIONS_URL", "").strip()
        or os.getenv("RAILWAY_STATUS_URL", "").strip()
        or delivery_shared_secret()
    )


def _merge_observations(local: list[dict[str, Any]], remote: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prefer the authenticated remote row while retaining local fallback rows."""
    merged: dict[str, dict[str, Any]] = {}
    for row in [*local, *remote]:
        if not isinstance(row, dict):
            continue
        key = str(row.get("observation_id") or "").strip()
        if key:
            merged[key] = row
    return list(merged.values())


def _attach_realtime_external_events(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Bind reviewed FinancialJuice observations to the realtime event lane.

    Gmail/Worker ingestion only stores a sanitized observation.  This monitor
    projects it through the existing event/risk/release contract so an event is
    delivered on the next monitor dispatch instead of waiting for a scheduled
    briefing.  Creator rows remain in the external observation lineage and are
    deliberately excluded from this market-event projection.
    """
    local_path = external_observations_path()
    local_rows, local_rejected = load_external_observations(local_path)
    remote_rows: list[dict[str, Any]] = []
    remote_health: dict[str, Any] = {}
    health: dict[str, Any] | None
    if _external_observations_configured():
        remote_rows, remote_health = load_railway_observations(include_priority_recovery=True)
    observations = _merge_observations(local_rows, remote_rows)
    fj_rows = [
        row for row in observations
        if str(row.get("content_origin") or row.get("source") or "").strip().casefold() == "financialjuice"
    ]
    events_container = snapshot.setdefault("events", {})
    if not isinstance(events_container, dict):
        events_container = {"items": []}
        snapshot["events"] = events_container
    existing_items = events_container.get("items")
    existing_events = [item for item in existing_items if isinstance(item, dict)] if isinstance(existing_items, list) else []
    projection = project_financialjuice_priority(
        fj_rows, existing_events=existing_events, market_snapshot=snapshot,
    )
    snapshot["financialjuice_priority_decisions"] = projection["decisions"]
    snapshot["financialjuice_priority_events"] = [
        item for item in projection["events"]
        if str(item.get("notification_status") or "") == "eligible"
    ]
    priority_event_refs: list[str] = []
    for item in projection["events"]:
        if _safe_vendor_importance(item) < 9:
            continue
        ref = str(item.get("priority_pending_ref") or "").strip()
        if ref and ref not in priority_event_refs:
            priority_event_refs.append(ref[:64])
    durable_recovery = [
        item for item in (remote_health.get("priority_recovery") or [])
        if isinstance(item, dict) and str(item.get("event_ref") or "").strip()
    ] if isinstance(remote_health, dict) else []
    durable_by_ref = {
        str(item["event_ref"]).strip(): item for item in durable_recovery
    }
    projected_by_ref = {
        str(item.get("priority_pending_ref") or "").strip(): item
        for item in projection["events"]
        if isinstance(item, dict) and str(item.get("priority_pending_ref") or "").strip()
    }
    durable_source_missing_refs: list[str] = []
    for ref in durable_by_ref:
        if ref not in priority_event_refs:
            priority_event_refs.append(ref[:64])
        if ref not in projected_by_ref:
            durable_source_missing_refs.append(ref[:64])
    # This is a safe correlation-only projection.  It lets the monitor
    # distinguish a ready event from a missing dispatch without exposing
    # message text, canonical keys or private mail identifiers.
    snapshot["financialjuice_priority_event_refs"] = priority_event_refs
    snapshot["financialjuice_priority_durable_recovery"] = [
        {
            "priority_pending_ref": str(item.get("event_ref") or "")[:64],
            "delivery_status": str(item.get("delivery_status") or "")[:40],
            "summary_status": str(item.get("summary_status") or "")[:40],
            "summary_reason": str(item.get("summary_reason") or "")[:120],
            "source_published_at": str(item.get("source_published_at") or "")[:80],
            "expires_at": str(item.get("expires_at") or "")[:80],
        }
        for item in durable_recovery
    ]
    snapshot["financialjuice_priority_durable_source_missing_refs"] = durable_source_missing_refs
    # The monitor only needs a bounded age/count signal to retry a pending
    # summary.  Keep the pending marker public-safe: event text, source IDs,
    # canonical keys and mail-derived fields stay in the private observation
    # lineage rather than entering the Pages snapshot.
    projected_pending = [
        {
            "source_key": "financialjuice",
            "vendor_importance": item.get("vendor_importance"),
            "notification_status": "content_incomplete",
            "notification_reason": "summary_semantics_incomplete",
            "priority_pending_ref": item.get("priority_pending_ref"),
            "freshness_status": item.get("freshness_status"),
            "source_published_at": item.get("source_published_at"),
            "received_at": item.get("received_at"),
            "candidate_at": item.get("candidate_at"),
        }
        for item in projection["events"]
        if str(item.get("notification_status") or "") == "content_incomplete"
        and str(item.get("freshness_status") or "") == "fresh"
        and _safe_vendor_importance(item) >= 9
    ]
    pending_by_ref = {
        str(item.get("priority_pending_ref") or "").strip(): item
        for item in projected_pending
        if str(item.get("priority_pending_ref") or "").strip()
    }
    for ref, durable in durable_by_ref.items():
        if str(durable.get("delivery_status") or "") != "summary_pending":
            continue
        if ref in pending_by_ref:
            pending_by_ref[ref]["summary_reason"] = str(durable.get("summary_reason") or "summary_semantics_incomplete")[:120]
            continue
        source = projected_by_ref.get(ref)
        if not isinstance(source, dict):
            continue
        pending_by_ref[ref] = {
            "source_key": "financialjuice",
            "vendor_importance": source.get("vendor_importance"),
            "notification_status": "content_incomplete",
            "notification_reason": str(durable.get("summary_reason") or "summary_semantics_incomplete")[:120],
            "priority_pending_ref": ref,
            "freshness_status": source.get("freshness_status"),
            "source_published_at": durable.get("source_published_at") or source.get("source_published_at"),
            "received_at": source.get("received_at"),
            "candidate_at": source.get("candidate_at"),
        }
    snapshot["financialjuice_priority_pending_events"] = list(pending_by_ref.values())
    snapshot["financialjuice_observations"] = bind_financialjuice_semantic_views(
        fj_rows, projection["events"],
    )
    # Apply the same public event boundary as scheduled releases so an
    # incomplete, explicitly suppressed FJ row cannot leak into the realtime
    # selector or abort unrelated market publication.
    events_container["items"] = replace_financialjuice_event_lane(
        existing_events, projection["events"],
    )
    boundary = apply_financialjuice_release_boundary(snapshot)
    snapshot["financialjuice_release_boundary"] = boundary
    # Use the same post-boundary event set for the public observation lane;
    # otherwise a quarantined row could be removed from events.items and then
    # reintroduced through the external-observation projection.
    surviving_projection = [
        item for item in projection["events"]
        if any(
            isinstance(public_item, dict)
            and str(public_item.get("observation_id") or public_item.get("item_id") or "").strip()
            == str(item.get("observation_id") or item.get("item_id") or "").strip()
            for public_item in events_container.get("items", [])
        )
    ]
    snapshot["external_observations"] = public_financialjuice_observations(observations, surviving_projection)
    rejected = local_rejected + int(remote_health.get("rejected_count") or 0)
    if _external_observations_configured():
        health = external_source_health_from_remote(
            remote_health, accepted=fj_rows, rejected=rejected, checked_at=datetime.now().astimezone(),
        )
    else:
        health = external_source_health(
            path=local_path, accepted=fj_rows, rejected=rejected, checked_at=datetime.now().astimezone(),
        )
    if health:
        snapshot["source_health"] = merge_external_source_health(snapshot.get("source_health") or {}, health)
        snapshot["external_source_health"] = health
    contract = validate_financialjuice_release(snapshot)
    contract.update(boundary)
    snapshot["financialjuice_release_contract"] = contract
    attach_financialjuice_release_diagnostic(snapshot, boundary)
    if not contract["ok"] or boundary["fatal_alert_contract_errors"]:
        # Keep the snapshot auditable, but never let a contradictory FJ row
        # become a realtime notification candidate.
        events_container["items"] = [
            item for item in events_container.get("items", [])
            if not isinstance(item, dict) or not is_financialjuice_row(item)
        ]
    return snapshot


def select_official_event(
    snapshot: dict[str, Any], now: datetime | None = None, *, baseline_official: bool = False,
    excluded_event_keys: set[str] | None = None,
) -> dict[str, Any] | None:
    """Select a verified official release, then a threshold price signal.

    The price signal fallback is constrained by ``event_alerts`` thresholds, so
    routine price refreshes never become Telegram notifications.
    """
    items = snapshot.get("official_events", {}).get("items", [])
    detailed_events = snapshot.get("events", {}).get("items", [])
    candidates: list[dict[str, Any]] = []
    if items and not baseline_official:
        for item in items:
            detailed = next(
                (
                    event for event in detailed_events
                    if event.get("url") == item.get("url")
                    or event.get("source_url") == item.get("url")
                ),
                None,
            )
            # Corporate notices are only eligible after their own market
            # scope has been synchronized. Routine calendar notices and
            # pending events remain visible in Mini App but must not push.
            if detailed and (
                detailed.get("corporate_alert_eligible") is False
                or detailed.get("notification_status") in {"observe_only", "pending"}
            ):
                continue
            if item.get("importance") != "high-risk":
                if detailed and detailed.get("high_risk_eligible") is False:
                    continue
                candidates.append(detailed or item)
                continue
            # A black-swan candidate must be confirmed by a related public
            # market move before it becomes a Telegram alert. It remains in
            # the dashboard as an observation when confirmation is absent.
            detailed = next(
                (
                    event for event in detailed_events
                    if (event.get("url") == item.get("url") or event.get("source_url") == item.get("url"))
                    and event.get("high_risk_eligible", True)
                    and (event.get("impact_confirmation") or {}).get("confirmed")
                ),
                None,
            )
            if detailed:
                candidates.append(detailed)
    # Major news is evaluated by the same event builder as official releases
    # and price signals.  Public providers can produce a low-risk observation
    # notification, while strict conflict/black-swan rows remain pending until
    # the existing official + market-sync gate is satisfied.
    for event in detailed_events:
        if event.get("kind") == "market_signal":
            continue
        status = str(event.get("notification_status") or "").strip().lower()
        if status not in {"eligible", "ready"}:
            continue
        risk = canonical_prstk_risk_level(event)
        if event.get("public_observation") and risk in {"R3", "R4"}:
            continue
        if is_secondary_commentary(event):
            # Keep the row in the release/Mini App, but route opinion-only
            # discovery content to the scheduled digest rather than an
            # immediate Telegram interruption.
            event["notification_status"] = "digest_only"
            event["notification_reason"] = "secondary_commentary_digest_only"
            continue
        candidates.append(event)
    excluded = excluded_event_keys or set()
    if candidates:
        def _candidate_key(event: dict[str, Any]) -> tuple[int, int, int, int, int]:
            risk = canonical_prstk_risk_level(event)
            risk_rank = {"R0": 0, "R1": 0, "R2": 1, "R3": 1, "R4": 2}.get(risk, 0)
            official = int(bool(event.get("official_confirmed") or event.get("official_confirmation") or event.get("source_tier") == "official"))
            # A qualifying FinancialJuice row is an explicit vendor-priority
            # exception. Keep that notification priority separate from the
            # PRStK risk grade, but let it win the shared candidate queue so
            # an unrelated eligible event cannot starve the FJ lane.
            vendor_priority = int(
                str(event.get("source_key") or event.get("source") or "").strip().casefold() == "financialjuice"
                and event.get("vendor_priority_notification") is True
                and str(event.get("notification_status") or "").strip().casefold() in {"eligible", "ready"}
            )
            try:
                vendor_importance = int(float(str(event.get("vendor_importance"))))
            except (TypeError, ValueError):
                vendor_importance = 0
            return (0 if vendor_priority else 1, taiwan_investor_priority(event, now=now), -vendor_importance, -official, -risk_rank)
        candidates.sort(key=_candidate_key)
        for candidate in candidates:
            if event_key(candidate) not in excluded:
                return candidate

    signals = [
        event for event in snapshot.get("events", {}).get("items", [])
        if event.get("kind") == "market_signal" and event_key(event) not in excluded
    ]
    if _is_taiwan_market_window(now):
        # During the Taiwan session, a broad Taiwan price signal has priority.
        # Commodity/crypto moves remain visible in the Mini App unless paired
        # with a verified official event above.
        taiwan_signal = next(
            (
                event for event in signals
                if (event.get("instrument") or {}).get("ticker") in {"TAIEX", "2330", "006208", "00685L"}
            ),
            None,
        )
        if taiwan_signal:
            return taiwan_signal
        # Keep the Taiwan session focused, but do not suppress a genuinely
        # broad overseas equity signal merely because Taiwan is quiet.
        return next(
            (
                event for event in signals
                if (event.get("instrument") or {}).get("ticker") in {"NASDAQ", "SOX", "S&P500", "DJIA", "NIKKEI", "KOSPI"}
            ),
            None,
        )
    return signals[0] if signals else None


def event_key(event: dict[str, Any] | None) -> str:
    """Create the durable canonical key used by cache and event ledger."""
    return canonical_event_key(event)


def _observe_event(event: dict[str, Any] | None, *, reminded: bool = False) -> dict[str, Any]:
    """Persist discovery/reminder facts alongside the public market snapshot."""
    if not event:
        return {"changed": False}
    ledger = EventLedger()
    if reminded:
        key = ledger.mark_reminded(event)
        record = dict(ledger.records.get(key) or {})
        record["changed"] = True
    else:
        record = ledger.observe(event)
        # The durable ledger is the source of truth after cache eviction or a
        # concurrent workflow run. All event producers use the same 30-minute
        # cooldown; the GitHub cache is only a fast idempotency optimization.
        record["should_remind"] = ledger.should_remind(event)
    ledger.save()
    return record


def _financialjuice_delivery_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project redacted FJ recipient receipts for replay-safe immediate sends."""
    projected: list[dict[str, Any]] = []
    for row in history:
        if not isinstance(row, dict):
            continue
        receipts = row.get("delivery_receipts")
        if isinstance(receipts, list):
            for receipt in receipts:
                if isinstance(receipt, dict):
                    projected.append({
                        "notification_key": receipt.get("notification_key") or row.get("notification_key"),
                        "recipient_hash": receipt.get("recipient_hash") or receipt.get("chat_id_hash"),
                        "delivery_status": receipt.get("delivery_status") or receipt.get("status"),
                    })
        elif row.get("notification_key") and row.get("recipient_hash"):
            projected.append({
                "notification_key": row.get("notification_key"),
                "recipient_hash": row.get("recipient_hash"),
                "delivery_status": row.get("delivery_status") or row.get("status"),
            })
    return projected


def build_official_event_brief(event: dict[str, Any]) -> str:
    """Make a neutral watch-sized alert through the single public formatter."""
    from src.event_output import short_event_message
    text = short_event_message(event)
    if text:
        validate_brief(text)
    return text


def prepare_snapshot(*, publish: bool = True) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Build a snapshot and optionally publish it before a direct send."""
    snapshot = build_market_snapshot()
    snapshot = _attach_realtime_external_events(snapshot)
    # Do not publish notification observability here: finding a candidate is
    # not yet the final send decision.  The workflow's status preflight adds
    # the policy/content result before its single immutable snapshot write.
    baseline_official = os.getenv("OFFICIAL_EVENT_BASELINE_READY") == "false"
    event = select_official_event(snapshot, baseline_official=baseline_official)
    if publish and not write_snapshot(snapshot):
        # Never evaluate or deliver an event from a run that lost the
        # freshness race with a newer published snapshot.
        print("Snapshot publish skipped; suppressing event delivery.")
        return snapshot, None
    return snapshot, event


def write_status_output(
    event: dict[str, Any] | None,
    snapshot: dict[str, Any] | None = None,
    *,
    publish_snapshot: bool = False,
) -> None:
    """Write GitHub Actions outputs without mixing provider diagnostics into them."""
    content_status = "not_applicable"
    content_blocked = False
    policy_suppressed = False
    unknown_suppression = False
    suppression_reason = ""
    ledger_record: dict[str, Any] = {}
    should_send = False
    suppressed_candidates = 0
    snapshot_publish_failed = False
    durable_receipt_verified = False
    if event:
        excluded: set[str] = set()
        candidates_value = (
            snapshot.get("events", {}).get("items", [])
            if isinstance(snapshot, dict) and isinstance(snapshot.get("events"), dict)
            else []
        )
        candidate_limit = max(1, len(candidates_value) if isinstance(candidates_value, list) else 1) + 1
        candidate = event
        for _ in range(candidate_limit):
            candidate_durable_receipt_verified = False
            try:
                candidate_caption = build_official_event_brief(candidate)
            except (TypeError, ValueError):
                candidate_caption = ""
            candidate_incomplete = content_is_incomplete(candidate, candidate_caption)
            if candidate_incomplete:
                content_blocked = True
                content_status = "incomplete"
            else:
                content_blocked = False
                content_status = "complete"
                candidate_record = _observe_event(candidate)
                candidate_priority = is_financialjuice_priority_event(candidate)
                candidate_should_send = bool(
                    candidate_priority or candidate_record.get("should_remind", True)
                )
                candidate_suppressed = False
                candidate_unknown_suppression = False
                candidate_reason = ""
                try:
                    theme_ledger = EventLedger()
                    claims = getattr(theme_ledger, "delivery_claims", {})
                    claim_keys = [event_key(candidate), notification_key_for_event(candidate)]
                    source_key = str(candidate.get("source_key") or candidate.get("source") or "").strip().casefold()
                    if source_key == "financialjuice":
                        claim_keys.extend(financialjuice_notification_aliases(candidate))
                    matching_claims = [
                        claims[key]
                        for key in dict.fromkeys(claim_keys)
                        if key and isinstance(claims, dict) and key in claims
                    ]
                    claim_statuses = [
                        str(claim.get("status") or "").strip().casefold()
                        if isinstance(claim, dict) else ""
                        for claim in matching_claims
                    ]
                    unknown_claim = any(
                        status not in {"delivered", "in_flight", "uncertain", "retryable"}
                        for status in claim_statuses
                    )
                    if matching_claims and unknown_claim:
                        candidate_should_send = False
                        candidate_unknown_suppression = True
                        candidate_reason = "notification_claim_state_unrecognized"
                    elif any(status in {"in_flight", "uncertain"} for status in claim_statuses):
                        candidate_should_send = False
                        candidate_unknown_suppression = True
                        candidate_reason = "notification_claim_in_flight_or_uncertain"
                    elif any(status == "delivered" for status in claim_statuses):
                        if any(status != "delivered" for status in claim_statuses):
                            candidate_should_send = False
                            candidate_unknown_suppression = True
                            candidate_reason = "notification_claim_state_conflict"
                        else:
                            complete_receipts = True
                            for matched_claim in matching_claims:
                                configured_values = matched_claim.get("recipient_hashes")
                                delivered_values = matched_claim.get("delivered_recipient_hashes")
                                configured = {
                                    str(value).strip()
                                    for value in configured_values
                                    if str(value).strip()
                                } if isinstance(configured_values, (list, tuple, set)) else set()
                                delivered = {
                                    str(value).strip()
                                    for value in delivered_values
                                    if str(value).strip()
                                } if isinstance(delivered_values, (list, tuple, set)) else set()
                                if not configured or not configured.issubset(delivered):
                                    complete_receipts = False
                                    break
                            if complete_receipts:
                                candidate_should_send = False
                                candidate_suppressed = True
                                candidate_durable_receipt_verified = True
                                candidate_reason = "already_delivered"
                            else:
                                candidate_should_send = False
                                candidate_unknown_suppression = True
                                candidate_reason = "delivered_claim_missing_recipient_receipts"
                    elif not candidate_priority and hasattr(theme_ledger, "theme_decision"):
                        theme = theme_ledger.theme_decision(candidate)
                        if hasattr(theme_ledger, "save"):
                            theme_ledger.save()
                        theme_reason = str(theme.get("reason") or "theme_decision_unavailable")
                        if not theme.get("allowed", False):
                            candidate_should_send = False
                            if theme_reason in {"same_theme_within_2h", "same_theme_unchanged"}:
                                candidate_suppressed = True
                                candidate_reason = f"theme:{theme_reason}"
                            else:
                                candidate_unknown_suppression = True
                                candidate_reason = f"theme:{theme_reason}"
                        elif not candidate_should_send:
                            candidate_unknown_suppression = True
                            candidate_reason = "preflight_sender_policy_disagreement"
                    elif not candidate_priority and not candidate_should_send:
                        candidate_unknown_suppression = True
                        candidate_reason = "theme_preflight_unavailable"
                except (OSError, RuntimeError, TypeError, ValueError):
                    candidate_unknown_suppression = True
                    candidate_should_send = False
                    candidate_reason = "theme_preflight_unavailable"
                event = candidate
                ledger_record = candidate_record
                durable_receipt_verified = candidate_durable_receipt_verified
                if candidate_should_send:
                    should_send = True
                    content_blocked = False
                    policy_suppressed = False
                    unknown_suppression = False
                    break
                policy_suppressed = candidate_suppressed
                unknown_suppression = candidate_unknown_suppression
                suppression_reason = candidate_reason
                if candidate_unknown_suppression:
                    event = candidate
                    break
            identity = event_key(candidate)
            if identity:
                excluded.add(identity)
            next_event = select_official_event(snapshot, excluded_event_keys=excluded) if isinstance(snapshot, dict) else None
            if next_event is None:
                event = candidate
                break
            suppressed_candidates += 1
            candidate = next_event
    pending_value = (
        snapshot.get("financialjuice_priority_pending_events")
        if isinstance(snapshot, dict) else []
    )
    pending_events = [item for item in pending_value if isinstance(item, dict)] if isinstance(pending_value, list) else []
    dispatch_detected = _safe_nonnegative_int(os.getenv("DISPATCH_PRIORITY_CANDIDATE_DETECTED"))
    dispatch_refs = _dispatch_pending_refs()
    dispatch_event_refs = _dispatch_event_refs()
    pending_refs = {
        str(item.get("priority_pending_ref") or "").strip()
        for item in pending_events
        if str(item.get("priority_pending_ref") or "").strip()
    }
    raw_projected_refs = snapshot.get("financialjuice_priority_event_refs", []) if isinstance(snapshot, dict) else []
    projected_event_refs = {
        str(ref or "").strip()
        for ref in raw_projected_refs
        if str(ref or "").strip()
    } if isinstance(raw_projected_refs, (list, tuple)) else set()
    if isinstance(snapshot, dict):
        for item in snapshot.get("financialjuice_priority_events", []) or []:
            if isinstance(item, dict) and str(item.get("priority_pending_ref") or "").strip():
                projected_event_refs.add(str(item["priority_pending_ref"]).strip())
    projected_event_refs.update(pending_refs)
    # The legacy list is a delivery hint, not a claim that the row must still
    # be in summary_pending. A ready row is valid after the same event moves
    # forward in the durable lifecycle.
    missing_pending_refs = [ref for ref in dispatch_refs if ref not in projected_event_refs]
    missing_event_refs = [ref for ref in dispatch_event_refs if ref not in projected_event_refs]
    # New dispatches carry all high-score event refs.  During the compatibility
    # window, an old count-only dispatch may be rescued only when the monitor
    # can independently re-scan a durable projected FJ event; the count alone
    # never grants delivery eligibility.
    if dispatch_event_refs:
        missing_dispatch_refs = [*missing_event_refs, *missing_pending_refs]
    elif dispatch_refs:
        missing_dispatch_refs = missing_pending_refs
    else:
        missing_dispatch_refs = []
    pending_age_seconds = max(
        (_event_age_seconds(item) for item in pending_events),
        default=0,
    )
    contract_mismatch = bool(
        (dispatch_detected > 0 and not projected_event_refs)
        or (dispatch_event_refs and dispatch_detected > len(dispatch_event_refs))
        or bool(missing_dispatch_refs)
    )
    legacy_dispatch_rescued = bool(
        dispatch_detected > 0
        and not dispatch_event_refs
        and not dispatch_refs
        and projected_event_refs
        and not contract_mismatch
    )
    pending_timeout = bool(pending_events and pending_age_seconds > 600)
    diagnostic_event = event
    if not diagnostic_event and pending_events:
        # Only expose the provider category in bounded diagnostics.  The
        # pending event's identifiers and source text never enter this row.
        diagnostic_event = {"source_key": "financialjuice"}
    durable_source_missing = bool(
        isinstance(snapshot, dict)
        and snapshot.get("financialjuice_priority_durable_source_missing_refs")
    )
    hard_failure_reason = ""
    if contract_mismatch:
        reason = "priority_candidate_contract_mismatch"
        status = "contract_mismatch"
    elif durable_source_missing:
        reason = "priority_durable_observation_missing"
        status = "contract_mismatch"
    elif content_blocked:
        reason = "content_incomplete_quarantined"
        status = "content_incomplete"
        hard_failure_reason = reason
    elif should_send and event:
        reason = "candidate_ready"
        status = "candidate_ready"
    elif pending_events:
        reason = "priority_summary_timeout" if pending_timeout else "summary_semantics_incomplete"
        status = "summary_timeout" if pending_timeout else "summary_pending"
    elif policy_suppressed and not unknown_suppression:
        reason = suppression_reason or "policy_suppressed"
        status = "already_delivered" if suppression_reason == "already_delivered" else "policy_suppressed"
    elif unknown_suppression:
        reason = suppression_reason or "notification_policy_unresolved"
        status = "blocked"
        hard_failure_reason = reason
    else:
        reason = "candidate_ready" if should_send else "no_new_eligible_candidate" if event else "no_event"
        status = "candidate_ready" if should_send else "suppressed" if event else "no_event"
    last_candidate_event = pending_events[0] if pending_events else event
    last_candidate_at = (
        last_candidate_event.get("candidate_at")
        if isinstance(last_candidate_event, dict) else None
    )
    summary = decision_summary(
        event=diagnostic_event,
        scan_status="completed",
        notification_expected=bool((event and should_send) or pending_events or contract_mismatch or unknown_suppression),
        notification_status=status,
        notification_reason=reason,
        last_candidate_at=last_candidate_at,
    )
    summary["priority_dispatch_legacy_rescan"] = legacy_dispatch_rescued
    if should_send and suppressed_candidates and not contract_mismatch and not durable_source_missing and not pending_timeout and not content_blocked:
        summary["notification_reason"] = "top_candidate_suppressed_later_candidate_considered"
    if isinstance(snapshot, dict):
        summary["durable_receipt_verified"] = durable_receipt_verified
        snapshot["source_health"] = merge_decision_health(
            snapshot.get("source_health"), "official_event_monitor", summary,
        )
        if publish_snapshot and not write_snapshot(snapshot):
            # A candidate cannot be eligible for delivery unless this exact
            # terminal decision is part of the snapshot that will be released.
            snapshot_publish_failed = True
            hard_failure_reason = hard_failure_reason or "official_notification_snapshot_publish_blocked"
            should_send = False
            status = "blocked"
            reason = "official_notification_snapshot_publish_blocked"
            summary = decision_summary(
                event=diagnostic_event,
                scan_status="completed",
                notification_expected=bool(summary.get("notification_expected")),
                notification_status=status,
                notification_reason=reason,
                last_candidate_at=last_candidate_at,
            )
            summary["durable_receipt_verified"] = durable_receipt_verified
            snapshot["source_health"] = merge_decision_health(
                snapshot.get("source_health"), "official_event_monitor", summary,
            )
    lines = [
        f"should_send={'true' if should_send else 'false'}",
        f"key={event_key(event) if event else ''}",
        f"snapshot_publish_failed={'true' if snapshot_publish_failed else 'false'}",
        f"notification_id={event.get('notification_id', '') if event else ''}",
        f"snapshot_id={event.get('snapshot_id', '') if event else ''}",
        f"observation_id={event.get('observation_id', '') if event else ''}",
        f"candidate_type={summary['candidate_type']}",
        f"notification_expected={'true' if summary['notification_expected'] else 'false'}",
        f"notification_status={summary['notification_status']}",
        f"notification_reason={summary['notification_reason']}",
        f"durable_receipt_verified={'true' if durable_receipt_verified else 'false'}",
        f"priority_pending_count={len(pending_events)}",
        f"priority_dispatch_ref_count={len(dispatch_refs)}",
        f"priority_event_ref_count={len(projected_event_refs)}",
        f"priority_dispatch_event_ref_count={len(dispatch_event_refs)}",
        f"priority_dispatch_missing_ref_count={len(missing_dispatch_refs)}",
        f"priority_dispatch_legacy_rescan={'true' if legacy_dispatch_rescued else 'false'}",
        f"priority_pending_age_seconds={pending_age_seconds}",
        f"candidate_content_status={content_status}",
        f"hard_failure_reason={hard_failure_reason or ('priority_candidate_contract_mismatch' if contract_mismatch else 'priority_durable_observation_missing' if durable_source_missing else 'priority_summary_timeout' if pending_timeout and not should_send else '')}",
        f"hard_failure={'true' if snapshot_publish_failed or contract_mismatch or durable_source_missing or content_blocked or unknown_suppression or (pending_timeout and not should_send) else 'false'}",
        f"last_processed_at={summary['last_processed_at']}",
        f"last_candidate_at={summary['last_candidate_at'] or ''}",
    ]
    destination = os.getenv("GITHUB_OUTPUT")
    if destination:
        with Path(destination).open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines + [f"ledger_changed={'true' if ledger_record.get('changed') else 'false'}"]) + "\n")
    else:
        print("\n".join(lines + [f"ledger_changed={'true' if ledger_record.get('changed') else 'false'}"]))
    write_summary("Official event / price notification decision", summary)


def _safe_nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _dispatch_pending_refs() -> list[str]:
    """Parse only bounded, non-reversible event references from dispatch."""
    raw = os.getenv("DISPATCH_PRIORITY_PENDING_REFS", "[]")
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(value, list):
        return []
    refs: list[str] = []
    for item in value[:100]:
        ref = str(item or "").strip()
        if ref and ref not in refs:
            refs.append(ref[:64])
    return refs


def _dispatch_event_refs() -> list[str]:
    """Parse the versioned all-state event refs from repository dispatch."""
    raw = os.getenv("DISPATCH_PRIORITY_EVENT_REFS", "[]")
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(value, list):
        return []
    refs: list[str] = []
    for item in value[:500]:
        ref = str(item or "").strip()
        if ref and ref not in refs:
            refs.append(ref[:64])
    return refs


def _safe_vendor_importance(event: dict[str, Any]) -> float:
    try:
        return float(event.get("vendor_importance") or 0)
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _event_age_seconds(event: dict[str, Any]) -> float:
    raw = event.get("source_published_at") or event.get("published_at") or event.get("received_at")
    if not raw:
        return 0.0
    try:
        published = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        published = published.replace(tzinfo=published.tzinfo or UTC).astimezone(UTC)
        return max(0.0, (datetime.now(UTC) - published).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return 0.0


def write_send_output(
    sent: bool,
    reason: str,
    *,
    event: dict[str, Any] | None = None,
    notification_status: str | None = None,
    delivered_count: int | None = None,
    failed_count: int | None = None,
    failure_classes: list[str] | tuple[str, ...] | None = None,
    last_telegram_attempt_at: str | None = None,
    last_receipt_status: str | None = None,
    notification_expected: bool | None = None,
) -> None:
    """Expose delivery result to GitHub Actions without failing a safe skip."""
    lines = [f"sent={'true' if sent else 'false'}", f"reason={reason}"]
    status = notification_status or ("delivered" if sent else "suppressed")
    summary = decision_summary(
        event=event,
        scan_status="completed",
        notification_expected=bool(event) if notification_expected is None else notification_expected,
        notification_status=status,
        notification_reason=reason,
        delivered_count=delivered_count,
        failed_count=failed_count,
        last_telegram_attempt_at=last_telegram_attempt_at,
        last_receipt_status=last_receipt_status or status,
    )
    lines.extend([
        f"candidate_type={summary['candidate_type']}",
        f"notification_expected={'true' if summary['notification_expected'] else 'false'}",
        f"notification_status={summary['notification_status']}",
        f"notification_reason={summary['notification_reason']}",
        f"delivered_count={summary['delivered_count'] if summary['delivered_count'] is not None else ''}",
        f"failed_count={summary['failed_count'] if summary['failed_count'] is not None else ''}",
        f"failure_classes={','.join(str(item) for item in (failure_classes or []) if str(item).strip())}",
        f"last_processed_at={summary['last_processed_at']}",
        f"last_candidate_at={summary['last_candidate_at'] or ''}",
        f"last_telegram_attempt_at={summary['last_telegram_attempt_at'] or ''}",
        f"last_receipt_status={summary['last_receipt_status'] or ''}",
    ])
    destination = os.getenv("GITHUB_OUTPUT")
    if destination:
        with Path(destination).open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    else:
        print("\n".join(lines))
    write_summary("Official event / price delivery", summary)


def _write_delivery_output(
    *, trace_id: str, deliveries: tuple[Any, ...], event: dict[str, Any] | None = None,
    budget: dict[str, Any] | None = None, delivery_status: str | None = None,
    delivered_count: int | None = None, failed_count: int | None = None,
    failed_recipient_hashes: list[str] | None = None,
) -> None:
    delivered_count = (
        sum(getattr(item, "status", "") == "delivered" for item in deliveries)
        if delivered_count is None else delivered_count
    )
    failed_count = (
        len(deliveries) - delivered_count
        if failed_count is None else failed_count
    )
    failed_hashes = (
        [getattr(item, "chat_id_hash", "") for item in deliveries if getattr(item, "status", "") != "delivered"]
        if failed_recipient_hashes is None else failed_recipient_hashes
    )
    computed_status = "delivered" if failed_count == 0 and delivered_count else "partial" if delivered_count else "failed"
    lines = [
        f"trace_id={trace_id}",
        f"release_id={os.environ.get('RELEASE_ID', '')}",
        f"delivered_count={delivered_count}",
        f"failed_count={failed_count}",
        f"delivery_status={delivery_status or computed_status}",
        "delivery_mode=text",
        f"failed_recipient_hashes={','.join(failed_hashes)}",
    ]
    if event:
        lines.extend([
            f"alert_id={event.get('notification_id') or event.get('event_cluster_key') or event.get('event_key') or ''}",
            f"notification_id={event.get('notification_id') or ''}",
            f"snapshot_id={event.get('snapshot_id') or ''}",
            f"observation_id={event.get('observation_id') or (event.get('instrument') or {}).get('observation_id') or ''}",
            f"notification_expected={'true' if event.get('notification_expected') else 'false'}",
            f"notification_status={event.get('notification_status') or ''}",
            f"notification_reason={event.get('notification_reason') or '、'.join(event.get('notification_reasons') or [])}",
            f"event_key={event_key(event)}",
            f"risk={canonical_prstk_risk_level(event)}",
            f"ingested_at={event.get('ingested_at') or event.get('received_at') or ''}",
            f"candidate_at={event.get('candidate_at') or ''}",
            f"writer_wait_ms={event.get('writer_wait_ms') if event.get('writer_wait_ms') is not None else ''}",
            f"release_ready_at={event.get('release_ready_at') or ''}",
            f"telegram_attempted_at={event.get('telegram_attempted_at') or ''}",
            f"delivery_result={event.get('delivery_result') or delivery_status or ''}",
            f"delay_reason={event.get('delay_reason') or 'none'}",
        ])
        if str(event.get("source_key") or event.get("source") or "").strip().casefold() == "financialjuice":
            # This is the only FJ state hand-off that crosses the workflow
            # boundary.  It contains a stable private-store reference and
            # release-bound safe fields; the callback allow-list strips
            # everything else before persistence.
            priority_ref = str(event.get("priority_pending_ref") or "").strip()[:64]
            if priority_ref:
                trace = {
                    "priority_pending_ref": priority_ref,
                    "observation_id_hash": event.get("observation_id_hash"),
                    "item_id": event.get("item_id"),
                    "event_cluster_key": event.get("event_cluster_key"),
                    "vendor_importance": event.get("vendor_importance"),
                    "prstk_risk": event.get("prstk_risk"),
                    "notification_reason": event.get("notification_reason"),
                    "release_id": os.environ.get("RELEASE_ID", ""),
                    "snapshot_id": event.get("snapshot_id"),
                    "delivery_status": delivery_status or computed_status,
                }
                lines.append(
                    "financialjuice_delivery_trace="
                    + json.dumps(trace, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
                )
    if budget is not None:
        lines.extend([
            f"alert_budget_allowed={'true' if budget.get('allowed') else 'false'}",
            f"alert_budget_reason={budget.get('reason', '')}",
            f"alert_budget_upgraded={'true' if budget.get('upgraded') else 'false'}",
            f"alert_budget_event_key={budget.get('event_key', '')}",
        ])
    destination = os.getenv("GITHUB_OUTPUT")
    if destination:
        with Path(destination).open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    else:
        print("\n".join(lines))


def send_current_event(expected_key: str | None = None, *, prepared: bool = False) -> bool:
    """Send one verified event, safely skipping it if it changes between steps."""
    if prepared:
        try:
            snapshot = json.loads(Path("site/data/market.json").read_text(encoding="utf-8"))
            event = select_official_event(snapshot)
        except (OSError, UnicodeError, json.JSONDecodeError):
            snapshot, event = {}, None
    else:
        snapshot, event = prepare_snapshot()
    current_key = event_key(event)
    if event and expected_key and current_key != expected_key:
        # The status step may have excluded a suppressed top candidate and
        # selected a later eligible one. Re-select that exact candidate from
        # the same immutable snapshot before declaring the snapshot changed.
        all_items = [
            item
            for container in (snapshot.get("official_events"), snapshot.get("events"))
            if isinstance(container, dict)
            for item in (container.get("items") or [])
            if isinstance(item, dict)
        ]
        expected_event = next(
            (item for item in all_items if event_key(item) == expected_key),
            None,
        )
        if expected_event is not None:
            event = expected_event
            current_key = expected_key
    if not event or (expected_key and current_key != expected_key):
        # A newer event can arrive between the pre-send check and delivery.
        # Keep the workflow green while avoiding stale delivery or a stale lock.
        write_send_output(False, "event_changed_before_delivery", event=event, notification_status="suppressed")
        print("Official event changed before delivery; skipped safely.")
        return False
    # Price signals must be bound to the exact published observation. This is
    # the final guard against a stale event surviving a refresh race.
    if event.get("kind") == "market_signal":
        instrument = event.get("instrument") or {}
        snapshot_id = str(event.get("snapshot_id") or "")
        observation_id = str(event.get("observation_id") or instrument.get("observation_id") or "")
        trace = event.get("source_trace") or {}
        provenance_matches = (
            snapshot_id
            and observation_id
            and str(instrument.get("snapshot_id") or snapshot_id) == snapshot_id
            and str(trace.get("snapshot_id") or snapshot_id) == snapshot_id
            and str(trace.get("observation_id") or observation_id) == observation_id
        )
        if not provenance_matches:
            write_send_output(False, "missing_quote_provenance", event=event, notification_status="suppressed")
            print("Market signal has no snapshot/observation provenance; skipped safely.")
            return False
    ledger = EventLedger()
    gate = verify_release_for_delivery(
        expected_snapshot_id=str(snapshot.get("snapshot_id") or ""),
        public_url=os.environ.get("PUBLIC_RELEASE_URL") or None,
        # Official/index/news alerts only require the relevant market/event
        # artifacts. Research freshness is enforced when a notification
        # actually includes research-specific claims.
        require_production_research=False,
    )
    if not gate.allowed:
        if hasattr(ledger, "record_decision"):
            ledger.record_decision(event, {"allowed": False, "status": "suppressed", "reason": "release_gate_blocked", "reasons": list(gate.errors)})
            ledger.save()
            write_send_output(False, "release_gate_blocked", event=event, notification_status="blocked")
        print("Release gate blocked official event delivery: " + "; ".join(gate.errors))
        return False
    # Semantic investor-theme suppression sits alongside (not inside) the
    # delivery-volume budget.  It keeps every supporting article in the
    # ledger/Mini App while preventing a new URL or headline from replaying
    # the same theme within two hours.
    # ``theme_decision`` is the single material-state arbiter.  If the highest
    # priority candidate is an unchanged duplicate, exclude only that
    # candidate and continue the same queue so a later valid event is not
    # starved by a stale FJ/vendor-priority row.
    fj_priority = is_financialjuice_priority_event(event)
    if hasattr(ledger, "theme_decision") and not fj_priority:
        excluded: set[str] = set()
        while True:
            claim_key = notification_key_for_event(event)
            claim_state = getattr(ledger, "delivery_claims", {}).get(claim_key, {})
            claim_status = str(claim_state.get("status") or "")
            if claim_status == "retryable":
                # A partial delivery is a recipient-level retry, not a new
                # theme notification. Let the claim narrow the sender list.
                break
            if claim_status in {"in_flight", "uncertain"}:
                excluded.add(current_key)
                next_event = select_official_event(snapshot, excluded_event_keys=excluded)
                if next_event is not None:
                    event = next_event
                    current_key = event_key(event)
                    continue
                write_send_output(False, f"notification_{claim_status}", event=event, notification_status="suppressed", last_receipt_status=claim_status)
                return False
            theme = ledger.theme_decision(event)
            ledger.save()
            if theme.get("allowed", False):
                break
            if hasattr(ledger, "record_decision"):
                ledger.record_decision(event, theme)
                ledger.save()
            if theme.get("reason") in {"same_theme_within_2h", "same_theme_unchanged"}:
                excluded.add(current_key)
                next_event = select_official_event(snapshot, excluded_event_keys=excluded)
                if next_event is not None:
                    event = next_event
                    current_key = event_key(event)
                    continue
            write_send_output(
                False,
                f"theme:{theme.get('reason', 'same_theme_unchanged')}",
                event=event,
                notification_status="policy_suppressed",
                notification_expected=False,
            )
            print(f"Official event suppressed by notification theme: {theme.get('reason', 'same_theme_unchanged')}")
            return False
    else:
        # Legacy test/adapter doubles may not expose the new arbiter.  Keep
        # their path safe without resurrecting a production cooldown gate.
        _observe_event(event)
    event_policy = (
        {"allowed": True, "reason": "fj_priority_independent", "market_scope": event_market_scope(event)}
        if fj_priority
        else decide_event_alert_policy(event, ledger.delivery_history())
    )
    if not event_policy.get("allowed", False):
        policy_event = {
            **event,
            "event_key": current_key,
            "alert_lane": "event",
            "market_scope": event_policy.get("market_scope") or event_market_scope(event),
            "event_policy_reason": event_policy.get("reason"),
        }
        if hasattr(ledger, "record_decision"):
            ledger.record_decision(policy_event, {**event_policy, "status": "suppressed", "reasons": [str(event_policy.get("reason") or "event_policy_suppressed")]})
            ledger.save()
        write_send_output(
            False,
            f"event_policy:{event_policy.get('reason', 'suppressed')}",
            event=policy_event,
            notification_status="suppressed",
        )
        print(f"Official event suppressed by event policy: {event_policy.get('reason', 'suppressed')}")
        return False
    event = {
        **event,
        "alert_lane": "event",
        "market_scope": event_policy.get("market_scope") or event_market_scope(event),
        "event_policy_reason": event_policy.get("reason"),
        # The FJ sender re-checks this marker for ordinary (<=8/10) events.
        # High-priority FJ is independent of this gate, but retaining the
        # marker makes the shared sender contract explicit for both lanes.
        "event_policy_allowed": bool(event_policy.get("allowed")),
    }
    budget_event = {
        **event,
        "event_key": current_key,
        "event_policy_allowed": bool(event_policy.get("allowed")),
    }
    budget = (
        {"allowed": True, "reason": "fj_priority_independent", "event_key": current_key}
        if fj_priority
        else decide_alert_budget(budget_event, ledger.delivery_history())
    )
    if not budget.get("allowed", False):
        if hasattr(ledger, "record_decision"):
            ledger.record_decision(budget_event, {**budget, "status": "suppressed", "reasons": [str(budget.get("reason") or "suppressed")]})
            ledger.save()
        write_send_output(
            False,
            f"alert_budget:{budget.get('reason', 'suppressed')}",
            event=event,
            notification_status="suppressed",
        )
        print(f"Official event suppressed by alert budget: {budget.get('reason', 'suppressed')}")
        return False
    settings = get_settings()
    if not settings.telegram_ready:
        raise RuntimeError("缺少 Telegram 設定，無法送出官方事件快訊")
    release_ready_at = datetime.now().astimezone().isoformat()
    event = {**event, "release_ready_at": release_ready_at}
    observation_id = str(event.get("observation_id") or (event.get("instrument") or {}).get("observation_id") or "")
    trace_id = f"official-{observation_id or current_key[:20]}"
    event_id = str(event.get("notification_id") or event.get("event_cluster_key") or event.get("event_key") or observation_id or trace_id)
    caption = build_official_event_brief(event)
    snapshot_id = str(snapshot.get("snapshot_id") or "")
    release_id = gate.release_id or ""
    target_url = alert_mini_app_url(
        settings.dashboard_url,
        alert_id=event_id,
        release_id=release_id,
        snapshot_id=snapshot_id,
        observation_id=observation_id,
    )
    notification_key = notification_key_for_event(event)
    if str(event.get("source_key") or event.get("source") or "").strip().casefold() == "financialjuice":
        # FinancialJuice uses the same release-gated event lane but its
        # vendor-priority contract adds recipient-level replay protection and
        # keeps FJ importance separate from the PRStK risk grade.
        fj_result = deliver_financialjuice_event(
            event,
            release_id=release_id,
            snapshot_id=snapshot_id,
            mini_app_url=settings.dashboard_url,
            release_ready=True,
            token=settings.telegram_bot_token or "",
            chat_ids=settings.telegram_chat_ids,
            delivery_history=_financialjuice_delivery_history(ledger.delivery_history()),
            text_sender=send_text_briefs_audited,
            ledger=ledger,
            run_id=os.getenv("GITHUB_RUN_ID", ""),
        )
        fj_receipts = [row for row in fj_result.get("receipts", []) if isinstance(row, dict)]
        delivered_count = sum(str(row.get("delivery_status") or "") == "delivered" for row in fj_receipts)
        failed_count = len(fj_receipts) - delivered_count
        fj_status = str(fj_result.get("status") or "failed")
        if fj_status not in {"blocked", "already_delivered"}:
            event = {**event, "telegram_attempted_at": datetime.now().astimezone().isoformat()}
        if fj_status == "already_delivered":
            _write_delivery_output(
                trace_id=trace_id, deliveries=(), event={**event, "snapshot_id": snapshot_id}, budget=budget,
                delivery_status="suppressed", delivered_count=0, failed_count=0,
            )
            write_send_output(
                False,
                "financialjuice_already_delivered",
                event=event,
                notification_status="suppressed",
                last_receipt_status="already_delivered",
            )
            return False
        if fj_status == "blocked" and not fj_receipts:
            if hasattr(ledger, "record_decision"):
                ledger.record_decision(event, {"allowed": False, "status": "suppressed", "reason": "financialjuice_delivery_blocked", "reasons": list(fj_result.get("reasons") or [])})
                ledger.save()
            write_send_output(False, "financialjuice_delivery_blocked", event=event, notification_status="blocked")
            return False
        delivery_status = "delivered" if fj_status == "delivered" else "partial" if delivered_count else "failed"
        failed_hashes = [
            str(row.get("recipient_hash") or row.get("chat_id_hash") or "")
            for row in fj_receipts
            if str(row.get("delivery_status") or "") != "delivered"
        ]
        _write_delivery_output(
            trace_id=trace_id, deliveries=(), event={**event, "snapshot_id": snapshot_id}, budget=budget,
            delivery_status=delivery_status, delivered_count=delivered_count,
            failed_count=failed_count, failed_recipient_hashes=failed_hashes,
        )
        if not delivered_count:
            failure_classes = [str(item) for item in (fj_result.get("failure_classes") or []) if str(item).strip()]
            failure_reason = "all_recipients_failed"
            if failure_classes:
                failure_reason = f"{failure_reason}:{','.join(failure_classes)}"
            write_send_output(
                False,
                failure_reason,
                event=event,
                notification_status="failed",
                delivered_count=delivered_count,
                failed_count=failed_count,
                failure_classes=failure_classes,
                last_receipt_status=delivery_status,
            )
            raise RuntimeError("Telegram FinancialJuice delivery failed for every configured recipient")
        ledger.record_delivery(
            {**budget_event, "trace_id": trace_id, "release_id": release_id, "snapshot_id": snapshot_id,
             "notification_id": event.get("notification_id"), "release_ready_at": release_ready_at,
             "telegram_attempted_at": event.get("telegram_attempted_at"), "delivery_result": delivery_status,
             "ingested_at": event.get("ingested_at") or event.get("received_at"),
             "candidate_at": event.get("candidate_at"), "writer_wait_ms": event.get("writer_wait_ms"),
             "delay_reason": event.get("delay_reason") or "none",
             "delivery_status": delivery_status, "notification_key": fj_result.get("notification_key"),
             "delivery_receipts": fj_receipts},
            trace_id=trace_id,
            reason="financialjuice_realtime_monitor",
        )
        ledger.save()
        write_send_output(
            True,
            "sent_partial" if failed_count else "sent",
            event=event,
            notification_status=delivery_status,
            delivered_count=delivered_count,
            failed_count=failed_count,
            last_telegram_attempt_at=event.get("telegram_attempted_at"),
            last_receipt_status=delivery_status,
        )
        return True
    try:
        if content_is_incomplete(event, caption):
            if hasattr(ledger, "record_decision"):
                ledger.record_decision(event, {"allowed": False, "status": "suppressed", "reason": "content_incomplete"})
                ledger.save()
            write_send_output(False, "content_incomplete", event=event, notification_status="suppressed")
            return False
        claim = (
            ledger.claim_notification(
                notification_key,
                recipient_hashes=tuple(recipient_hash(chat_id) for chat_id in settings.telegram_chat_ids),
                run_id=os.getenv("GITHUB_RUN_ID", ""),
            )
            if hasattr(ledger, "claim_notification") else {"status": "claimed"}
        )
        if claim.get("status") != "claimed":
            write_send_output(False, f"notification_{claim.get('status', 'blocked')}", event=event, notification_status="suppressed", last_receipt_status=str(claim.get("status") or "blocked"))
            return False
        pending_hashes = set(str(item) for item in claim.get("pending_recipient_hashes") or [])
        send_chat_ids = settings.telegram_chat_ids
        if pending_hashes:
            send_chat_ids = tuple(
                chat_id for chat_id in settings.telegram_chat_ids if recipient_hash(chat_id) in pending_hashes
            )
        telegram_attempted_at = datetime.now().astimezone().isoformat()
        event = {**event, "telegram_attempted_at": telegram_attempted_at}
        deliveries = send_text_briefs_audited(
            token=settings.telegram_bot_token or "",
            chat_ids=send_chat_ids,
            text=caption,
            dashboard_url=settings.dashboard_url,
            alert_id=event_id,
            release_id=release_id,
            snapshot_id=snapshot_id,
            observation_id=observation_id,
            target_url=target_url,
            prstk_risk_level=canonical_prstk_risk_level(event),
        )
    except (OSError, ValueError) as exc:
        if hasattr(ledger, "complete_notification_claim"):
            ledger.complete_notification_claim(notification_key, uncertain=True)
        write_send_output(False, "text_delivery_failed", event=event, notification_status="failed")
        print(f"Text delivery blocked official event: {type(exc).__name__}")
        return False
    _write_delivery_output(trace_id=trace_id, deliveries=deliveries, event=event, budget=budget)
    delivered_count = sum(item.status == "delivered" for item in deliveries)
    failed_count = len(deliveries) - delivered_count
    if hasattr(ledger, "complete_notification_claim"):
        ledger.complete_notification_claim(
            notification_key,
            delivered_recipient_hashes=tuple(item.chat_id_hash for item in deliveries if item.status == "delivered"),
            failed_recipient_hashes=tuple(item.chat_id_hash for item in deliveries if item.status != "delivered"),
        )
    if not delivered_count:
        failure_classes = sorted({
            str(getattr(item, "error_class", "") or "").strip()
            for item in deliveries
            if str(getattr(item, "error_class", "") or "").strip()
        })
        failure_reason = "all_recipients_failed"
        if failure_classes:
            failure_reason = f"{failure_reason}:{','.join(failure_classes)}"
        write_send_output(
            False,
            failure_reason,
            event=event,
            notification_status="failed",
            delivered_count=delivered_count,
            failed_count=failed_count,
            failure_classes=failure_classes,
            last_receipt_status="failed",
        )
        raise RuntimeError("Telegram delivery failed for every configured recipient")
    ledger.record_delivery(
        {
            **budget_event,
            "trace_id": trace_id,
            "release_id": release_id,
            "snapshot_id": snapshot_id,
            "notification_id": event.get("notification_id"),
            "release_ready_at": release_ready_at,
            "telegram_attempted_at": event.get("telegram_attempted_at"),
            "delivery_result": "delivered" if failed_count == 0 else "partial",
            "ingested_at": event.get("ingested_at") or event.get("received_at"),
            "candidate_at": event.get("candidate_at"),
            "writer_wait_ms": event.get("writer_wait_ms"),
            "delay_reason": event.get("delay_reason") or "none",
            "notification_status": event.get("notification_status") or "eligible",
            "notification_reason": event.get("notification_reason") or "",
            "delivery_status": "delivered" if failed_count == 0 else "partial",
        },
        trace_id=trace_id,
        reason="official_event_monitor",
    )
    ledger.save()
    write_send_output(
        True,
        "sent_partial" if failed_count else "sent",
        event=event,
        notification_status="partial" if failed_count else "delivered",
        delivered_count=delivered_count,
        failed_count=failed_count,
        last_telegram_attempt_at=event.get("telegram_attempted_at"),
        last_receipt_status="partial" if failed_count else "delivered",
    )
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="監測官方重大事件與已核對價格訊號")
    parser.add_argument("--write-status", action="store_true")
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--expected-key")
    parser.add_argument("--prepared", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.write_status:
        snapshot, event = prepare_snapshot(publish=False)
        write_status_output(event, snapshot, publish_snapshot=True)
    if args.send:
        send_current_event(args.expected_key, prepared=args.prepared)
    if not args.write_status and not args.send:
        raise ValueError("請指定 --write-status 或 --send")


if __name__ == "__main__":
    main()
