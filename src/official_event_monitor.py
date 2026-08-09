"""De-duplicated Telegram alerting for fresh first-party macro releases."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.alert_budget import decide_alert_budget
from src.alert_card_renderer import RendererError, render_alert_card
from src.config import get_settings
from src.event_ledger import EventLedger, canonical_event_key
from src.market_data import build_market_snapshot
from src.refresh_market_data import write_snapshot
from src.release_gate import verify_release_for_delivery
from src.telegram_client import send_photo_briefs, summarize_photo_deliveries, validate_brief


def _is_taiwan_market_window(now: datetime | None = None) -> bool:
    """Return whether Taiwan-session price alerts should lead the queue."""
    local_now = now or datetime.now(ZoneInfo("Asia/Taipei"))
    if local_now.tzinfo is None:
        local_now = local_now.replace(tzinfo=ZoneInfo("Asia/Taipei"))
    else:
        local_now = local_now.astimezone(ZoneInfo("Asia/Taipei"))
    return local_now.weekday() < 5 and time(8, 45) <= local_now.time() <= time(13, 30)


def select_official_event(
    snapshot: dict[str, Any], now: datetime | None = None, *, baseline_official: bool = False
) -> dict[str, Any] | None:
    """Select a verified official release, then a threshold price signal.

    The price signal fallback is constrained by ``event_alerts`` thresholds, so
    routine price refreshes never become Telegram notifications.
    """
    items = snapshot.get("official_events", {}).get("items", [])
    detailed_events = snapshot.get("events", {}).get("items", [])
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
                return detailed or item
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
                return detailed
    signals = [event for event in snapshot.get("events", {}).get("items", []) if event.get("kind") == "market_signal"]
    if _is_taiwan_market_window(now):
        # During the Taiwan session, a broad Taiwan price signal has priority.
        # Commodity/crypto moves remain visible in the Mini App unless paired
        # with a verified official event above.
        taiwan_signal = next((event for event in signals if (event.get("instrument") or {}).get("ticker") == "TAIEX"), None)
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


def build_official_event_brief(event: dict[str, Any]) -> str:
    """Make a neutral watch-sized alert for an official event or price move."""
    if event.get("market_direction") or event.get("market_move"):
        from src.event_output import short_event_message
        text = short_event_message(event)
        validate_brief(text)
        return text
    if event.get("kind") == "market_signal":
        text = f"快訊｜{event.get('brief_title') or event.get('short_label', '價格訊號')}"
        instrument = event.get("instrument") or {}
        ticker = str(instrument.get("ticker") or "市場")
        label = "台指" if ticker == "TAIEX" else ticker
        percent = instrument.get("change_percent")
        if percent is None:
            text = f"快訊｜{event.get('brief_title') or event.get('short_label', '價格訊號')}"[:30]
            validate_brief(text)
            return text
        move = f"{float(percent):+.1f}%" if percent is not None else "波動"
        pattern = str(event.get("pattern") or "價格訊號")
        risk = str(event.get("risk_level") or "觀察")
        text = f"快訊｜{label} {move}｜{pattern}｜{risk}"
        text = text[:30]
        validate_brief(text)
        return text
    label = " ".join(event.get("short_label", "官方事件").split())
    title = " ".join(event.get("brief_summary") or event.get("title", "").split())
    text = f"快訊｜{label}｜{title}"
    text = text[:30]
    validate_brief(text)
    return text


def prepare_snapshot() -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Refresh the public snapshot before the Mini App button is sent."""
    snapshot = build_market_snapshot()
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
    budget: dict[str, Any] | None = None,
) -> None:
    summary = summarize_photo_deliveries(deliveries)
    lines = [
        f"trace_id={trace_id}",
        f"release_id={os.environ.get('RELEASE_ID', '')}",
        f"delivered_count={summary.delivered_count}",
        f"failed_count={summary.failed_count}",
        f"delivery_status={'delivered' if summary.failed_count == 0 else 'partial' if summary.delivered_count else 'failed'}",
        "delivery_mode=photo",
        f"failed_recipient_hashes={','.join(summary.failed_recipient_hashes)}",
    ]
    if event:
        lines.extend([
            f"alert_id={event.get('event_cluster_key') or event.get('event_key') or ''}",
            f"snapshot_id={event.get('snapshot_id') or ''}",
            f"observation_id={event.get('observation_id') or (event.get('instrument') or {}).get('observation_id') or ''}",
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
    gate = verify_release_for_delivery(
        expected_snapshot_id=str(snapshot.get("snapshot_id") or ""),
        public_url=os.environ.get("PUBLIC_RELEASE_URL") or None,
    )
    if not gate.allowed:
        write_send_output(False, "release_gate_blocked")
        print("Release gate blocked official event delivery: " + "; ".join(gate.errors))
        return False
    cooldown_record = _observe_event(event)
    if not cooldown_record.get("should_remind", True):
        write_send_output(False, "event_cooldown")
        print("Official event is inside the shared 30-minute cooldown; skipped safely.")
        return False
    ledger = EventLedger()
    budget_event = {**event, "event_key": current_key}
    budget = decide_alert_budget(budget_event, ledger.delivery_history())
    if not budget.get("allowed", False):
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
    try:
        with tempfile.TemporaryDirectory(prefix="prstk-official-card-") as temporary:
            photo_path = render_alert_card(
                {
                    "title": event.get("title") or "官方市場事件",
                    "lifecycle_state": event.get("lifecycle_state") or "confirmed",
                    "trigger_reason": caption,
                    "release_id": gate.release_id,
                    "snapshot_id": snapshot_id,
                },
                Path(temporary) / "alert.png",
            )
            deliveries = send_photo_briefs(
                token=settings.telegram_bot_token or "",
                chat_ids=settings.telegram_chat_ids,
                caption=caption,
                photo_path=photo_path,
                mini_app_url=settings.dashboard_url,
                alert_id=event_id,
                release_id=gate.release_id or "",
                snapshot_id=snapshot_id,
            )
    except (RendererError, OSError, ValueError) as exc:
        write_send_output(False, "renderer_failed")
        print(f"Renderer blocked official event delivery: {getattr(exc, 'error_type', type(exc).__name__)}")
        return False
    _write_delivery_output(trace_id=trace_id, deliveries=deliveries, event=event, budget=budget)
    delivery_summary = summarize_photo_deliveries(deliveries)
    if not delivery_summary.any_delivered:
        write_send_output(False, "all_recipients_failed")
        raise RuntimeError("Telegram delivery failed for every configured recipient")
    ledger.record_delivery(
        {**budget_event, "trace_id": trace_id},
        trace_id=trace_id,
        reason="official_event_monitor",
    )
    ledger.save()
    write_send_output(True, "sent_partial" if delivery_summary.failed_count else "sent")
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
