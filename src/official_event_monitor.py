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
    snapshot: dict[str, Any], now: datetime | None = None, *, baseline_official: bool = False
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
        return candidates[0]

    signals = [event for event in snapshot.get("events", {}).get("items", []) if event.get("kind") == "market_signal"]
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
    validate_brief(text)
    return text


def prepare_snapshot() -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Refresh the public snapshot before the Mini App button is sent."""
    snapshot = build_market_snapshot()
    snapshot = _attach_realtime_external_events(snapshot)
    if not write_snapshot(snapshot):
        # Never evaluate or deliver an event from a run that lost the
        # freshness race with a newer published snapshot.
        print("Snapshot publish skipped; suppressing event delivery.")
        return snapshot, None
    # The first deployment observes current official headlines but avoids
    # immediately replaying them as alerts. Price signals remain eligible.
    baseline_official = os.getenv("OFFICIAL_EVENT_BASELINE_READY") == "false"
    return snapshot, select_official_event(snapshot, baseline_official=baseline_official)


def write_status_output(event: dict[str, Any] | None) -> None:
    """Write GitHub Actions outputs without mixing provider diagnostics into them."""
    ledger_record = _observe_event(event)
    should_send = bool(event and ledger_record.get("should_remind", True))
    lines = [
        f"should_send={'true' if should_send else 'false'}",
        f"key={event_key(event)}",
        f"snapshot_id={event.get('snapshot_id', '') if event else ''}",
    ]
    destination = os.getenv("GITHUB_OUTPUT")
    if destination:
        with Path(destination).open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines + [f"ledger_changed={'true' if ledger_record.get('changed') else 'false'}"]) + "\n")
    else:
        print("\n".join(lines + [f"ledger_changed={'true' if ledger_record.get('changed') else 'false'}"]))


def write_send_output(sent: bool, reason: str) -> None:
    """Expose delivery result to GitHub Actions without failing a safe skip."""
    lines = [f"sent={'true' if sent else 'false'}", f"reason={reason}"]
    destination = os.getenv("GITHUB_OUTPUT")
    if destination:
        with Path(destination).open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    else:
        print("\n".join(lines))


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
            f"alert_id={event.get('event_cluster_key') or event.get('event_key') or ''}",
            f"snapshot_id={event.get('snapshot_id') or ''}",
            f"observation_id={event.get('observation_id') or (event.get('instrument') or {}).get('observation_id') or ''}",
            f"notification_expected={'true' if event.get('notification_expected') else 'false'}",
            f"notification_status={event.get('notification_status') or ''}",
            f"notification_reason={event.get('notification_reason') or '、'.join(event.get('notification_reasons') or [])}",
            f"event_key={event_key(event)}",
            f"risk={canonical_prstk_risk_level(event)}",
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
    if not event or (expected_key and current_key != expected_key):
        # A newer event can arrive between the pre-send check and delivery.
        # Keep the workflow green while avoiding stale delivery or a stale lock.
        write_send_output(False, "event_changed_before_delivery")
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
            write_send_output(False, "missing_quote_provenance")
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
        write_send_output(False, "release_gate_blocked")
        print("Release gate blocked official event delivery: " + "; ".join(gate.errors))
        return False
    # Semantic investor-theme suppression sits alongside (not inside) the
    # delivery-volume budget.  It keeps every supporting article in the
    # ledger/Mini App while preventing a new URL or headline from replaying
    # the same theme within two hours.
    if hasattr(ledger, "theme_decision"):
        theme = ledger.theme_decision(event)
        ledger.save()
        if not theme.get("allowed", False):
            if hasattr(ledger, "record_decision"):
                ledger.record_decision(event, theme)
                ledger.save()
            write_send_output(False, f"theme:{theme.get('reason', 'same_theme_within_2h')}")
            print(f"Official event suppressed by notification theme: {theme.get('reason', 'same_theme_within_2h')}")
            return False
    cooldown_record = _observe_event(event)
    if not cooldown_record.get("should_remind", True):
        write_send_output(False, "event_cooldown")
        print("Official event is inside the shared 30-minute cooldown; skipped safely.")
        return False
    budget_event = {**event, "event_key": current_key}
    budget = decide_alert_budget(budget_event, ledger.delivery_history())
    if not budget.get("allowed", False):
        if hasattr(ledger, "record_decision"):
            ledger.record_decision(budget_event, {**budget, "status": "suppressed", "reasons": [str(budget.get("reason") or "suppressed")]})
            ledger.save()
        write_send_output(False, f"alert_budget:{budget.get('reason', 'suppressed')}")
        print(f"Official event suppressed by alert budget: {budget.get('reason', 'suppressed')}")
        return False
    settings = get_settings()
    if not settings.telegram_ready:
        raise RuntimeError("缺少 Telegram 設定，無法送出官方事件快訊")
    observation_id = str(event.get("observation_id") or (event.get("instrument") or {}).get("observation_id") or "")
    trace_id = f"official-{observation_id or current_key[:20]}"
    event_id = str(event.get("event_cluster_key") or event.get("event_key") or observation_id or trace_id)
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
            write_send_output(False, "financialjuice_already_delivered")
            return False
        if fj_status == "blocked" and not fj_receipts:
            if hasattr(ledger, "record_decision"):
                ledger.record_decision(event, {"allowed": False, "status": "suppressed", "reason": "financialjuice_delivery_blocked", "reasons": list(fj_result.get("reasons") or [])})
                ledger.save()
            write_send_output(False, "financialjuice_delivery_blocked")
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
            write_send_output(False, "all_recipients_failed")
            raise RuntimeError("Telegram FinancialJuice delivery failed for every configured recipient")
        ledger.record_delivery(
            {**budget_event, "trace_id": trace_id, "release_id": release_id, "snapshot_id": snapshot_id,
             "delivery_status": delivery_status, "notification_key": fj_result.get("notification_key"),
             "delivery_receipts": fj_receipts},
            trace_id=trace_id,
            reason="financialjuice_realtime_monitor",
        )
        ledger.save()
        write_send_output(True, "sent_partial" if failed_count else "sent")
        return True
    try:
        deliveries = send_text_briefs_audited(
            token=settings.telegram_bot_token or "",
            chat_ids=settings.telegram_chat_ids,
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
        write_send_output(False, "text_delivery_failed")
        print(f"Text delivery blocked official event: {type(exc).__name__}")
        return False
    _write_delivery_output(trace_id=trace_id, deliveries=deliveries, event=event, budget=budget)
    delivered_count = sum(item.status == "delivered" for item in deliveries)
    failed_count = len(deliveries) - delivered_count
    if not delivered_count:
        write_send_output(False, "all_recipients_failed")
        raise RuntimeError("Telegram delivery failed for every configured recipient")
    ledger.record_delivery(
        {
            **budget_event,
            "trace_id": trace_id,
            "release_id": release_id,
            "snapshot_id": snapshot_id,
            "notification_status": event.get("notification_status") or "eligible",
            "notification_reason": event.get("notification_reason") or "",
            "delivery_status": "delivered" if failed_count == 0 else "partial",
        },
        trace_id=trace_id,
        reason="official_event_monitor",
    )
    ledger.save()
    write_send_output(True, "sent_partial" if failed_count else "sent")
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
        _, event = prepare_snapshot()
        write_status_output(event)
    if args.send:
        send_current_event(args.expected_key, prepared=args.prepared)
    if not args.write_status and not args.send:
        raise ValueError("請指定 --write-status 或 --send")


if __name__ == "__main__":
    main()
