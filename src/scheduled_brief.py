"""Create a short market brief, refresh dashboard data, and notify Telegram."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from src.alert_budget import decide_alert_budget
from src.briefing_cards import build_briefing_snapshot
from src.config import get_settings
from src.event_ledger import EventLedger, is_secondary_commentary, taiwan_investor_priority
from src.market_data import build_market_snapshot
from src.refresh_market_data import merge_published_metadata, write_snapshot
from src.telegram_client import PUBLIC_TEXT_MAX_CHARS, alert_mini_app_url, send_briefs, summarize_public_message

SLOT_LABELS = {
    "morning": "晨報",
    "pre_open": "盤前",
    "intraday": "盤中",
    "midday": "午報",
    "afternoon": "午盤",
    "post_close": "盤後",
    "us_premarket": "美股盤前",
    "us_open": "美股開盤",
}
MAX_BRIEF_LENGTH = PUBLIC_TEXT_MAX_CHARS
TAIWAN_SESSION_SLOTS = frozenset({"pre_open", "intraday", "midday", "afternoon"})
CRON_SLOT_MAP = {
    "0 22 * * *": "morning",
    "45 0 * * 1-5": "pre_open",
    "0 2 * * 1-5": "intraday",
    "30 2 * * 1-5": "intraday",
    "45 3 * * 1-5": "midday",
    "15 5 * * 1-5": "afternoon",
    "45 6 * * 1-5": "post_close",
    "0 13 * * 1-5": "us_premarket",
    "0 14 * * 1-5": "us_premarket",
}


def _write_output(values: dict[str, object]) -> None:
    """Publish non-secret correlation values to GitHub Actions outputs.

    The same values are also printed for local runs.  Telegram text remains
    intentionally short; correlation belongs in Actions, Railway and the
    Mini App snapshot rather than in the bounded watch message.
    """
    lines = []
    for key, value in values.items():
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        lines.append(f"{key}={str(value or '')}")
    destination = os.getenv("GITHUB_OUTPUT")
    if destination:
        with open(destination, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    else:
        print("\n".join(lines))


def briefing_correlation(snapshot: dict, slot: str, event: dict | None = None) -> dict[str, str]:
    """Return the IDs shared by a scheduled report and its Mini App card."""
    snapshot_id = str(snapshot.get("snapshot_id") or "")
    briefing_raw = snapshot.get("briefing")
    briefing: dict = briefing_raw if isinstance(briefing_raw, dict) else {}
    item = event or {}
    observation_id = str(
        briefing.get("observation_id")
        or item.get("observation_id")
        or (item.get("instrument") or {}).get("observation_id")
        or ""
    )
    trace_id = str(briefing.get("trace_id") or (f"brief-{snapshot_id}-{slot}" if snapshot_id else f"brief-{slot}"))
    return {"trace_id": trace_id, "snapshot_id": snapshot_id, "observation_id": observation_id}

# External scheduler calls are accepted only around their declared Taiwan-time
# slot. This prevents an accidental early backup request from consuming the
# same-day idempotency lock that belongs to the real scheduled briefing.
STRICT_SLOT_WINDOWS = {
    "morning": (5 * 60 + 30, 6 * 60 + 30),
    "pre_open": (8 * 60 + 15, 9 * 60 + 15),
    "intraday": (9 * 60 + 30, 10 * 60 + 30),
    "midday": (11 * 60 + 15, 12 * 60 + 15),
    "afternoon": (12 * 60 + 45, 13 * 60 + 45),
    "post_close": (13 * 60 + 55, 14 * 60 + 55),
    "us_premarket": (20 * 60 + 30, 21 * 60 + 30),
}


def _strict_slot_at(now: datetime) -> str | None:
    """Return the one external-scheduler slot permitted at this local time."""
    minute = now.hour * 60 + now.minute
    for slot, (start, end) in STRICT_SLOT_WINDOWS.items():
        if start <= minute <= end:
            return slot
    return None


def _us_premarket_cron_matches(now: datetime, scheduled_cron: str) -> bool:
    """Accept only the UTC cron that is 30 minutes before the NYSE open."""
    if scheduled_cron not in {"0 13 * * 1-5", "0 14 * * 1-5"}:
        return True
    new_york_now = now.astimezone(ZoneInfo("America/New_York"))
    # 09:00 New York is the desired report time.  Derive its UTC hour from
    # the exchange offset so daylight-saving changes do not produce two
    # reports or a report 90 minutes before the cash open.
    offset = new_york_now.utcoffset()
    expected_utc_hour = 9 - int((offset.total_seconds() if offset else 0) // 3600)
    cron_hour = int(scheduled_cron.split()[1])
    return cron_hour == expected_utc_hour and new_york_now.weekday() < 5


def resolve_slot(
    value: str,
    now: datetime | None = None,
    *,
    strict_window: bool = False,
    scheduled_cron: str | None = None,
) -> str | None:
    """Resolve an explicit slot or choose the nearest Taiwan-time briefing slot."""
    local_now = now or datetime.now(ZoneInfo("Asia/Taipei"))
    cron_slot = CRON_SLOT_MAP.get(str(scheduled_cron or "").strip())
    if cron_slot and value in {"auto", cron_slot}:
        # GitHub-hosted schedules can start late.  The cron identity, not the
        # runner start time, is the source of truth for an automatic slot.
        if cron_slot == "us_premarket" and not _us_premarket_cron_matches(local_now, str(scheduled_cron).strip()):
            return None
        return cron_slot
    if strict_window:
        matched = _strict_slot_at(local_now)
        if matched is None or (value != "auto" and value != matched):
            return None
        return matched
    if value != "auto":
        return value
    hour = local_now.hour
    if hour < 8:
        return "morning"
    if hour < 10:
        return "pre_open"
    if hour < 11:
        return "intraday"
    if hour < 13:
        return "midday"
    if hour < 14:
        return "afternoon"
    if hour < 18:
        return "post_close"
    if hour < 21:
        return "us_premarket"
    # This system has one fixed Taiwan-time pre-market report throughout the
    # year.  The content remains a public market briefing, not a claim that
    # the US cash session is about to open at the same local clock time.
    return "us_premarket" if hour == 21 else None


def _pick_quote(snapshot: dict, slot: str) -> dict | None:
    if slot in TAIWAN_SESSION_SLOTS:
        # Taiwan intraday reports lead with the broad market, not an
        # individual company.  Representative shares remain a fallback.
        items = [*(snapshot.get("indices") or []), *(snapshot.get("quotes") or [])]
        return next((item for item in items if item.get("ticker") == "TAIEX"), None) or next(
            (item for item in items if item.get("ticker") == "2330"), None
        ) or (items[0] if items else None)

    quotes = snapshot.get("quotes", [])
    return next((quote for quote in quotes if quote["ticker"] == "NVDA"), None) or (
        quotes[0] if quotes else None
    )


def _pick_event(
    snapshot: dict,
    slot: str,
    *,
    excluded_event_keys: set[str] | None = None,
) -> dict | None:
    """Prioritise the market currently relevant to the timed watch brief."""
    excluded = excluded_event_keys or set()
    from src.alert_orchestrator import notification_key_for_event

    def available(item: dict) -> bool:
        key = notification_key_for_event(item) or str(
            item.get("notification_id")
            or item.get("item_id")
            or item.get("observation_id")
            or ""
        ).strip()
        return key not in excluded and str(item.get("event_key") or "") not in excluded

    # A qualifying FinancialJuice item has its own vendor-priority lane.  It
    # may lead the single scheduled photo when no prior cluster notification
    # has consumed it; risk still stays in the conservative PRStK state.
    priority_events = snapshot.get("financialjuice_priority_events") or []
    if isinstance(priority_events, list):
        def priority_key(item: dict) -> tuple[int, int, float, str]:
            """Prefer complete, important, recent FJ facts deterministically."""
            complete = bool(
                item.get("public_signal_eligible") is not False
                and item.get("alert_eligible") is not False
                and str(item.get("notification_status") or "eligible") == "eligible"
            )
            try:
                importance = int(item.get("importance") or item.get("vendor_importance") or 0)
            except (TypeError, ValueError):
                importance = 0
            published = str(item.get("published_at") or item.get("received_at") or "")
            try:
                published_score = datetime.fromisoformat(published.replace("Z", "+00:00")).timestamp()
            except (TypeError, ValueError, OverflowError):
                published_score = float("-inf")
            return (0 if complete else 1, -importance, -published_score, notification_key_for_event(item))

        ordered_priority = sorted(
            (item for item in priority_events if isinstance(item, dict) and available(item)),
            key=priority_key,
        )
        first_priority = ordered_priority[0] if ordered_priority else None
        if first_priority:
            return first_priority
    events = [
        event for event in ((snapshot.get("events") or {}).get("items", []) or [])
        if isinstance(event, dict) and available(event) and not is_secondary_commentary(event)
    ]
    preferred: tuple[str, ...]
    if slot in TAIWAN_SESSION_SLOTS:
        preferred = tuple(["TAIEX", "TPEx"])
    else:
        preferred = tuple(["SOX", "NASDAQ", "DJIA", "S&P 500"])
    for ticker in preferred:
        selected = next(
            (event for event in events if event.get("instrument", {}).get("ticker") == ticker),
            None,
        )
        if selected:
            return selected

    if slot in TAIWAN_SESSION_SLOTS:
        # During Taiwan trading hours, an overseas price-only move (Brent,
        # crypto, etc.) stays visible in the Mini App but must not replace the
        # Taiwan-market headline. A verified policy/macro/company event may.
        taiwan_ordered = sorted(events, key=taiwan_investor_priority)
        return next((event for event in taiwan_ordered if event.get("kind") != "market_signal"), None)
    return events[0] if events else None


def build_brief(snapshot: dict, slot: str) -> str:
    """Create a 60-character watch brief; detail remains in the Mini App."""
    from src.event_output import short_event_message

    label = SLOT_LABELS[slot]
    quote = _pick_quote(snapshot, slot)
    event = _pick_event(snapshot, slot)
    if not quote:
        return f"{label}｜市場資料暫時無法取得"
    pct = quote.get("change_percent")
    if pct is None:
        return f"{label}｜{quote['ticker']} 資料暫時無法取得"
    if event and (event.get("market_direction") or event.get("market_move")):
        prepared = dict(event)
        instrument = prepared.get("instrument") or quote
        ticker = str(instrument.get("ticker") or quote.get("ticker") or "市場")
        if ticker == "TAIEX":
            ticker = "台指"
        prepared.setdefault("short_label", prepared.get("pattern") or ticker)
        prepared.setdefault("market_direction", "上漲" if float(pct) > 0 else "下跌" if float(pct) < 0 else "持平")
        prepared.setdefault("market_move", f"{float(pct):+.1f}%")
        prepared.setdefault("risk_level", "高波動" if abs(float(pct)) >= 2 else "觀察")
        return short_event_message(prepared, prefix=label)
    # Compatibility fallback for sparse test/legacy snapshots. Production
    # events produced by event_alerts carry the canonical fields above.
    icon = "📈" if pct > 1 else "📉" if pct < -1 else "🟰"
    suffix = f"{quote['ticker']}{icon}{pct:+.1f}%"
    if event:
        if event.get("kind") == "market_signal" and event.get("pattern"):
            instrument = event.get("instrument") or quote
            market = "台指" if instrument.get("ticker") == "TAIEX" else str(instrument.get("ticker") or quote["ticker"])
            return f"{label}｜{market} {float(pct):+.1f}%｜{event.get('pattern')}"
        if event.get("brief_title"):
            return f"{label}｜{event['brief_title']}"
        event_label = event.get("short_label")
        if event_label:
            prefix = f"{label}｜"
            available = MAX_BRIEF_LENGTH - len(prefix) - len(suffix) - 1
            label_text = str(event_label)
            if len(label_text) > max(0, available):
                return summarize_public_message(
                    f"{prefix}{label_text}｜{suffix}", limit=MAX_BRIEF_LENGTH,
                )
            return f"{prefix}{label_text}｜{suffix}"
    return f"{label}｜{suffix}"


def write_event_lock_key(event: dict | None) -> None:
    """Let a timed briefing suppress the same monitor alert immediately after."""
    if not event:
        return
    from src.official_event_monitor import event_key

    ledger = EventLedger()
    ledger.observe(event)
    ledger.save()

    destination = os.getenv("GITHUB_OUTPUT")
    if destination:
        with open(destination, "a", encoding="utf-8") as handle:
            handle.write(f"event_key={event_key(event)}\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="產製並發送 PRStK 定時快報")
    parser.add_argument("--slot", choices=("auto", *SLOT_LABELS), default="auto")
    parser.add_argument("--print-window", action="store_true")
    parser.add_argument("--strict-window", action="store_true")
    parser.add_argument("--scheduled-cron", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    now = datetime.now(ZoneInfo("Asia/Taipei"))
    slot = resolve_slot(
        args.slot,
        now,
        strict_window=args.strict_window,
        scheduled_cron=args.scheduled_cron,
    )
    if args.print_window:
        print(f"should_run={'true' if slot else 'false'}")
        print(f"slot={slot or 'skip'}")
        print(f"key={now.date().isoformat()}-{slot or 'skip'}")
        return

    if slot is None:
        print("此時段不在已設定的台灣時間快報窗口，略過快報。")
        return

    settings = get_settings()
    if not settings.telegram_ready:
        raise RuntimeError("缺少 Telegram 設定，未發送快報。")
    snapshot = build_market_snapshot()
    snapshot["briefing"] = build_briefing_snapshot(snapshot, slot)
    published = write_snapshot(snapshot)
    if not published:
        _write_output({"sent": "false", "reason": "snapshot_publish_skipped"})
        return
    event = _pick_event(snapshot, slot)
    correlation = briefing_correlation(snapshot, slot, event)
    snapshot_id = correlation["snapshot_id"]
    observation_id = correlation["observation_id"]
    trace_id = correlation["trace_id"]
    # Keep the correlation contract in the published JSON so the Mini App can
    # show exactly which observation produced the Telegram brief.
    snapshot.setdefault("briefing", {})["trace_id"] = trace_id
    snapshot["briefing"]["snapshot_id"] = snapshot_id
    snapshot["briefing"]["observation_id"] = observation_id
    if not merge_published_metadata(
        {"trace_id": trace_id, "snapshot_id": snapshot_id, "observation_id": observation_id},
        expected_snapshot_id=snapshot_id,
    ):
        _write_output({"sent": "false", "reason": "snapshot_metadata_merge_skipped", "trace_id": trace_id})
        return
    ledger = EventLedger()
    budget = decide_alert_budget(event, ledger.delivery_history()) if event else {
        "allowed": True, "reason": "no_event", "event_key": ""
    }
    if not budget["allowed"]:
        _write_output({
            "sent": "false", "delivery_status": "suppressed",
            "reason": budget["reason"],
            "event_key": budget.get("event_key", ""),
            "alert_budget_allowed": "false",
        })
        print(f"Scheduled briefing suppressed by alert budget: {budget['reason']}")
        return
    write_event_lock_key(event)
    brief = build_brief(snapshot, slot)
    results = send_briefs(
        token=settings.telegram_bot_token or "",
        chat_ids=settings.telegram_chat_ids,
        text=brief,
        dashboard_url=settings.dashboard_url,
        target_url=(
            alert_mini_app_url(
                settings.dashboard_url,
                alert_id=str((event or {}).get("notification_id") or (event or {}).get("event_cluster_key") or (event or {}).get("event_key") or trace_id),
                release_id=str(snapshot.get("release_id") or os.environ.get("RELEASE_ID") or ""),
                snapshot_id=snapshot_id,
                observation_id=observation_id,
            )
            if (snapshot.get("release_id") or os.environ.get("RELEASE_ID"))
            else None
        ),
        message_kind="scheduled_brief",
    )
    summary = {
        "delivered": sum(result.delivered for result in results),
        "failed": sum(not result.delivered for result in results),
    }
    _write_output({
        "sent": "true",
        "reason": "sent_partial" if summary["failed"] else "sent",
        "trace_id": trace_id,
        "snapshot_id": snapshot_id,
        "observation_id": observation_id,
        "delivery_status": "delivered" if not summary["failed"] else "partial" if summary["delivered"] else "failed",
        "delivered_count": summary["delivered"],
        "failed_count": summary["failed"],
        "alert_budget_allowed": "true",
        "alert_budget_reason": budget.get("reason", "budget_available"),
    })
    if event and summary["delivered"]:
        ledger.mark_reminded({**event, "trace_id": trace_id})
        ledger.save()
    delivered = summary["delivered"]
    unavailable = [result.chat_id for result in results if not result.delivered]
    print(f"已發送 {slot} 快報給 {delivered}/{len(results)} 位收件人。")
    if unavailable:
        print("以下收件人尚未啟動或已封鎖 Bot，略過本次發送：" + ", ".join(unavailable))


if __name__ == "__main__":
    main()
