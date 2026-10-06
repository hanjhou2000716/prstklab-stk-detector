"""Identify expired automatic report occurrences before heavy setup starts."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
NEW_YORK = ZoneInfo("America/New_York")
EXPIRY = timedelta(minutes=30)
CRON_SLOTS = {
    "0 22 * * *": "morning",
    "45 0 * * 1-5": "pre_open",
    "20 6 * * 1-5": "post_close",
    "0 13 * * 1-5": "us_premarket",
    "0 14 * * 1-5": "us_premarket",
}
ANCHOR_TIME = {
    "morning": time(6, 0),
    "pre_open": time(8, 45),
    "post_close": time(14, 20),
    # The normal NYSE open is 09:30 local; the report anchor is 30 minutes earlier.
    "us_premarket": time(9, 0),
}


def _parse_aware(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        result = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return result if result.tzinfo is not None and result.utcoffset() is not None else None


def expired_occurrence(
    *,
    event_name: str,
    schedule: str = "",
    payload: dict[str, object] | None = None,
    now: datetime | None = None,
) -> dict[str, str] | None:
    """Return immutable slot context only when a trusted automatic slot expired."""
    event = str(event_name or "").strip()
    body = payload or {}
    slot = ""
    timezone = TAIPEI
    anchor: datetime | None = None

    if event == "schedule":
        slot = CRON_SLOTS.get(str(schedule or "").strip(), "")
        if not slot:
            return None
        created = _parse_aware(body.get("run_created_at"))
        if created is None:
            return None
        timezone = NEW_YORK if slot == "us_premarket" else TAIPEI
        local_day = created.astimezone(timezone).date()
        anchor = datetime.combine(local_day, ANCHOR_TIME[slot], tzinfo=timezone)
    elif event == "repository_dispatch":
        slot = str(body.get("scheduled_slot") or body.get("slot") or "").strip()
        if slot not in ANCHOR_TIME:
            return None
        version = str(body.get("schedule_contract_version") or body.get("contract_version") or "").strip()
        if version not in {"2", "3", "4"}:
            return None
        timezone = NEW_YORK if slot == "us_premarket" else TAIPEI
        declared_timezone = str(body.get("time_zone") or "").strip()
        expected_timezone = "America/New_York" if slot == "us_premarket" else "Asia/Taipei"
        allowed_timezones = {expected_timezone}
        if version in {"2", "3"}:
            allowed_timezones.add("Asia/Taipei")
        if declared_timezone not in allowed_timezones:
            return None
        if version in {"3", "4"} and not str(body.get("trace_id") or "").strip():
            return None
        raw_dispatch = body.get("dispatch_unix")
        dispatched: datetime | None = None
        if raw_dispatch not in (None, ""):
            try:
                if isinstance(raw_dispatch, bool) or not str(raw_dispatch).isdigit():
                    return None
                dispatched = datetime.fromtimestamp(int(str(raw_dispatch)), tz=UTC)
            except (OverflowError, OSError, TypeError, ValueError):
                return None
        declared_anchor = _parse_aware(body.get("scheduled_for_at"))
        source_time = declared_anchor if version == "2" else dispatched
        if source_time is None:
            return None
        local_day = source_time.astimezone(timezone).date()
        anchor = datetime.combine(local_day, ANCHOR_TIME[slot], tzinfo=timezone)
        if abs((source_time.astimezone(UTC) - anchor.astimezone(UTC)).total_seconds()) > 300:
            return None
        if declared_anchor is not None and abs(
            (declared_anchor.astimezone(UTC) - anchor.astimezone(UTC)).total_seconds()
        ) > 300:
            return None
    else:
        return None

    current = (now or datetime.now(UTC)).astimezone(UTC)
    deadline = anchor + EXPIRY
    if current < deadline.astimezone(UTC):
        return None
    assert anchor is not None
    return {
        "slot": slot,
        "slot_date": local_day.isoformat(),
        "anchor": anchor.isoformat(),
        "deadline": deadline.isoformat(),
        "detected_at": current.isoformat(),
        "reason": "expired_scheduled_occurrence",
    }


def main() -> int:
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    try:
        event_payload = json.loads(Path(event_path).read_text(encoding="utf-8")) if event_path else {}
    except (OSError, UnicodeError, json.JSONDecodeError):
        event_payload = {}
    if not isinstance(event_payload, dict):
        event_payload = {}
    payload = event_payload.get("client_payload")
    if not isinstance(payload, dict):
        payload = {}
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule":
        payload = {"run_created_at": os.environ.get("RUN_CREATED_AT", "")}
    result = expired_occurrence(
        event_name=os.environ.get("GITHUB_EVENT_NAME", ""),
        schedule=os.environ.get("GITHUB_EVENT_SCHEDULE", ""),
        payload=payload,
    )
    output = os.environ.get("GITHUB_OUTPUT", "")
    if result is None:
        if output:
            with Path(output).open("a", encoding="utf-8") as handle:
                handle.write("expired=false\n")
        print("expired=false")
        return 0
    if output:
        with Path(output).open("a", encoding="utf-8") as handle:
            handle.write("expired=true\n")
            handle.write(f"expired_reason={result['reason']}\n")
            handle.write(f"expired_slot={result['slot']}\n")
            handle.write(f"expired_slot_date={result['slot_date']}\n")
            handle.write(f"expired_anchor={result['anchor']}\n")
            handle.write(f"expired_deadline={result['deadline']}\n")
            handle.write(f"expired_detected_at={result['detected_at']}\n")
    print(
        f"::notice title=Scheduled report expired::{result['slot']} "
        f"{result['slot_date']} stopped before writer queue; original deadline {result['deadline']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
