"""Create a short market brief, refresh dashboard data, and notify Telegram."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from src.alert_budget import decide_alert_budget
from src.briefing_cards import build_briefing_snapshot
from src.config import get_settings
from src.event_ledger import EventLedger, is_secondary_commentary, taiwan_investor_priority
from src.market_data import build_market_snapshot
from src.refresh_market_data import merge_published_metadata, write_snapshot
from src.schedule_contract import ANCHOR_SLOTS as CONTRACT_ANCHOR_SLOTS
from src.schedule_contract import MAX_SCHEDULE_DELAY_SECONDS as CONTRACT_MAX_SCHEDULE_DELAY_SECONDS
from src.schedule_contract import SCHEDULE_CONTRACT_VERSION, SCHEDULE_TIMEZONE, validate_scheduled_context
from src.telegram_client import PUBLIC_TEXT_MAX_CHARS, alert_mini_app_url, send_briefs, summarize_public_message

SLOT_LABELS = {
    "morning": "晨報",
    "pre_open": "台股盤前",
    "intraday": "台股盤中",
    "midday": "台股午盤",
    "afternoon": "台股收盤前",
    "post_close": "台股盤後",
    "us_premarket": "美股盤前",
    "us_open": "美股開盤",
}
MAX_BRIEF_LENGTH = PUBLIC_TEXT_MAX_CHARS
TAIWAN_SESSION_SLOTS = frozenset({"pre_open", "intraday", "midday", "afternoon", "post_close"})
CRON_SLOT_MAP = {
    "0 22 * * *": "morning",
    "45 0 * * 1-5": "pre_open",
    "20 6 * * 1-5": "post_close",
    "0 13 * * 1-5": "us_premarket",
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
    "intraday": (10 * 60, 11 * 60),
    "midday": (11 * 60 + 15, 12 * 60 + 15),
    "afternoon": (12 * 60 + 45, 13 * 60 + 45),
    "post_close": (14 * 60 + 15, 15 * 60 + 15),
    "us_premarket": (20 * 60 + 30, 21 * 60 + 30),
}

# Manual runs are named from the most recent fixed report boundary.  These
# boundaries intentionally cover the whole clock: weekend/holiday content is
# still labelled by time and must disclose its closed-market context in the
# report itself.
MANUAL_SLOT_BOUNDARIES = (
    (6 * 60, "morning"),
    (8 * 60 + 30, "pre_open"),
    (9 * 60, "intraday"),
    (11 * 60 + 30, "midday"),
    (12 * 60 + 45, "afternoon"),
    (13 * 60 + 30, "post_close"),
    (21 * 60, "us_premarket"),
)

ANCHOR_SLOTS = CONTRACT_ANCHOR_SLOTS
MAX_SCHEDULE_DELAY_SECONDS = CONTRACT_MAX_SCHEDULE_DELAY_SECONDS
TAIPEI = ZoneInfo("Asia/Taipei")


def anchor_market(slot: str) -> str:
    """Return the market namespace used by scheduled-anchor idempotency."""
    return "us" if str(slot).strip() == "us_premarket" else "taiwan"


def anchor_key(slot: str, slot_date: str) -> str:
    """Build the stable market/date/anchor identity for a scheduled brief."""
    return f"{anchor_market(slot)}:{slot_date}:{slot}"


def _scheduled_time_for_cron(local_now: datetime, cron: str) -> datetime | None:
    """Return the Taipei execution time represented by a GitHub UTC cron."""
    parts = str(cron or "").split()
    if len(parts) != 5 or parts[2] != "*" or parts[3] != "*" or parts[4] not in {"*", "1-5"}:
        return None
    try:
        minute, hour = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    utc_date = local_now.astimezone(UTC).date()
    return datetime(utc_date.year, utc_date.month, utc_date.day, hour, minute, tzinfo=UTC).astimezone(TAIPEI)


def _phase_at(local_now: datetime) -> tuple[str, str]:
    """Resolve the actual Taipei market phase and its slot date."""
    minute = local_now.hour * 60 + local_now.minute
    if minute < 6 * 60:
        return "us_premarket", (local_now.date() - timedelta(days=1)).isoformat()
    selected = "morning"
    for start, candidate in MANUAL_SLOT_BOUNDARIES:
        if minute >= start:
            selected = candidate
    return selected, local_now.date().isoformat()


def _strict_slot_at(now: datetime) -> str | None:
    """Return the one external-scheduler slot permitted at this local time."""
    minute = now.hour * 60 + now.minute
    for slot, (start, end) in STRICT_SLOT_WINDOWS.items():
        if start <= minute <= end:
            return slot
    return None


def _us_premarket_cron_matches(now: datetime, scheduled_cron: str) -> bool:
    """Accept the one fixed 21:00 Asia/Taipei production slot.

    The report is intentionally fixed at 21:00 Taiwan time.  It remains a
    pre-market report in both New York daylight and standard time, but the
    message must use the actual exchange calendar rather than claiming a
    fixed number of minutes before the cash open.
    """
    if scheduled_cron != "0 13 * * 1-5":
        return True
    taipei_now = now.astimezone(ZoneInfo("Asia/Taipei"))
    return taipei_now.weekday() < 5


def _manual_slot_context(now: datetime) -> dict[str, str]:
    """Resolve a manual run to the latest fixed Taipei-time report slot."""
    local_now = now.astimezone(ZoneInfo("Asia/Taipei"))
    selected_slot, slot_date = _phase_at(local_now)
    return {
        "requested_slot": "auto",
        "effective_slot": selected_slot,
        "scheduled_slot": "",
        "effective_market_phase": selected_slot,
        "slot_date": slot_date,
        "scheduled_for_at": "",
        "run_started_at": local_now.isoformat(),
        "arrival_at": local_now.isoformat(),
        "delay_seconds": "0",
        "delivery_intent": "notify_candidate" if selected_slot in ANCHOR_SLOTS else "event_only",
        "resolution_reason": "manual_actual_market_phase",
        "trigger_kind": "workflow_dispatch",
        "schedule_contract_version": SCHEDULE_CONTRACT_VERSION,
        "time_zone": SCHEDULE_TIMEZONE,
        "contract_status": "manual_compatibility",
    }


def _invalid_dispatch_context(
    requested: str,
    now: datetime,
    *,
    reason: str,
    trigger_kind: str,
    dispatch_unix: str | None = None,
    dispatch_trace_id: str | None = None,
) -> dict[str, str]:
    """Create a publish-only context so a bad dispatch is visible on Pages."""
    local_now = now.astimezone(TAIPEI)
    effective_slot, slot_date = _phase_at(local_now)
    return {
        "requested_slot": requested,
        "scheduled_slot": requested if requested in SLOT_LABELS else "",
        "effective_slot": effective_slot,
        "effective_market_phase": effective_slot,
        "slot_date": slot_date,
        "scheduled_for_at": "",
        "dispatch_unix": str(dispatch_unix or ""),
        "dispatch_trace_id": str(dispatch_trace_id or ""),
        "run_started_at": local_now.isoformat(),
        "arrival_at": local_now.isoformat(),
        "delay_seconds": "0",
        "delivery_intent": "publish_only",
        "resolution_reason": reason,
        "suppression_reason": reason,
        "trigger_kind": trigger_kind,
        "schedule_contract_version": SCHEDULE_CONTRACT_VERSION,
        "time_zone": SCHEDULE_TIMEZONE,
        "contract_status": "invalid",
    }


def resolve_schedule_diagnostic(
    value: str,
    now: datetime,
    *,
    strict_window: bool = False,
    scheduled_cron: str | None = None,
    scheduled_for_at: str | None = None,
    trigger_kind: str = "compatibility",
    contract_version: str | None = None,
    time_zone: str | None = None,
    dispatch_unix: str | None = None,
    dispatch_trace_id: str | None = None,
) -> dict[str, object]:
    """Resolve a scheduled run and retain a diagnostic for invalid context.

    ``resolve_slot_context`` remains a compatibility API returning ``None``
    for invalid dispatches.  The workflow uses this richer result so a
    malformed backup request still publishes a diagnostic snapshot and then
    fails the job explicitly instead of looking like normal deduplication.
    """
    context = resolve_slot_context(
        value,
        now,
        strict_window=strict_window,
        scheduled_cron=scheduled_cron,
        scheduled_for_at=scheduled_for_at,
        trigger_kind=trigger_kind,
        contract_version=contract_version,
        time_zone=time_zone,
        dispatch_unix=dispatch_unix,
        dispatch_trace_id=dispatch_trace_id,
    )
    if context is not None:
        return {"context": context, "valid": context.get("contract_status") != "invalid", "reason": context.get("resolution_reason", "")}
    trigger = str(trigger_kind or "compatibility").strip().casefold()
    if trigger == "repository_dispatch":
        requested = str(value or "auto").strip() or "auto"
        declared = requested if requested in SLOT_LABELS else ""
        check = validate_scheduled_context(
            slot=declared,
            scheduled_for_at=scheduled_for_at,
            now=now,
            contract_version=SCHEDULE_CONTRACT_VERSION if contract_version is None else contract_version,
            time_zone=SCHEDULE_TIMEZONE if time_zone is None else time_zone,
            dispatch_unix=dispatch_unix,
        )
        reason = str(check.get("reason") or "invalid_schedule_context:slot_resolution_failed")
        blocked = _invalid_dispatch_context(
            requested,
            now,
            reason=reason,
            trigger_kind=trigger,
            dispatch_unix=dispatch_unix,
            dispatch_trace_id=dispatch_trace_id,
        )
        return {"context": blocked, "valid": False, "reason": reason}
    return {"context": None, "valid": False, "reason": "outside_window"}


def resolve_slot_context(
    value: str,
    now: datetime | None = None,
    *,
    strict_window: bool = False,
    scheduled_cron: str | None = None,
    scheduled_for_at: str | None = None,
    trigger_kind: str = "compatibility",
    contract_version: str | None = None,
    time_zone: str | None = None,
    dispatch_unix: str | None = None,
    dispatch_trace_id: str | None = None,
) -> dict[str, str] | None:
    """Resolve slot plus identity metadata without trusting stale manual input."""
    local_now = now or datetime.now(ZoneInfo("Asia/Taipei"))
    local_now = local_now.astimezone(ZoneInfo("Asia/Taipei"))
    requested = str(value or "auto").strip() or "auto"
    trigger = str(trigger_kind or "compatibility").strip().casefold()
    cron_text = str(scheduled_cron or "").strip()
    cron_slot = CRON_SLOT_MAP.get(cron_text)
    if cron_slot:
        if cron_slot == "us_premarket" and not _us_premarket_cron_matches(local_now, str(scheduled_cron).strip()):
            return None
        scheduled_at = _scheduled_time_for_cron(local_now, cron_text)
        if scheduled_for_at:
            try:
                parsed = datetime.fromisoformat(str(scheduled_for_at).replace("Z", "+00:00"))
                scheduled_at = parsed.astimezone(TAIPEI)
            except (TypeError, ValueError):
                pass
        if scheduled_at is None:
            scheduled_at = local_now
        delay_seconds = max(0, int((local_now - scheduled_at).total_seconds()))
        late = delay_seconds > MAX_SCHEDULE_DELAY_SECONDS
        actual_phase, actual_date = _phase_at(local_now)
        slot_date = local_now.date()
        # The 13:00 UTC weekday cron is the 21:00 Taipei report.  If GitHub
        # starts that run after midnight Taipei time, keep the slot identity
        # on the previous local date instead of creating a second report for
        # the new calendar day.
        if cron_slot == "us_premarket" and local_now.hour < 6:
            slot_date -= timedelta(days=1)
        resolved_slot = actual_phase if late else cron_slot
        resolved_date = actual_date if late else slot_date.isoformat()
        return {
            "requested_slot": requested,
            "scheduled_slot": cron_slot,
            "effective_slot": resolved_slot,
            "effective_market_phase": resolved_slot,
            "slot_date": resolved_date,
            "scheduled_for_at": scheduled_at.isoformat(),
            "run_started_at": local_now.isoformat(),
            "arrival_at": local_now.isoformat(),
            "delay_seconds": str(delay_seconds),
            "delivery_intent": "publish_only" if late else "notify_candidate",
            "resolution_reason": "late_schedule_publish_only" if late else "scheduled_anchor_on_time",
            "trigger_kind": "schedule" if trigger == "compatibility" else trigger,
            "schedule_contract_version": SCHEDULE_CONTRACT_VERSION,
            "time_zone": SCHEDULE_TIMEZONE,
            "contract_status": "valid",
        }
    if trigger == "repository_dispatch":
        declared = requested if requested in SLOT_LABELS else ""
        check = validate_scheduled_context(
            slot=declared,
            scheduled_for_at=scheduled_for_at,
            now=local_now,
            contract_version=SCHEDULE_CONTRACT_VERSION if contract_version is None else contract_version,
            time_zone=SCHEDULE_TIMEZONE if time_zone is None else time_zone,
            dispatch_unix=dispatch_unix,
        )
        if check.get("contract_status") != "valid":
            return None
        scheduled_at = check["scheduled"]
        delay_seconds = max(0, int((local_now - scheduled_at).total_seconds()))
        late = delay_seconds > MAX_SCHEDULE_DELAY_SECONDS
        actual_phase, actual_date = _phase_at(local_now)
        return {
            "requested_slot": requested,
            "scheduled_slot": declared,
            "effective_slot": actual_phase if late else declared,
            "effective_market_phase": actual_phase if late else declared,
            "slot_date": actual_date if late else scheduled_at.date().isoformat(),
            "scheduled_for_at": scheduled_at.isoformat(),
            "dispatch_unix": str(dispatch_unix or ""),
            "dispatch_trace_id": str(dispatch_trace_id or ""),
            "run_started_at": local_now.isoformat(),
            "arrival_at": local_now.isoformat(),
            "delay_seconds": str(delay_seconds),
            "delivery_intent": "publish_only" if late else "notify_candidate",
            "resolution_reason": "late_dispatch_publish_only" if late else "dispatch_anchor_on_time",
            "trigger_kind": trigger,
            "schedule_contract_version": SCHEDULE_CONTRACT_VERSION,
            "time_zone": SCHEDULE_TIMEZONE,
            "contract_status": "valid",
        }
    if trigger == "compatibility":
        if strict_window:
            matched = _strict_slot_at(local_now)
            if matched is None or (requested != "auto" and requested != matched):
                return None
            return {
                "requested_slot": requested,
                "effective_slot": matched,
                "scheduled_slot": requested if requested != "auto" else matched,
                "effective_market_phase": matched,
                "slot_date": local_now.date().isoformat(),
                "scheduled_for_at": "",
                "run_started_at": local_now.isoformat(),
                "delay_seconds": "0",
                "delivery_intent": "event_only",
                "resolution_reason": "trusted_dispatch_window",
                "trigger_kind": trigger,
                "schedule_contract_version": SCHEDULE_CONTRACT_VERSION,
                "time_zone": SCHEDULE_TIMEZONE,
                "contract_status": "compatibility",
            }
        if requested != "auto":
            return {
                "requested_slot": requested,
                "effective_slot": requested,
                "scheduled_slot": requested,
                "effective_market_phase": requested,
                "slot_date": local_now.date().isoformat(),
                "scheduled_for_at": "",
                "run_started_at": local_now.isoformat(),
                "delay_seconds": "0",
                "delivery_intent": "event_only",
                "resolution_reason": "explicit_compatibility_slot",
                "trigger_kind": trigger,
                "schedule_contract_version": SCHEDULE_CONTRACT_VERSION,
                "time_zone": SCHEDULE_TIMEZONE,
                "contract_status": "compatibility",
            }
        minute = local_now.hour * 60 + local_now.minute
        legacy_windows = (
            (5 * 60 + 30, 6 * 60 + 30, "morning"),
            (8 * 60 + 15, 9 * 60 + 15, "pre_open"),
            (10 * 60, 11 * 60, "intraday"),
            (11 * 60 + 15, 12 * 60 + 15, "midday"),
            (12 * 60 + 45, 13 * 60 + 45, "afternoon"),
            (14 * 60 + 15, 15 * 60 + 15, "post_close"),
            (20 * 60 + 30, 21 * 60 + 30, "us_premarket"),
        )
        selected = next((slot for start, end, slot in legacy_windows if start <= minute <= end), None)
        if not selected:
            return None
        return {
            "requested_slot": requested,
            "effective_slot": selected,
            "scheduled_slot": selected,
            "effective_market_phase": selected,
            "slot_date": local_now.date().isoformat(),
            "scheduled_for_at": "",
            "run_started_at": local_now.isoformat(),
            "delay_seconds": "0",
            "delivery_intent": "event_only",
            "resolution_reason": "compatibility_clock_window",
            "trigger_kind": trigger,
            "schedule_contract_version": SCHEDULE_CONTRACT_VERSION,
            "time_zone": SCHEDULE_TIMEZONE,
            "contract_status": "compatibility",
        }
    if trigger in {"workflow_dispatch", "manual"}:
        context = _manual_slot_context(local_now)
        context["requested_slot"] = requested
        context["trigger_kind"] = trigger
        return context
    if strict_window:
        matched = _strict_slot_at(local_now)
        if matched is None or (requested != "auto" and requested != matched):
            return None
        return {
            "requested_slot": requested,
            "effective_slot": matched,
            "scheduled_slot": requested if requested != "auto" else matched,
            "effective_market_phase": matched,
            "slot_date": local_now.date().isoformat(),
            "scheduled_for_at": "",
            "run_started_at": local_now.isoformat(),
            "delay_seconds": "0",
            "delivery_intent": "event_only",
            "resolution_reason": "trusted_dispatch_window",
            "trigger_kind": trigger,
        }
    if requested != "auto":
        if requested not in SLOT_LABELS:
            return None
        return {
            "requested_slot": requested,
            "effective_slot": requested,
            "scheduled_slot": requested,
            "effective_market_phase": requested,
            "slot_date": local_now.date().isoformat(),
            "scheduled_for_at": "",
            "run_started_at": local_now.isoformat(),
            "delay_seconds": "0",
            "delivery_intent": "event_only",
            "resolution_reason": "explicit_compatibility_slot",
            "trigger_kind": trigger,
        }
    # Explicitly named manual/CLI callers use the fixed boundaries above.  An
    # unknown trigger is deliberately conservative and does not invent a slot.
    return None


def resolve_slot(
    value: str,
    now: datetime | None = None,
    *,
    strict_window: bool = False,
    scheduled_cron: str | None = None,
    scheduled_for_at: str | None = None,
) -> str | None:
    """Compatibility API returning only the resolved slot name."""
    context = resolve_slot_context(
        value, now, strict_window=strict_window, scheduled_cron=scheduled_cron,
        scheduled_for_at=scheduled_for_at,
    )
    return context["effective_slot"] if context else None


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
    parser.add_argument("--scheduled-for", default="")
    parser.add_argument("--trigger-kind", default="compatibility")
    parser.add_argument("--schedule-contract-version", default="")
    parser.add_argument("--time-zone", default="")
    parser.add_argument("--dispatch-unix", default="")
    parser.add_argument("--dispatch-trace-id", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    now = datetime.now(ZoneInfo("Asia/Taipei"))
    diagnostic = resolve_schedule_diagnostic(
        args.slot,
        now,
        strict_window=args.strict_window,
        scheduled_cron=args.scheduled_cron,
        scheduled_for_at=args.scheduled_for,
        trigger_kind=args.trigger_kind,
        contract_version=args.schedule_contract_version,
        time_zone=args.time_zone,
        dispatch_unix=args.dispatch_unix,
        dispatch_trace_id=args.dispatch_trace_id,
    )
    raw_context = diagnostic.get("context")
    context: dict[str, str] | None = raw_context if isinstance(raw_context, dict) else None
    slot = context.get("effective_slot") if context else None
    if args.print_window:
        print(f"should_run={'true' if slot else 'false'}")
        print(f"slot={slot or 'skip'}")
        print(f"requested_slot={(context or {}).get('requested_slot', args.slot)}")
        print(f"scheduled_slot={(context or {}).get('scheduled_slot', '')}")
        print(f"effective_slot={slot or 'skip'}")
        print(f"effective_market_phase={(context or {}).get('effective_market_phase', slot or 'skip')}")
        print(f"slot_date={(context or {}).get('slot_date', now.date().isoformat())}")
        print(f"scheduled_for_at={(context or {}).get('scheduled_for_at', '')}")
        print(f"dispatch_unix={(context or {}).get('dispatch_unix', '')}")
        print(f"dispatch_trace_id={(context or {}).get('dispatch_trace_id', '')}")
        print(f"run_started_at={(context or {}).get('run_started_at', now.isoformat())}")
        print(f"delay_seconds={(context or {}).get('delay_seconds', '0')}")
        print(f"delivery_intent={(context or {}).get('delivery_intent', 'event_only')}")
        print(f"resolution_reason={(context or {}).get('resolution_reason', 'outside_window')}")
        print(f"trigger_kind={(context or {}).get('trigger_kind', args.trigger_kind)}")
        print(f"contract_status={(context or {}).get('contract_status', 'not_applicable')}")
        print(f"schedule_contract_version={(context or {}).get('schedule_contract_version', SCHEDULE_CONTRACT_VERSION)}")
        print(f"time_zone={(context or {}).get('time_zone', SCHEDULE_TIMEZONE)}")
        print(f"notification_status={(context or {}).get('notification_status', 'blocked' if not diagnostic.get('valid', False) and slot else 'not_attempted')}")
        print(f"notification_reason={(context or {}).get('suppression_reason') or diagnostic.get('reason') or ('outside_window' if not slot else '')}")
        print(f"key={anchor_key(slot or 'skip', (context or {}).get('slot_date', now.date().isoformat())) if slot else 'skip'}")
        if context:
            _write_output({"context_json": context})
        return

    if slot is None:
        print("此時段不在已設定的台灣時間快報窗口，略過快報。")
        return

    delivery_intent = str((context or {}).get("delivery_intent") or "event_only").strip()
    if delivery_intent != "notify_candidate":
        _write_output({
            "sent": "false",
            "delivery_status": "suppressed",
            "notification_expected": "false",
            "notification_status": "suppressed",
            "notification_reason": str(
                (context or {}).get("suppression_reason")
                or (context or {}).get("resolution_reason")
                or "delivery_intent_not_notify"
            ),
        })
        print("此執行只更新市場資料，不具備例行 Telegram 投遞資格。")
        return

    settings = get_settings()
    if not settings.telegram_ready:
        raise RuntimeError("缺少 Telegram 設定，未發送快報。")
    snapshot = build_market_snapshot()
    snapshot["briefing"] = build_briefing_snapshot(snapshot, slot)
    snapshot["briefing"]["slot_context"] = context
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
    # The published briefing is the single public-text source for Telegram,
    # immutable alerts and the Mini App.  Keep build_brief as a compatibility
    # fallback only for sparse legacy snapshots that cannot produce a shared
    # briefing artifact.
    briefing = snapshot.get("briefing")
    briefing_message = str(briefing.get("public_short_message") or "").strip() if isinstance(briefing, dict) else ""
    brief = briefing_message if briefing_message and len(briefing_message) <= MAX_BRIEF_LENGTH else build_brief(snapshot, slot)
    release_id = str(snapshot.get("release_id") or os.environ.get("RELEASE_ID") or "")
    target_url = (
        alert_mini_app_url(
            settings.dashboard_url,
            alert_id=str((event or {}).get("notification_id") or (event or {}).get("event_cluster_key") or (event or {}).get("event_key") or trace_id),
            release_id=release_id,
            snapshot_id=snapshot_id,
            observation_id=observation_id,
        )
        if release_id
        else ""
    )
    # The direct compatibility entry point follows the same ledger boundary
    # as the two-phase workflow: without a release-bound HTTPS report link,
    # persistence is not provable and Telegram must not be attempted.
    if not target_url:
        _write_output({
            "sent": "false",
            "delivery_status": "suppressed",
            "reason": "ledger_source_url_invalid",
            "notification_status": "suppressed",
            "notification_reason": "ledger_source_url_invalid",
        })
        return
    event_for_delivery = {**event, "source_url": target_url} if event else None
    if event_for_delivery is not None:
        preflight = ledger.preflight_delivery(event_for_delivery)
        if not preflight.get("ok"):
            _write_output({
                "sent": "false",
                "delivery_status": "suppressed",
                "reason": str(preflight.get("reason") or "ledger_preflight_failed"),
                "notification_status": "suppressed",
                "notification_reason": str(preflight.get("reason") or "ledger_preflight_failed"),
            })
            return
        write_event_lock_key(event_for_delivery)
    results = send_briefs(
        token=settings.telegram_bot_token or "",
        chat_ids=settings.telegram_chat_ids,
        text=brief,
        dashboard_url=settings.dashboard_url,
        target_url=target_url,
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
        assert event_for_delivery is not None
        ledger.mark_reminded({**event_for_delivery, "trace_id": trace_id})
        ledger.save()
    delivered = summary["delivered"]
    unavailable = [result.chat_id for result in results if not result.delivered]
    print(f"已發送 {slot} 快報給 {delivered}/{len(results)} 位收件人。")
    if unavailable:
        print("以下收件人尚未啟動或已封鎖 Bot，略過本次發送：" + ", ".join(unavailable))


if __name__ == "__main__":
    main()
