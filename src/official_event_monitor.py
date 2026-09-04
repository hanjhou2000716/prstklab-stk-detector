"""De-duplicated Telegram alerting for fresh first-party macro releases."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.alert_budget import decide_alert_budget
from src.alert_orchestrator import content_is_incomplete, notification_key_for_event, recipient_hash
from src.config import get_settings
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
from src.financialjuice_notification import deliver_financialjuice_event
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
        remote_rows, remote_health = load_railway_observations()
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
    snapshot["external_observations"] = public_financialjuice_observations(observations, projection["events"])
    snapshot["financialjuice_observations"] = fj_rows
    snapshot["financialjuice_priority_decisions"] = projection["decisions"]
    snapshot["financialjuice_priority_events"] = [
        item for item in projection["events"]
        if str(item.get("notification_status") or "") == "eligible"
    ]
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
    snapshot["financialjuice_release_contract"] = contract
    if contract["ok"]:
        # Preserve non-FJ producers and replace the stale FJ slice with the
        # current release-bound public projection.
        events_container["items"] = replace_financialjuice_event_lane(
            existing_events, projection["events"],
        )
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


def prepare_snapshot() -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Refresh the public snapshot before the Mini App button is sent."""
    snapshot = build_market_snapshot()
    snapshot = _attach_realtime_external_events(snapshot)
    # Select before publishing so the immutable snapshot carries the same
    # candidate decision that the workflow will inspect.  The ledger remains
    # the single durable source of truth; this is only a safe public summary.
    baseline_official = os.getenv("OFFICIAL_EVENT_BASELINE_READY") == "false"
    event = select_official_event(snapshot, baseline_official=baseline_official)
    summary = decision_summary(
        event=event,
        scan_status="completed",
        notification_expected=bool(event),
        notification_status="candidate_ready" if event else "no_event",
        notification_reason="candidate_ready" if event else "no_event",
    )
    snapshot["source_health"] = merge_decision_health(
        snapshot.get("source_health"), "official_event_monitor", summary,
    )
    if not write_snapshot(snapshot):
        # Never evaluate or deliver an event from a run that lost the
        # freshness race with a newer published snapshot.
        print("Snapshot publish skipped; suppressing event delivery.")
        return snapshot, None
    return snapshot, event


def write_status_output(
    event: dict[str, Any] | None,
    snapshot: dict[str, Any] | None = None,
) -> None:
    """Write GitHub Actions outputs without mixing provider diagnostics into them."""
    ledger_record = _observe_event(event)
    should_send = bool(event and ledger_record.get("should_remind", True))
    suppressed_candidates = 0
    # The durable ledger is authoritative, but the first selected candidate
    # can already be known and suppressed while a later candidate is new. Do
    # not let that top candidate prevent the workflow from considering the
    # rest of the same queue (especially a previously delivered FJ item).
    if event and not should_send and isinstance(snapshot, dict):
        excluded = {event_key(event)}
        for _ in range(8):
            next_event = select_official_event(snapshot, excluded_event_keys=excluded)
            if next_event is None:
                break
            suppressed_candidates += 1
            next_record = _observe_event(next_event)
            event = next_event
            ledger_record = next_record
            should_send = bool(next_record.get("should_remind", True))
            excluded.add(event_key(next_event))
            if should_send:
                break
    reason = "candidate_ready" if should_send else "no_new_eligible_candidate" if event else "no_event"
    summary = decision_summary(
        event=event,
        scan_status="completed",
        notification_expected=bool(event),
        notification_status="candidate_ready" if should_send else "suppressed" if event else "no_event",
        notification_reason=reason,
        last_candidate_at=(event or {}).get("candidate_at") if isinstance(event, dict) else None,
    )
    if suppressed_candidates:
        summary["notification_reason"] = "top_candidate_suppressed_later_candidate_considered"
    lines = [
        f"should_send={'true' if should_send else 'false'}",
        f"key={event_key(event) if event else ''}",
        f"snapshot_id={event.get('snapshot_id', '') if event else ''}",
        f"candidate_type={summary['candidate_type']}",
        f"notification_expected={'true' if summary['notification_expected'] else 'false'}",
        f"notification_status={summary['notification_status']}",
        f"notification_reason={summary['notification_reason']}",
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
) -> None:
    """Expose delivery result to GitHub Actions without failing a safe skip."""
    lines = [f"sent={'true' if sent else 'false'}", f"reason={reason}"]
    status = notification_status or ("delivered" if sent else "suppressed")
    summary = decision_summary(
        event=event,
        scan_status="completed",
        notification_expected=bool(event),
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
    if hasattr(ledger, "theme_decision"):
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
                notification_status="suppressed",
            )
            print(f"Official event suppressed by notification theme: {theme.get('reason', 'same_theme_unchanged')}")
            return False
    else:
        # Legacy test/adapter doubles may not expose the new arbiter.  Keep
        # their path safe without resurrecting a production cooldown gate.
        _observe_event(event)
    budget_event = {**event, "event_key": current_key}
    budget = decide_alert_budget(budget_event, ledger.delivery_history())
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
        telegram_attempted_at = datetime.now().astimezone().isoformat()
        event = {**event, "telegram_attempted_at": telegram_attempted_at}
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
        snapshot, event = prepare_snapshot()
        write_status_output(event, snapshot)
    if args.send:
        send_current_event(args.expected_key, prepared=args.prepared)
    if not args.write_status and not args.send:
        raise ValueError("請指定 --write-status 或 --send")


if __name__ == "__main__":
    main()
