"""Shared contract for the four production scheduled-brief anchors.

The backup scheduler is outside this repository, so the receiver must be
strict about the information it accepts.  This module is deliberately small:
it validates identity and time only; delivery eligibility is still decided by
the existing briefing evidence and EventLedger gates.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

SCHEDULE_CONTRACT_VERSION = "2"
SCHEDULE_TIMEZONE = "Asia/Taipei"
TAIPEI_TIMEZONE = SCHEDULE_TIMEZONE
TAIPEI = ZoneInfo(SCHEDULE_TIMEZONE)
MAX_SCHEDULE_DELAY_SECONDS = 30 * 60
MAX_CLOCK_SKEW_SECONDS = 5 * 60

# Creator's 10:30 batch is a separate, non-Telegram content lane.  Preserve
# its original contract here so introducing scheduled-brief validation cannot
# change Creator cutoff semantics.
CREATOR_MORNING_BATCH_TIME = time(10, 30)
CREATOR_MORNING_LATE_GRACE_MINUTES = 180
CREATOR_BATCH_CRON_SCHEDULES = frozenset({
    "30 2 * * 1-5",
    "45 3 * * 1-5",
    "15 5 * * 1-5",
})


def creator_batch_cutoff(day: date) -> datetime:
    """Return the immutable 10:30 Asia/Taipei Creator cutoff."""
    return datetime.combine(day, CREATOR_MORNING_BATCH_TIME, tzinfo=TAIPEI)


def creator_batch_late_end(day: date) -> datetime:
    """Return the bounded Creator late-arrival deadline."""
    return creator_batch_cutoff(day) + timedelta(minutes=CREATOR_MORNING_LATE_GRACE_MINUTES)

# The time is a production identity, not a suggestion.  Keep this mapping in
# one place so the workflow, backup payload builder and receiver cannot drift.
FIXED_ANCHORS: dict[str, tuple[int, int, str]] = {
    "morning": (6, 0, "taiwan"),
    "pre_open": (8, 45, "taiwan"),
    "post_close": (14, 20, "taiwan"),
    "us_premarket": (21, 0, "us"),
}
RETIRED_ROUTINE_SLOTS = frozenset({"intraday", "midday", "afternoon", "us_open"})
ANCHOR_SLOTS = frozenset(FIXED_ANCHORS)


def parse_scheduled_for(value: Any) -> datetime | None:
    """Parse an ISO timestamp only when it carries an explicit offset.

    A naive timestamp is unsafe at the receiver because a retrying service may
    run in UTC.  It is therefore rejected rather than silently interpreted as
    Taiwan time.
    """
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(TAIPEI)


def fixed_scheduled_for(slot: str, slot_date: date | str) -> datetime:
    """Return the canonical Taipei timestamp for an anchor/date."""
    name = str(slot).strip()
    if name not in FIXED_ANCHORS:
        raise ValueError(f"unknown scheduled anchor: {name}")
    day = date.fromisoformat(str(slot_date)) if not isinstance(slot_date, date) else slot_date
    hour, minute, _ = FIXED_ANCHORS[name]
    return datetime.combine(day, time(hour, minute), tzinfo=TAIPEI)


def _anchor_date_for_us_premarket(at: datetime) -> date:
    """Keep a 21:00 report that runs after midnight on its prior slot date."""
    local = at.astimezone(TAIPEI)
    return local.date() - timedelta(days=1) if local.hour < 6 else local.date()


def slot_date_for(slot: str, at: datetime) -> str:
    local = at.astimezone(TAIPEI)
    day = _anchor_date_for_us_premarket(local) if slot == "us_premarket" else local.date()
    return day.isoformat()


def validate_scheduled_context(
    *,
    slot: str,
    scheduled_for_at: Any,
    now: datetime,
    contract_version: Any = SCHEDULE_CONTRACT_VERSION,
    time_zone: Any = SCHEDULE_TIMEZONE,
) -> dict[str, Any]:
    """Validate a backup/dispatch schedule context without making it sendable."""
    name = str(slot or "").strip()
    result: dict[str, Any] = {
        "contract_version": str(contract_version or ""),
        "time_zone": str(time_zone or ""),
        "contract_status": "invalid",
        "reason": "",
        "scheduled_slot": name,
    }
    if name in RETIRED_ROUTINE_SLOTS:
        result["reason"] = "invalid_schedule_context:retired_routine_slot"
        return result
    if name not in ANCHOR_SLOTS:
        result["reason"] = "invalid_schedule_context:unknown_scheduled_slot"
        return result
    scheduled = parse_scheduled_for(scheduled_for_at)
    if scheduled is None:
        result["reason"] = (
            "invalid_schedule_context:missing_scheduled_for_at"
            if scheduled_for_at in (None, "")
            else "invalid_schedule_context:invalid_scheduled_for_at"
        )
        return result
    if str(contract_version or "") != SCHEDULE_CONTRACT_VERSION:
        result["reason"] = "invalid_schedule_context:unsupported_contract_version"
        return result
    if str(time_zone or "") != SCHEDULE_TIMEZONE:
        result["reason"] = "invalid_schedule_context:invalid_time_zone"
        return result
    local_now = now.astimezone(TAIPEI)
    if scheduled - local_now > timedelta(seconds=MAX_CLOCK_SKEW_SECONDS):
        result["reason"] = "invalid_schedule_context:future_scheduled_for_at"
        return result
    expected = fixed_scheduled_for(name, scheduled.date())
    if abs((scheduled - expected).total_seconds()) > MAX_CLOCK_SKEW_SECONDS:
        result["reason"] = "invalid_schedule_context:slot_mismatch"
        return result
    delay = max(0, int((local_now - scheduled).total_seconds()))
    result.update({
        "contract_status": "valid",
        "reason": "late_schedule_publish_only" if delay > MAX_SCHEDULE_DELAY_SECONDS else "dispatch_anchor_on_time",
        "scheduled": scheduled,
        "delay_seconds": delay,
        "slot_date": slot_date_for(name, scheduled),
    })
    return result


def build_scheduled_dispatch_payload(
    slot: str,
    scheduled_for_at: str,
    *,
    force: bool = False,
    trigger_kind: str = "cron-job.org",
    trace_id: str = "",
) -> dict[str, Any]:
    """Build the exact Repository Dispatch body used by a backup scheduler."""
    parsed = parse_scheduled_for(scheduled_for_at)
    if parsed is None:
        raise ValueError("scheduled_for_at must be an ISO timestamp with timezone")
    check = validate_scheduled_context(
        slot=slot,
        scheduled_for_at=scheduled_for_at,
        now=parsed,
    )
    if check["contract_status"] != "valid":
        raise ValueError(str(check["reason"]))
    payload: dict[str, Any] = {
        "slot": slot,
        "scheduled_slot": slot,
        "scheduled_for_at": parsed.isoformat(),
        "time_zone": SCHEDULE_TIMEZONE,
        "schedule_contract_version": SCHEDULE_CONTRACT_VERSION,
        "trigger_kind": trigger_kind,
        "force": bool(force),
    }
    if trace_id:
        payload["trace_id"] = str(trace_id)
    return {"event_type": "scheduled-brief", "client_payload": payload}


__all__ = [
    "ANCHOR_SLOTS",
    "CREATOR_BATCH_CRON_SCHEDULES",
    "CREATOR_MORNING_BATCH_TIME",
    "CREATOR_MORNING_LATE_GRACE_MINUTES",
    "FIXED_ANCHORS",
    "MAX_CLOCK_SKEW_SECONDS",
    "MAX_SCHEDULE_DELAY_SECONDS",
    "RETIRED_ROUTINE_SLOTS",
    "SCHEDULE_CONTRACT_VERSION",
    "SCHEDULE_TIMEZONE",
    "TAIPEI_TIMEZONE",
    "build_scheduled_dispatch_payload",
    "creator_batch_cutoff",
    "creator_batch_late_end",
    "fixed_scheduled_for",
    "parse_scheduled_for",
    "slot_date_for",
    "validate_scheduled_context",
]
