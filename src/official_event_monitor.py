"""De-duplicated Telegram alerting for fresh first-party macro releases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
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
            "first_detected_at": item.get("first_detected_at"),
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
            pending_by_ref[ref]["summary_contract_version"] = str(durable.get("summary_contract_version") or "")[:40]
            pending_by_ref[ref]["first_detected_at"] = str(durable.get("first_detected_at") or "")[:80]
            continue
        source = projected_by_ref.get(ref)
        if not isinstance(source, dict):
            continue
        # A current projection that has recovered to ready/deliverable must
        # not be rolled backwards by a stale durable summary_pending row.
        if (
            str(source.get("notification_status") or "") != "content_incomplete"
            or str(source.get("freshness_status") or "") != "fresh"
        ):
            continue
        pending_by_ref[ref] = {
            "source_key": "financialjuice",
            "vendor_importance": source.get("vendor_importance"),
            "notification_status": "content_incomplete",
            "notification_reason": str(durable.get("summary_reason") or "summary_semantics_incomplete")[:120],
            "summary_contract_version": str(durable.get("summary_contract_version") or "")[:40],
            "priority_pending_ref": ref,
            "freshness_status": source.get("freshness_status"),
            "source_published_at": durable.get("source_published_at") or source.get("source_published_at"),
            "received_at": source.get("received_at"),
            "candidate_at": source.get("candidate_at"),
            "first_detected_at": (
                durable.get("first_detected_at") or source.get("first_detected_at")
            ),
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
        def _candidate_key(event: dict[str, Any]) -> tuple[int, int, int, int, int, int]:
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
            return (
                0 if vendor_priority else 1,
                -int(_event_age_seconds(event)),
                taiwan_investor_priority(event, now=now),
                -vendor_importance,
                -official,
                -risk_rank,
            )
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


def select_official_event_batch(
    snapshot: dict[str, Any], *, now: datetime | None = None, max_count: int = 10,
) -> list[dict[str, Any]]:
    """Select a bounded, fair alert batch with reserved slots for live signals."""
    limit = max(1, min(10, int(max_count)))
    total = 0
    for container_name in ("official_events", "events"):
        container = snapshot.get(container_name)
        items = container.get("items", []) if isinstance(container, dict) else []
        if isinstance(items, list):
            total += len(items)
    pool: list[dict[str, Any]] = []
    excluded: set[str] = set()
    for _ in range(max(1, total + 1)):
        event = select_official_event(snapshot, now=now, excluded_event_keys=excluded)
        if event is None:
            break
        key = event_key(event)
        if not key or key in excluded:
            break
        pool.append(event)
        excluded.add(key)
    if len(pool) <= limit:
        return pool

    def is_fj(event: dict[str, Any]) -> bool:
        return str(event.get("source_key") or event.get("source") or "").strip().casefold() == "financialjuice"

    def is_signal(event: dict[str, Any]) -> bool:
        return str(event.get("kind") or "").strip().casefold() == "market_signal"

    def is_official(event: dict[str, Any]) -> bool:
        return bool(
            event.get("official_confirmed")
            or event.get("official_confirmation")
            or str(event.get("source_tier") or "").strip().casefold() == "official"
        )

    fj_rows = [event for event in pool if is_fj(event)]
    fj_rows.sort(key=lambda event: (-_event_age_seconds(event), -_safe_vendor_importance(event)))
    signal_rows = [event for event in pool if not is_fj(event) and is_signal(event)]
    official_rows = [event for event in pool if not is_fj(event) and not is_signal(event) and is_official(event)]
    selected: list[dict[str, Any]] = []
    reserved = [*(signal_rows[:1]), *(official_rows[:1])]
    selected.extend(reserved[:limit])
    remaining = limit - len(selected)
    if remaining > 0:
        priority_cap = min(len(fj_rows), max(0, remaining - (1 if pool and len(reserved) < 2 else 0)))
        selected.extend(fj_rows[:priority_cap])
    used = {event_key(event) for event in selected}
    for event in pool:
        if len(selected) >= limit:
            break
        if event_key(event) not in used:
            selected.append(event)
            used.add(event_key(event))
    return selected


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
    source_key = str(event.get("source_key") or event.get("source") or "").strip().casefold()
    if source_key == "financialjuice":
        from src.financialjuice_notification import financialjuice_public_short_message

        text = financialjuice_public_short_message(event)
    else:
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


def _candidate_delivery_policy(
    event: dict[str, Any],
    ledger: Any,
    *,
    priority: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Use one event-policy and alert-budget decision in preflight and sender."""
    if priority:
        event_policy = {
            "allowed": True,
            "reason": "fj_priority_independent",
            "market_scope": event_market_scope(event),
        }
    else:
        history_method = getattr(ledger, "delivery_history", None)
        history = history_method() if callable(history_method) else []
        event_policy = decide_event_alert_policy(event, history)
    if not event_policy.get("allowed", False):
        return event_policy, {"allowed": False, "reason": "not_evaluated", "event_key": event_key(event)}
    budget_event = {
        **event,
        "event_key": event_key(event),
        "event_policy_allowed": bool(event_policy.get("allowed")),
        "market_scope": event_policy.get("market_scope") or event_market_scope(event),
    }
    if priority:
        budget = {"allowed": True, "reason": "fj_priority_independent", "event_key": event_key(event)}
    else:
        history_method = getattr(ledger, "delivery_history", None)
        history = history_method() if callable(history_method) else []
        budget = decide_alert_budget(budget_event, history)
    return event_policy, budget


def _batch_candidate_preflight(event: dict[str, Any]) -> tuple[str, str, bool]:
    """Independently apply the sender's idempotency and policy gates per row."""
    priority = is_financialjuice_priority_event(event)
    expected = priority or bool(event.get("notification_expected", event.get("should_remind", True)))
    try:
        ledger = EventLedger()
        claims = getattr(ledger, "delivery_claims", {})
        claim_keys = [event_key(event), notification_key_for_event(event)]
        source_key = str(event.get("source_key") or event.get("source") or "").strip().casefold()
        if source_key == "financialjuice":
            claim_keys.extend(financialjuice_notification_aliases(event))
        matches = [
            claims[key]
            for key in dict.fromkeys(claim_keys)
            if key and isinstance(claims, dict) and isinstance(claims.get(key), dict)
        ]
        statuses = [str(item.get("status") or "").strip().casefold() for item in matches]
        if any(status not in {"delivered", "in_flight", "uncertain", "retryable"} for status in statuses):
            return "unknown", "notification_claim_state_unrecognized", expected
        if any(status in {"in_flight", "uncertain"} for status in statuses):
            return "unknown", "notification_claim_uncertain", expected
        if any(status == "delivered" for status in statuses):
            if any(status != "delivered" for status in statuses):
                return "unknown", "notification_claim_state_conflict", expected
            complete = all(
                isinstance(item.get("recipient_hashes"), (list, tuple, set))
                and bool(item.get("recipient_hashes"))
                and bool(set(item.get("recipient_hashes") or ()).issubset(
                    set(item.get("delivered_recipient_hashes") or ())
                ))
                for item in matches if str(item.get("status") or "").casefold() == "delivered"
            )
            return (
                ("suppressed", "already_delivered", False)
                if complete else ("unknown", "delivered_claim_missing_recipient_receipts", expected)
            )
        if priority:
            return "ready", "fj_priority_independent", True
        observation = _observe_event(event)
        if not observation.get("should_remind", True):
            return "suppressed", str(observation.get("reason") or "event_not_due"), False
        if callable(getattr(ledger, "theme_decision", None)):
            theme = ledger.theme_decision(event)
            if not theme.get("allowed", False):
                return "suppressed", f"theme:{theme.get('reason') or 'suppressed'}", False
        policy, budget = _candidate_delivery_policy(event, ledger, priority=False)
        if not policy.get("allowed", False):
            return "suppressed", f"event_policy:{policy.get('reason') or 'suppressed'}", False
        if not budget.get("allowed", False):
            return "suppressed", f"alert_budget:{budget.get('reason') or 'suppressed'}", False
        return "ready", "candidate_ready", True
    except (OSError, RuntimeError):
        return "unknown", "notification_ledger_unavailable", expected
    except (TypeError, ValueError):
        return "unknown", "candidate_policy_unresolved", expected


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
    candidate_decisions: list[dict[str, Any]] = []
    candidate_incident_reason = ""
    shared_ledger_failure = False
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
            candidate_priority = is_financialjuice_priority_event(candidate)
            candidate_should_send = False
            candidate_suppressed = False
            candidate_unknown_suppression = False
            candidate_reason = ""
            candidate_record: dict[str, Any] = {}
            try:
                candidate_caption = build_official_event_brief(candidate)
            except (TypeError, ValueError):
                candidate_caption = ""
            candidate_incomplete = content_is_incomplete(candidate, candidate_caption)
            candidate_expected = candidate_priority or bool(
                candidate.get("notification_expected", candidate.get("should_remind", True))
            )
            candidate_obligation = candidate_expected
            if candidate_incomplete:
                content_blocked = True
                content_status = "incomplete"
                candidate_reason = "content_incomplete_quarantined"
            else:
                content_blocked = False
                content_status = "complete"
                candidate_record = _observe_event(candidate)
                candidate_should_send = bool(
                    candidate_priority or candidate_record.get("should_remind", True)
                )
                candidate_expected = candidate_priority or candidate_should_send
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
                        candidate_reason = (
                            "notification_claim_uncertain"
                            if "uncertain" in claim_statuses
                            else "notification_claim_in_flight"
                        )
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
                    if candidate_should_send and not candidate_priority:
                        policy, budget = _candidate_delivery_policy(
                            candidate, theme_ledger, priority=candidate_priority,
                        )
                        if not policy.get("allowed", False):
                            candidate_should_send = False
                            candidate_suppressed = True
                            candidate_reason = f"event_policy:{policy.get('reason') or 'suppressed'}"
                        elif not budget.get("allowed", False):
                            candidate_should_send = False
                            candidate_suppressed = True
                            candidate_reason = f"alert_budget:{budget.get('reason') or 'suppressed'}"
                except (OSError, RuntimeError):
                    candidate_unknown_suppression = True
                    candidate_should_send = False
                    candidate_reason = "notification_ledger_unavailable"
                except (TypeError, ValueError):
                    candidate_unknown_suppression = True
                    candidate_should_send = False
                    candidate_reason = "candidate_policy_unresolved"
            candidate_expected = (candidate_priority or candidate_obligation) and not candidate_suppressed
            candidate_decisions.append({
                "event_ref": str(
                    candidate.get("priority_pending_ref") or candidate.get("event_ref") or ""
                )[:64],
                "fact_fingerprint": hashlib.sha256(
                    event_key(candidate).encode("utf-8")
                ).hexdigest()[:16] if event_key(candidate) else "",
                "key_fingerprint": hashlib.sha256(
                    event_key(candidate).encode("utf-8")
                ).hexdigest()[:16] if event_key(candidate) else "",
                "notification_key": str(notification_key_for_event(candidate) or "")[:160],
                "summary_contract_version": str(candidate.get("public_summary_version") or "")[:40],
                "summary_fingerprint": hashlib.sha256(
                    candidate_caption.encode("utf-8")
                ).hexdigest() if candidate_caption else "",
                "stage": "content_preflight" if candidate_incomplete else "notification_preflight",
                "expected": candidate_expected,
                "content_status": "incomplete" if candidate_incomplete else "complete",
                "status": (
                    "content_incomplete" if candidate_incomplete
                    else "ready" if candidate_should_send
                    else "unknown" if candidate_unknown_suppression
                    else "suppressed"
                ),
                "reason": candidate_reason or (
                    "candidate_ready" if candidate_should_send
                    else "notification_policy_suppressed" if candidate_suppressed
                    else "notification_policy_not_eligible"
                ),
                "source_published_at": str(candidate.get("source_published_at") or "")[:80],
                "expires_at": str(candidate.get("expires_at") or "")[:80],
                "first_detected_at": str(candidate.get("first_detected_at") or "")[:80],
                "last_progress_at": str(candidate.get("last_progress_at") or "")[:80],
                "recorded_at": datetime.now(UTC).isoformat(),
            })
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
            if candidate_unknown_suppression and not candidate_incident_reason:
                candidate_incident_reason = candidate_reason or "candidate_policy_unresolved"
            if candidate_reason == "notification_ledger_unavailable":
                shared_ledger_failure = True
            if candidate_reason == "notification_ledger_unavailable":
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
        (_pending_detection_age_seconds(item) for item in pending_events),
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
    for pending in pending_events:
        ref = str(pending.get("priority_pending_ref") or pending.get("event_ref") or "").strip()
        if not ref:
            continue
        age = _pending_detection_age_seconds(pending)
        item_status = "summary_timeout" if age > 600 else "summary_pending"
        item_reason = "priority_summary_timeout" if age > 600 else "summary_semantics_incomplete"
        existing_decision = next(
            (row for row in candidate_decisions if str(row.get("event_ref") or "") == ref), None,
        )
        if existing_decision is not None:
            existing_decision.update({
                "stage": "summary",
                "status": item_status,
                "reason": item_reason,
                "first_detected_at": str(pending.get("first_detected_at") or "")[:80],
                "last_progress_at": str(pending.get("last_progress_at") or "")[:80],
                "expires_at": str(pending.get("expires_at") or existing_decision.get("expires_at") or "")[:80],
                "summary_contract_version": str(pending.get("summary_contract_version") or existing_decision.get("summary_contract_version") or "")[:40],
            })
        else:
            candidate_decisions.append({
                "event_ref": ref[:64],
                "fact_fingerprint": "",
                "key_fingerprint": "",
                "notification_key": "",
                "summary_contract_version": str(pending.get("summary_contract_version") or "")[:40],
                "summary_fingerprint": "",
                "stage": "summary",
                "expected": True,
                "content_status": "incomplete",
                "status": item_status,
                "reason": item_reason,
                "source_published_at": str(pending.get("source_published_at") or "")[:80],
                "expires_at": str(pending.get("expires_at") or "")[:80],
                "first_detected_at": str(pending.get("first_detected_at") or "")[:80],
                "last_progress_at": str(pending.get("last_progress_at") or "")[:80],
                "recorded_at": datetime.now(UTC).isoformat(),
            })
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
        notification_expected=bool(
            (event and should_send)
            or any(bool(item.get("expected")) for item in candidate_decisions)
            or pending_events or contract_mismatch or unknown_suppression
        ),
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
    batch_candidates = (
        select_official_event_batch(snapshot)
        if isinstance(snapshot, dict) and should_send else []
    )
    batch_content_eligible: list[dict[str, Any]] = []
    decisions_by_key = {
        str(item.get("key_fingerprint") or ""): item
        for item in candidate_decisions if str(item.get("key_fingerprint") or "")
    }
    for batch_candidate in batch_candidates:
        batch_key = event_key(batch_candidate)
        batch_fingerprint = hashlib.sha256(batch_key.encode("utf-8")).hexdigest()[:16] if batch_key else ""
        prior_decision = decisions_by_key.get(batch_fingerprint)
        if prior_decision and prior_decision.get("status") != "ready":
            continue
        try:
            batch_caption = build_official_event_brief(batch_candidate)
        except (TypeError, ValueError):
            batch_caption = ""
        if content_is_incomplete(batch_candidate, batch_caption):
            if batch_key and not prior_decision:
                row = {
                    "event_ref": str(
                        batch_candidate.get("priority_pending_ref") or batch_candidate.get("event_ref") or ""
                    )[:64],
                    "fact_fingerprint": hashlib.sha256(batch_key.encode("utf-8")).hexdigest()[:16],
                    "key_fingerprint": batch_fingerprint,
                    "notification_key": str(notification_key_for_event(batch_candidate) or "")[:160],
                    "summary_contract_version": str(batch_candidate.get("public_summary_version") or "")[:40],
                    "summary_fingerprint": "",
                    "stage": "content_preflight",
                    "expected": is_financialjuice_priority_event(batch_candidate) or bool(
                        batch_candidate.get("notification_expected", batch_candidate.get("should_remind", True))
                    ),
                    "content_status": "incomplete",
                    "status": "content_incomplete",
                    "reason": "content_incomplete_quarantined",
                    "source_published_at": str(batch_candidate.get("source_published_at") or "")[:80],
                    "expires_at": str(batch_candidate.get("expires_at") or "")[:80],
                    "first_detected_at": str(batch_candidate.get("first_detected_at") or "")[:80],
                    "last_progress_at": str(batch_candidate.get("last_progress_at") or "")[:80],
                    "recorded_at": datetime.now(UTC).isoformat(),
                }
                candidate_decisions.append(row)
                decisions_by_key[batch_fingerprint] = row
            continue
        if prior_decision:
            batch_content_eligible.append(batch_candidate)
            continue
        item_status, item_reason, item_expected = _batch_candidate_preflight(batch_candidate)
        row = {
            "event_ref": str(
                batch_candidate.get("priority_pending_ref") or batch_candidate.get("event_ref") or ""
            )[:64],
            "fact_fingerprint": batch_fingerprint,
            "key_fingerprint": batch_fingerprint,
            "notification_key": str(notification_key_for_event(batch_candidate) or "")[:160],
            "summary_contract_version": str(batch_candidate.get("public_summary_version") or "")[:40],
            "summary_fingerprint": hashlib.sha256(batch_caption.encode("utf-8")).hexdigest(),
            "stage": "notification_preflight",
            "expected": item_expected,
            "content_status": "complete",
            "status": item_status,
            "reason": item_reason,
            "source_published_at": str(batch_candidate.get("source_published_at") or "")[:80],
            "expires_at": str(batch_candidate.get("expires_at") or "")[:80],
            "first_detected_at": str(batch_candidate.get("first_detected_at") or "")[:80],
            "last_progress_at": str(batch_candidate.get("last_progress_at") or "")[:80],
            "recorded_at": datetime.now(UTC).isoformat(),
        }
        candidate_decisions.append(row)
        decisions_by_key[batch_fingerprint] = row
        if item_status == "unknown" and not candidate_incident_reason:
            candidate_incident_reason = item_reason
        if item_reason == "notification_ledger_unavailable":
            shared_ledger_failure = True
        if item_status == "ready":
            batch_content_eligible.append(batch_candidate)
    batch_candidates = batch_content_eligible
    if shared_ledger_failure:
        batch_candidates = []
        should_send = False
        status = "blocked"
        reason = "notification_ledger_unavailable"
    if should_send and event:
        expected_key = event_key(event)
        if expected_key and all(event_key(item) != expected_key for item in batch_candidates):
            batch_candidates = [event, *batch_candidates[:9]]
    batch_candidates = batch_candidates[:10]
    batch_rows = [
        {
            "schema_version": "official-event-batch-candidate-v1",
            "key": event_key(item),
            "notification_key": notification_key_for_event(item),
            # The immutable release projection uses this canonical key as its
            # public notification ID. Source observation IDs remain provenance.
            "notification_id": notification_key_for_event(item),
            "snapshot_id": str(
                item.get("snapshot_id")
                or (snapshot.get("snapshot_id") if isinstance(snapshot, dict) else "")
                or ""
            ),
            "observation_id": str(
                item.get("observation_id")
                or ((item.get("instrument") or {}).get("observation_id") if isinstance(item.get("instrument"), dict) else "")
                or ""
            ),
            "canonical_fact_key": str(item.get("canonical_fact_key") or ""),
            "material_fact_version": str(item.get("material_fact_version") or item.get("fact_version") or ""),
            "event_ref": str(item.get("priority_pending_ref") or item.get("event_ref") or ""),
            "source_key": str(item.get("source_key") or item.get("source") or "").strip().casefold(),
            "kind": str(item.get("kind") or ""),
        }
        for item in batch_candidates
        if event_key(item) and notification_key_for_event(item)
    ]
    batch_targets = [
        {
            "notification_id": row["notification_id"],
            "snapshot_id": row["snapshot_id"],
            "observation_id": row["observation_id"],
        }
        for row in batch_rows
        if row["notification_id"]
    ]
    batch_contract_mismatch = bool(batch_candidates) and (
        len(batch_rows) != len(batch_candidates)
        or len(batch_targets) != len(batch_rows)
        or len({row["notification_key"] for row in batch_rows}) != len(batch_rows)
    )
    lines = [
        f"should_send={'true' if should_send else 'false'}",
        f"key={event_key(event) if event else ''}",
        f"notification_key={notification_key_for_event(event) if event else ''}",
        f"snapshot_publish_failed={'true' if snapshot_publish_failed else 'false'}",
        f"notification_id={notification_key_for_event(event) if event else ''}",
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
        f"batch_count={len(batch_rows)}",
        f"batch_candidates={json.dumps(batch_rows, separators=(',', ':'), sort_keys=True)}",
        f"candidate_results={json.dumps(candidate_decisions, separators=(',', ':'), sort_keys=True)}",
        f"degraded_candidate_count={sum(1 for item in candidate_decisions if item.get('status') in {'content_incomplete', 'unknown', 'summary_pending', 'summary_timeout'})}",
        f"batch_alert_targets={json.dumps(batch_targets, separators=(',', ':'), sort_keys=True)}",
        f"candidate_incident_reason={candidate_incident_reason}",
        f"candidate_incident_count={sum(1 for item in candidate_decisions if item.get('status') in {'unknown', 'content_incomplete', 'summary_pending', 'summary_timeout'})}",
        f"hard_failure_reason={hard_failure_reason or ('notification_batch_contract_mismatch' if batch_contract_mismatch else 'priority_candidate_contract_mismatch' if contract_mismatch else 'priority_durable_observation_missing' if durable_source_missing else 'notification_ledger_unavailable' if shared_ledger_failure else '')}",
        f"hard_failure={'true' if snapshot_publish_failed or batch_contract_mismatch or contract_mismatch or durable_source_missing or shared_ledger_failure else 'false'}",
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


def _pending_detection_age_seconds(event: dict[str, Any]) -> float:
    """Measure summary work from its first detection, never from source age."""
    raw = next((
        event.get(field) for field in (
            "first_detected_at", "summary_first_seen_at", "candidate_at", "received_at",
        ) if event.get(field)
    ), None)
    if not raw:
        return 0.0
    try:
        detected = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        detected = detected.replace(tzinfo=detected.tzinfo or UTC).astimezone(UTC)
        return max(0.0, (datetime.now(UTC) - detected).total_seconds())
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
    actual_notification_key: str = "",
) -> None:
    """Expose delivery result to GitHub Actions without failing a safe skip."""
    lines = [
        f"sent={'true' if sent else 'false'}", f"reason={reason}",
        f"notification_key={actual_notification_key.strip()}",
    ]
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
    actual_notification_key: str = "",
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
        f"notification_key={actual_notification_key.strip()}",
        f"release_id={os.environ.get('RELEASE_ID', '')}",
        f"delivered_count={delivered_count}",
        f"failed_count={failed_count}",
        f"delivery_status={delivery_status or computed_status}",
        "delivery_mode=text",
        f"failed_recipient_hashes={','.join(failed_hashes)}",
    ]
    if event:
        public_notification_id = notification_key_for_event(event)
        lines.extend([
            f"alert_id={public_notification_id or event.get('notification_id') or event.get('event_cluster_key') or event.get('event_key') or ''}",
            f"notification_id={public_notification_id or event.get('notification_id') or ''}",
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


def send_current_event(
    expected_key: str | None = None, *, prepared: bool = False, exact_candidate: bool = False,
    expected_binding: Mapping[str, str] | None = None,
) -> bool:
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
    if expected_binding:
        actual_notification_key = notification_key_for_event(event)
        actual_snapshot_id = str(event.get("snapshot_id") or snapshot.get("snapshot_id") or "")
        actual_observation_id = str(
            event.get("observation_id")
            or ((event.get("instrument") or {}).get("observation_id") if isinstance(event.get("instrument"), dict) else "")
            or ""
        )
        expected_fact_key = expected_binding.get("canonical_fact_key", "")
        expected_fact_version = expected_binding.get("material_fact_version", "")
        expected_observation_id = expected_binding.get("observation_id", "")
        expected_source_key = expected_binding.get("source_key", "")
        mismatches = []
        if not actual_notification_key or actual_notification_key != expected_binding.get("notification_key"):
            mismatches.append("notification_key")
        if actual_notification_key != expected_binding.get("notification_id"):
            mismatches.append("public_notification_id")
        if not actual_snapshot_id or actual_snapshot_id != expected_binding.get("snapshot_id"):
            mismatches.append("snapshot_id")
        if expected_observation_id and actual_observation_id != expected_observation_id:
            mismatches.append("observation_id")
        actual_source_key = str(event.get("source_key") or event.get("source") or "").strip().casefold()
        if expected_source_key and actual_source_key != expected_source_key:
            mismatches.append("source_key")
        if expected_fact_key and str(event.get("canonical_fact_key") or "") != expected_fact_key:
            mismatches.append("canonical_fact_key")
        if expected_fact_version and str(event.get("material_fact_version") or event.get("fact_version") or "") != expected_fact_version:
            mismatches.append("material_fact_version")
        if mismatches:
            reason = "batch_release_identity_mismatch:" + ",".join(mismatches)
            write_send_output(False, reason, event=event, notification_status="blocked")
            print("Official event batch identity changed before delivery; skipped safely.")
            return False
    # Public release manifests derive notification_id from this exact stable
    # delivery identity. Normalize the in-memory event to that value too, so
    # the Telegram deep link cannot keep an ingress-only fj-item identifier.
    public_notification_id = notification_key_for_event(event)
    if public_notification_id:
        event = {**event, "notification_id": public_notification_id}
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
                if exact_candidate:
                    write_send_output(False, f"notification_{claim_status}", event=event, notification_status="suppressed", last_receipt_status=claim_status)
                    return False
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
                if exact_candidate:
                    write_send_output(
                        False,
                        f"theme:{theme.get('reason', 'same_theme_unchanged')}",
                        event=event,
                        notification_status="policy_suppressed",
                        notification_expected=False,
                    )
                    return False
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
    event_policy, budget = _candidate_delivery_policy(
        event, ledger, priority=fj_priority,
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
            notification_status="policy_suppressed",
            notification_expected=False,
        )
        print(f"Official event suppressed by event policy: {event_policy.get('reason', 'suppressed')}")
        return False
    event = {
        **event,
        "alert_lane": "event",
        "market_scope": event_policy.get("market_scope") or event_market_scope(event),
        "event_policy_reason": event_policy.get("reason"),
        # FJ priority remains independent of the ordinary event policy.
        "event_policy_allowed": bool(event_policy.get("allowed")),
    }
    budget_event = {
        **event,
        "event_key": current_key,
        "event_policy_allowed": bool(event_policy.get("allowed")),
    }
    if not budget.get("allowed", False):
        if hasattr(ledger, "record_decision"):
            ledger.record_decision(budget_event, {**budget, "status": "suppressed", "reasons": [str(budget.get("reason") or "suppressed")]})
            ledger.save()
        write_send_output(
            False,
            f"alert_budget:{budget.get('reason', 'suppressed')}",
            event=event,
            notification_status="policy_suppressed",
            notification_expected=False,
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
    event_id = str(
        notification_key_for_event(event)
        or event.get("notification_id")
        or event.get("event_cluster_key")
        or event.get("event_key")
        or observation_id
        or trace_id
    )
    caption = build_official_event_brief(event)
    snapshot_id = str(event.get("snapshot_id") or snapshot.get("snapshot_id") or "")
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
        actual_claim_key = str(fj_result.get("notification_key") or "").strip()
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
                actual_notification_key=actual_claim_key,
            )
            write_send_output(
                False,
                "financialjuice_already_delivered",
                event=event,
                notification_status="suppressed",
                last_receipt_status="already_delivered",
                actual_notification_key=actual_claim_key,
            )
            return False
        if fj_status == "blocked" and not fj_receipts:
            if hasattr(ledger, "record_decision"):
                ledger.record_decision(event, {"allowed": False, "status": "suppressed", "reason": "financialjuice_delivery_blocked", "reasons": list(fj_result.get("reasons") or [])})
                ledger.save()
            write_send_output(
                False, "financialjuice_delivery_blocked", event=event, notification_status="blocked",
                actual_notification_key=actual_claim_key,
            )
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
            actual_notification_key=actual_claim_key,
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
                actual_notification_key=actual_claim_key,
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
            actual_notification_key=actual_claim_key,
        )
        return True
    actual_claim_key = ""
    try:
        if content_is_incomplete(event, caption):
            if hasattr(ledger, "record_decision"):
                ledger.record_decision(event, {"allowed": False, "status": "suppressed", "reason": "content_incomplete"})
                ledger.save()
            write_send_output(False, "content_incomplete", event=event, notification_status="suppressed")
            return False
        if hasattr(ledger, "claim_notification"):
            claim = ledger.claim_notification(
                notification_key,
                recipient_hashes=tuple(recipient_hash(chat_id) for chat_id in settings.telegram_chat_ids),
                run_id=os.getenv("GITHUB_RUN_ID", ""),
            )
        else:
            claim = {
                "status": "blocked", "reason": "notification_claim_store_unavailable",
                "notification_key": "",
            }
        actual_claim_key = str(claim.get("notification_key") or "").strip()
        if claim.get("status") == "claimed" and actual_claim_key != notification_key:
            if hasattr(ledger, "complete_notification_claim") and actual_claim_key:
                ledger.complete_notification_claim(actual_claim_key, uncertain=True)
            write_send_output(
                False, "notification_claim_identity_mismatch", event=event,
                notification_status="blocked", actual_notification_key=actual_claim_key,
            )
            return False
        if claim.get("status") != "claimed":
            write_send_output(
                False, f"notification_{claim.get('status', 'blocked')}", event=event,
                notification_status="suppressed", last_receipt_status=str(claim.get("status") or "blocked"),
                actual_notification_key=actual_claim_key,
            )
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
        if hasattr(ledger, "complete_notification_claim") and actual_claim_key:
            ledger.complete_notification_claim(actual_claim_key, uncertain=True)
        write_send_output(
            False, "text_delivery_failed", event=event, notification_status="failed",
            actual_notification_key=actual_claim_key,
        )
        print(f"Text delivery blocked official event: {type(exc).__name__}")
        return False
    _write_delivery_output(
        trace_id=trace_id, deliveries=deliveries, event=event, budget=budget,
        actual_notification_key=actual_claim_key,
    )
    delivered_count = sum(item.status == "delivered" for item in deliveries)
    failed_count = len(deliveries) - delivered_count
    if hasattr(ledger, "complete_notification_claim"):
        ledger.complete_notification_claim(
            actual_claim_key,
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
            "notification_key": actual_claim_key,
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
        actual_notification_key=actual_claim_key,
    )
    return True


def _read_action_outputs(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return result
    for line in lines:
        key, separator, value = line.partition("=")
        if separator and key and key.replace("_", "").isalnum():
            result[key] = value
    return result


def send_current_event_batch(expected_file: Path, *, prepared: bool = False) -> list[dict[str, Any]]:
    """Send each exact preflighted candidate and preserve per-event evidence."""
    try:
        candidates = json.loads(expected_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"batch candidate file unreadable: {type(exc).__name__}") from exc
    if not isinstance(candidates, list) or not candidates or len(candidates) > 10:
        raise ValueError("batch candidate file must contain 1..10 records")
    seen: set[str] = set()
    normalized: list[dict[str, str]] = []
    for item in candidates:
        if not isinstance(item, dict):
            raise ValueError("batch candidate record is invalid")
        if item.get("schema_version") != "official-event-batch-candidate-v1":
            raise ValueError("batch candidate schema version is missing or unsupported")
        key = str(item.get("key") or "").strip()
        notification_key = str(item.get("notification_key") or "").strip()
        notification_id = str(item.get("notification_id") or "").strip()
        snapshot_id = str(item.get("snapshot_id") or "").strip()
        if not key or not notification_key or not notification_id or not snapshot_id or key in seen:
            raise ValueError("batch candidate identity is missing or duplicated")
        seen.add(key)
        normalized.append({
            "key": key,
            "notification_key": notification_key,
            "notification_id": notification_id,
            "snapshot_id": snapshot_id,
            "observation_id": str(item.get("observation_id") or ""),
            "canonical_fact_key": str(item.get("canonical_fact_key") or ""),
            "material_fact_version": str(item.get("material_fact_version") or ""),
            "event_ref": str(item.get("event_ref") or ""),
            "source_key": str(item.get("source_key") or "").strip().casefold(),
        })
        if normalized[-1]["source_key"] == "financialjuice" and (
            not normalized[-1]["canonical_fact_key"] or not normalized[-1]["material_fact_version"]
        ):
            raise ValueError("FinancialJuice batch fact identity is incomplete")

    results: list[dict[str, Any]] = []
    original_output = os.environ.get("GITHUB_OUTPUT")
    original_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    with tempfile.TemporaryDirectory(prefix="official-event-batch-") as temp_dir:
        root = Path(temp_dir)
        try:
            for index, candidate in enumerate(normalized):
                output_path = root / f"event-{index}.out"
                summary_path = root / f"event-{index}.summary"
                os.environ["GITHUB_OUTPUT"] = str(output_path)
                os.environ["GITHUB_STEP_SUMMARY"] = str(summary_path)
                error_type = ""
                try:
                    send_current_event(
                        candidate["key"], prepared=prepared, exact_candidate=True,
                        expected_binding=candidate,
                    )
                except Exception as exc:
                    # A failed event does not starve later independent candidates.
                    error_type = type(exc).__name__
                    print(f"Event batch item failed safely: key={candidate['key'][:80]} error={error_type}")
                values = _read_action_outputs(output_path)
                actual_notification_key = values.get("notification_key", "").strip()
                if not actual_notification_key:
                    error_type = error_type or "sender_notification_key_missing"
                elif actual_notification_key != candidate["notification_key"]:
                    error_type = error_type or "notification_key_mismatch"
                trace_id = values.get("trace_id", "")
                delivery_status = values.get("delivery_status", "")
                results.append({
                    **candidate,
                    "notification_key": actual_notification_key,
                    "sent": values.get("sent") == "true",
                    "reason": values.get("reason", "sender_output_missing")[:160],
                    "notification_status": values.get("notification_status", "unknown")[:64],
                    "delivery_status": delivery_status[:32],
                    "trace_id": trace_id[:160],
                    "release_id": values.get("release_id", os.environ.get("RELEASE_ID", ""))[:160],
                    "snapshot_id": values.get("snapshot_id", candidate["snapshot_id"])[:160],
                    "alert_id": values.get("alert_id", candidate["notification_id"])[:160],
                    "delivery_mode": values.get("delivery_mode", "text")[:32],
                    "delivered_count": _safe_nonnegative_int(values.get("delivered_count")),
                    "failed_count": _safe_nonnegative_int(values.get("failed_count")),
                    "failed_recipient_hashes": [
                        item for item in values.get("failed_recipient_hashes", "").split(",")
                        if len(item) == 12 and all(char in "0123456789abcdef" for char in item)
                    ],
                    "financialjuice_delivery_trace": values.get("financialjuice_delivery_trace", "")[:2000],
                    "receipt_required": bool(actual_notification_key and trace_id and delivery_status),
                    "error_type": error_type,
                })
        finally:
            if original_output is None:
                os.environ.pop("GITHUB_OUTPUT", None)
            else:
                os.environ["GITHUB_OUTPUT"] = original_output
            if original_summary is None:
                os.environ.pop("GITHUB_STEP_SUMMARY", None)
            else:
                os.environ["GITHUB_STEP_SUMMARY"] = original_summary

    destination = Path(os.getenv("OFFICIAL_EVENT_BATCH_RESULTS_PATH") or Path(tempfile.gettempdir()) / "official-event-batch-results.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(results, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    temporary.replace(destination)
    receipt_rows = [row for row in results if row["receipt_required"]]
    delivered = sum(row["delivery_status"] == "delivered" for row in receipt_rows)
    partial = sum(row["delivery_status"] == "partial" for row in receipt_rows)
    failed = sum(row["delivery_status"] == "failed" or bool(row["error_type"]) for row in results)
    delivered_recipients = sum(row["delivered_count"] for row in receipt_rows)
    failed_recipients = sum(row["failed_count"] for row in receipt_rows)
    status = "failed" if failed else "partial" if partial else "delivered" if delivered else "no_delivery"
    delivery_status = (
        "partial" if delivered_recipients and failed_recipients
        else "failed" if failed_recipients or failed
        else "partial" if partial
        else "delivered" if delivered_recipients
        else "suppressed"
    )
    summary = {
        "schema_version": "official-event-delivery-batch-v1",
        "candidate_count": len(results),
        "receipt_required_count": len(receipt_rows),
        "delivered_event_count": delivered,
        "partial_event_count": partial,
        "failed_event_count": failed,
        "delivered_recipient_count": delivered_recipients,
        "failed_recipient_count": failed_recipients,
    }
    output_values = {
        "batch_results_file": str(destination),
        "batch_count": len(results),
        "attempted_count": len(receipt_rows),
        "delivered_event_count": delivered,
        "partial_event_count": partial,
        "failed_event_count": failed,
        "delivery_status": delivery_status,
        "delivered_count": delivered_recipients,
        "failed_count": failed_recipients,
        "sent": "true" if receipt_rows else "false",
        "notification_expected": "true",
        "notification_status": status,
        "reason": "batch_delivery_results_recorded",
    }
    action_output_path = os.getenv("GITHUB_OUTPUT")
    output_lines = [f"{key}={value}" for key, value in output_values.items()]
    if action_output_path:
        with Path(action_output_path).open("a", encoding="utf-8") as handle:
            handle.write("\n".join(output_lines) + "\n")
    else:
        print("\n".join(output_lines))
    write_summary("Official event batch delivery", summary)
    # The workflow's incident reconciler owns paced alerting for isolated item
    # failures. Keep the batch step successful after recording every result so
    # a single event cannot prevent unrelated rows from being attempted.
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="監測官方重大事件與已核對價格訊號")
    parser.add_argument("--write-status", action="store_true")
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--expected-key")
    parser.add_argument("--send-batch", action="store_true")
    parser.add_argument("--expected-keys-file", type=Path)
    parser.add_argument("--prepared", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.write_status:
        snapshot, event = prepare_snapshot(publish=False)
        write_status_output(event, snapshot, publish_snapshot=True)
    if args.send:
        send_current_event(args.expected_key, prepared=args.prepared)
    if args.send_batch:
        if args.expected_keys_file is None:
            raise ValueError("--send-batch requires --expected-keys-file")
        send_current_event_batch(args.expected_keys_file, prepared=args.prepared)
    if not args.write_status and not args.send and not args.send_batch:
        raise ValueError("請指定 --write-status、--send 或 --send-batch")


if __name__ == "__main__":
    main()
