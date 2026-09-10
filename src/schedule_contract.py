"""Shared contract for the four production scheduled-brief anchors.

The backup scheduler is outside this repository, so the receiver must be
strict about the information it accepts.  This module is deliberately small:
it validates identity and time only; delivery eligibility is still decided by
the existing briefing evidence and EventLedger gates.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

SCHEDULE_CONTRACT_VERSION = "3"
LEGACY_SCHEDULE_CONTRACT_VERSION = "2"
SCHEDULE_TIMEZONE = "Asia/Taipei"
TAIPEI_TIMEZONE = SCHEDULE_TIMEZONE
TAIPEI = ZoneInfo(SCHEDULE_TIMEZONE)
MAX_SCHEDULE_DELAY_SECONDS = 30 * 60
MAX_CLOCK_SKEW_SECONDS = 5 * 60
CRON_JOB_ORG_DISPATCH_FIELD = "dispatch_unix"

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

# A market-only refresh still needs a real display phase.  Keep this separate
# from ``FIXED_ANCHORS``: intraday/midday/afternoon are valid Pages views, but
# they are retired as routine Telegram anchors.
LIVE_PHASE_BOUNDARIES: tuple[tuple[int, str], ...] = (
    (6 * 60, "morning"),
    (8 * 60 + 30, "pre_open"),
    (9 * 60, "intraday"),
    (11 * 60 + 30, "midday"),
    (12 * 60 + 45, "afternoon"),
    (13 * 60 + 30, "post_close"),
    (21 * 60, "us_premarket"),
)


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


def parse_dispatch_unix(value: Any) -> datetime | None:
    """Parse cron-job.org's execution timestamp as an aware Taipei time.

    cron-job.org expands ``%cjo:unixtime%`` in the request body immediately
    before sending the request.  It is intentionally kept separate from
    ``scheduled_for_at``: the former records when the backup actually arrived,
    while the latter is the fixed production anchor derived below.
    """
    if value in (None, "") or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text or not text.isdigit():
        return None
    try:
        parsed = datetime.fromtimestamp(int(text), tz=UTC)
    except (OverflowError, OSError, ValueError):
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


def live_market_phase_at(at: datetime) -> tuple[str, str]:
    """Return the display phase for a market-only refresh.

    ``build_market_snapshot`` is also used by the Pages-only refresh workflow,
    where there is no scheduled anchor input.  Falling back to ``morning`` in
    that path makes an afternoon snapshot look like a stale morning report.
    This resolver is display metadata only; it does not grant notification
    eligibility to retired routine phases.
    """
    local = at.astimezone(TAIPEI)
    minute = local.hour * 60 + local.minute
    if minute < LIVE_PHASE_BOUNDARIES[0][0]:
        return "us_premarket", (local.date() - timedelta(days=1)).isoformat()
    selected = LIVE_PHASE_BOUNDARIES[0][1]
    for start, candidate in LIVE_PHASE_BOUNDARIES:
        if minute >= start:
            selected = candidate
    return selected, local.date().isoformat()


def _next_anchor_after(slot: str, scheduled: datetime) -> datetime:
    """Return the next fixed anchor after a canonical slot timestamp."""
    ordered = sorted(
        (time(hour, minute), name)
        for name, (hour, minute, _market) in FIXED_ANCHORS.items()
    )
    current = scheduled.timetz().replace(tzinfo=None)
    for anchor_time, _name in ordered:
        if anchor_time > current:
            return datetime.combine(scheduled.date(), anchor_time, tzinfo=TAIPEI)
    next_day = scheduled.date() + timedelta(days=1)
    first_time, _first_name = ordered[0]
    return datetime.combine(next_day, first_time, tzinfo=TAIPEI)


def validate_scheduled_context(
    *,
    slot: str,
    scheduled_for_at: Any,
    now: datetime,
    contract_version: Any = SCHEDULE_CONTRACT_VERSION,
    time_zone: Any = SCHEDULE_TIMEZONE,
    dispatch_unix: Any = None,
    dispatch_trace_id: Any = None,
) -> dict[str, Any]:
    """Validate a backup/dispatch schedule context without making it sendable."""
    name = str(slot or "").strip()
    result: dict[str, Any] = {
        "contract_version": str(contract_version or ""),
        "time_zone": str(time_zone or ""),
        "contract_status": "invalid",
        "reason": "",
        "scheduled_slot": name,
        "dispatch_unix": str(dispatch_unix or ""),
        "dispatch_trace_id": str(dispatch_trace_id or "").strip(),
    }
    if name in RETIRED_ROUTINE_SLOTS:
        result["reason"] = "invalid_schedule_context:retired_routine_slot"
        return result
    if name not in ANCHOR_SLOTS:
        result["reason"] = "invalid_schedule_context:unknown_scheduled_slot"
        return result
    version = str(contract_version or "")
    if version not in {SCHEDULE_CONTRACT_VERSION, LEGACY_SCHEDULE_CONTRACT_VERSION}:
        result["reason"] = "invalid_schedule_context:unsupported_contract_version"
        return result
    if str(time_zone or "") != SCHEDULE_TIMEZONE:
        result["reason"] = "invalid_schedule_context:invalid_time_zone"
        return result
    dispatch_at = parse_dispatch_unix(dispatch_unix)
    scheduled: datetime
    if version == SCHEDULE_CONTRACT_VERSION:
        if dispatch_at is None:
            result["reason"] = (
                "invalid_schedule_context:missing_dispatch_unix"
                if dispatch_unix in (None, "")
                else "invalid_schedule_context:invalid_dispatch_unix"
            )
            return result
        if not str(dispatch_trace_id or "").strip():
            result["reason"] = "invalid_schedule_context:missing_trace_id"
            return result
        scheduled = fixed_scheduled_for(name, slot_date_for(name, dispatch_at))
    elif version == LEGACY_SCHEDULE_CONTRACT_VERSION:
        parsed_scheduled = parse_scheduled_for(scheduled_for_at)
        if parsed_scheduled is None:
            result["reason"] = (
                "invalid_schedule_context:missing_scheduled_for_at"
                if scheduled_for_at in (None, "")
                else "invalid_schedule_context:invalid_scheduled_for_at"
            )
            return result
        scheduled = parsed_scheduled
    else:  # guarded above; keeps type checkers aware that scheduled is assigned
        raise AssertionError("unreachable schedule contract version")
    local_now = now.astimezone(TAIPEI)
    if scheduled - local_now > timedelta(seconds=MAX_CLOCK_SKEW_SECONDS):
        result["reason"] = "invalid_schedule_context:future_scheduled_for_at"
        return result
    expected = fixed_scheduled_for(name, scheduled.date())
    if version == SCHEDULE_CONTRACT_VERSION:
        assert dispatch_at is not None
        if dispatch_at - local_now > timedelta(seconds=MAX_CLOCK_SKEW_SECONDS):
            result["reason"] = "invalid_schedule_context:future_dispatch_unix"
            return result
        if dispatch_at < expected - timedelta(seconds=MAX_CLOCK_SKEW_SECONDS):
            result["reason"] = "invalid_schedule_context:dispatch_before_anchor"
            return result
        if dispatch_at > _next_anchor_after(name, expected) - timedelta(seconds=MAX_CLOCK_SKEW_SECONDS):
            result["reason"] = "invalid_schedule_context:dispatch_outside_anchor_window"
            return result
        if scheduled_for_at not in (None, ""):
            declared = parse_scheduled_for(scheduled_for_at)
            if declared is None or abs((declared - expected).total_seconds()) > MAX_CLOCK_SKEW_SECONDS:
                result["reason"] = "invalid_schedule_context:slot_mismatch"
                return result
    elif abs((scheduled - expected).total_seconds()) > MAX_CLOCK_SKEW_SECONDS:
        result["reason"] = "invalid_schedule_context:slot_mismatch"
        return result
    delay = max(0, int((local_now - scheduled).total_seconds()))
    result.update({
        "contract_status": "valid",
        "reason": "late_schedule_publish_only" if delay > MAX_SCHEDULE_DELAY_SECONDS else "dispatch_anchor_on_time",
        "scheduled": scheduled,
        "dispatch_at": dispatch_at,
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
        contract_version=LEGACY_SCHEDULE_CONTRACT_VERSION,
        time_zone=SCHEDULE_TIMEZONE,
    )
    if check["contract_status"] != "valid":
        raise ValueError(str(check["reason"]))
    payload: dict[str, Any] = {
        "slot": slot,
        "scheduled_slot": slot,
        "scheduled_for_at": parsed.isoformat(),
        "time_zone": SCHEDULE_TIMEZONE,
        # This helper preserves the explicit-timestamp v2 wire format for
        # callers that already have the original anchor.  New cron-job.org
        # jobs should use build_cron_job_dispatch_payload below.
        "schedule_contract_version": LEGACY_SCHEDULE_CONTRACT_VERSION,
        "trigger_kind": trigger_kind,
        "force": bool(force),
    }
    if trace_id:
        payload["trace_id"] = str(trace_id)
    return {"event_type": "scheduled-brief", "client_payload": payload}


def build_cron_job_dispatch_payload(
    slot: str,
    *,
    force: bool = False,
    notify: bool = True,
    trace_placeholder: str = "%cjo:uuid4%",
) -> dict[str, Any]:
    """Build the v3 body to paste into a cron-job.org request.

    The timestamp placeholder is expanded by cron-job.org at send time, so
    this function intentionally returns a template rather than pretending to
    validate the literal placeholder as a Unix timestamp.
    """
    if str(slot).strip() not in ANCHOR_SLOTS:
        raise ValueError(f"unknown scheduled anchor: {slot}")
    return {
        "event_type": "scheduled-brief",
        "client_payload": {
            "slot": str(slot).strip(),
            "scheduled_slot": str(slot).strip(),
            "dispatch_unix": "%cjo:unixtime%",
            "trace_id": trace_placeholder,
            "time_zone": SCHEDULE_TIMEZONE,
            "schedule_contract_version": SCHEDULE_CONTRACT_VERSION,
            "trigger_kind": "cron-job.org",
            "notify": bool(notify),
            "force": bool(force),
        },
    }


__all__ = [
    "ANCHOR_SLOTS",
    "CREATOR_BATCH_CRON_SCHEDULES",
    "CREATOR_MORNING_BATCH_TIME",
    "CREATOR_MORNING_LATE_GRACE_MINUTES",
    "CRON_JOB_ORG_DISPATCH_FIELD",
    "FIXED_ANCHORS",
    "LEGACY_SCHEDULE_CONTRACT_VERSION",
    "MAX_CLOCK_SKEW_SECONDS",
    "MAX_SCHEDULE_DELAY_SECONDS",
    "RETIRED_ROUTINE_SLOTS",
    "SCHEDULE_CONTRACT_VERSION",
    "SCHEDULE_TIMEZONE",
    "TAIPEI_TIMEZONE",
    "build_scheduled_dispatch_payload",
    "build_cron_job_dispatch_payload",
    "creator_batch_cutoff",
    "creator_batch_late_end",
    "fixed_scheduled_for",
    "parse_scheduled_for",
    "parse_dispatch_unix",
    "slot_date_for",
    "validate_scheduled_context",
]
