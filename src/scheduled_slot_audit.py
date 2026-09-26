"""Read-only receipt audit for all four scheduled notification anchors."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any

from src.schedule_contract import NEW_YORK, TAIPEI, scheduled_anchor_key

SCHEDULE_TO_SLOT = {
    "45 22 * * *": "morning",
    "30 1 * * 1-5": "pre_open",
    "5 7 * * 1-5": "post_close",
    "45 13 * * 1-5": "us_premarket",
    "45 14 * * 1-5": "us_premarket",
}


def _candidate_occurrence(schedule: str, reference: datetime) -> datetime | None:
    """Return the most recent UTC occurrence represented by this exact cron."""
    slot = SCHEDULE_TO_SLOT.get(str(schedule or "").strip())
    if slot is None:
        return None
    current = reference.astimezone(UTC)
    try:
        hour_text, minute_text = schedule.split()[1], schedule.split()[0]
        hour, minute = int(hour_text), int(minute_text)
    except (IndexError, TypeError, ValueError):
        return None
    for offset in range(8):
        day = current.date() - timedelta(days=offset)
        if schedule.endswith("1-5") and day.weekday() >= 5:
            continue
        candidate = datetime.combine(day, time(hour, minute), UTC)
        if candidate <= current:
            return candidate
    return None


def _candidate_slot(schedule: str, occurrence: datetime) -> tuple[str, datetime] | None:
    slot = SCHEDULE_TO_SLOT.get(schedule)
    if slot is None:
        return None
    if slot == "us_premarket":
        local = occurrence.astimezone(NEW_YORK)
        if local.hour != 9 or local.minute != 45:
            return None
        return slot, local
    local = occurrence.astimezone(TAIPEI)
    expected = {"morning": (6, 45), "pre_open": (9, 30), "post_close": (15, 5)}[slot]
    if (local.hour, local.minute) != expected:
        return None
    return slot, local


def _load_ledger(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("scheduled_receipt_ledger_invalid") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("delivery_claims"), dict):
        raise ValueError("scheduled_receipt_ledger_invalid")
    return payload


def _calendar_snapshot(slot: str, day: datetime) -> dict[str, Any]:
    """Build calendar evidence with independent TWSE and TAIFEX sources."""
    from src.market_data import get_market_status
    from src.taifex_calendar import get_taifex_index_futures_status

    target = day.date()
    if slot == "us_premarket":
        return {"markets": {"us": get_market_status("us", target)}}
    cash = get_market_status("taiwan", target)
    cash["calendar_provider"] = "pandas_market_calendars"
    futures = get_taifex_index_futures_status(target, now=day)
    return {"markets": {"taiwan_cash": cash, "taiwan_futures": futures}}


def _receipt_result(payload: dict[str, Any], *, anchor: str, slot_date: str) -> dict[str, Any]:
    claims = payload["delivery_claims"]
    claim = claims.get(f"scheduled-anchor:{anchor}")
    base = {"market_date": slot_date, "anchor": anchor, "read_only": True}
    if not isinstance(claim, dict):
        return {"status": "missing_receipt", "reason": "scheduled_anchor_claim_missing", **base}
    configured = {str(value) for value in claim.get("recipient_hashes", []) if str(value)}
    delivered = {str(value) for value in claim.get("delivered_recipient_hashes", []) if str(value)}
    if claim.get("kind") != "scheduled_brief" or claim.get("anchor_key") != anchor:
        return {"status": "blocked", "reason": "scheduled_anchor_claim_identity_mismatch", **base}
    if claim.get("status") != "delivered" or not configured or not configured.issubset(delivered):
        return {
            "status": "incomplete_receipt", "reason": "scheduled_anchor_recipients_not_fully_delivered",
            "recipient_count": len(configured), "delivered_count": len(configured & delivered), **base,
        }
    return {
        "status": "delivered", "reason": "durable_recipient_receipt_verified",
        "recipient_count": len(configured), "delivered_count": len(configured), **base,
    }


def audit_slot(
    *,
    ledger_path: Path,
    schedule: str,
    now: datetime,
    run_created_at: datetime | str | None = None,
) -> dict[str, Any]:
    """Audit the immutable scheduled occurrence; never mutate or resend."""
    reference = run_created_at
    if isinstance(reference, str):
        try:
            reference = datetime.fromisoformat(reference.replace("Z", "+00:00"))
        except ValueError:
            return {"status": "blocked", "reason": "workflow_run_created_at_invalid", "read_only": True}
    if reference is None:
        reference = now
    if reference.tzinfo is None or reference.utcoffset() is None:
        return {"status": "blocked", "reason": "workflow_run_created_at_invalid", "read_only": True}
    occurrence = _candidate_occurrence(schedule, reference)
    selected = _candidate_slot(schedule, occurrence) if occurrence else None
    if selected is None:
        return {"status": "not_applicable", "reason": "schedule_candidate_not_applicable", "read_only": True}
    slot, anchor_local = selected
    current = now.astimezone(UTC)
    if current < anchor_local.astimezone(UTC):
        return {"status": "not_due", "reason": "audit_deadline_not_passed", "slot": slot, "read_only": True}
    slot_date = anchor_local.date().isoformat()
    anchor = scheduled_anchor_key(slot, slot_date)
    try:
        from src.scheduled_delivery import _resolve_delivery_obligation

        snapshot = _calendar_snapshot(slot, anchor_local)
        obligation, policy_reason, _states = _resolve_delivery_obligation(
            snapshot,
            slot,
            {
                "slot_date": slot_date,
                "delivery_intent": "notify_candidate",
                "resolution_reason": "scheduled_receipt_audit",
                "contract_status": "valid",
            },
            notification_requested=True,
        )
    except Exception as exc:
        return {
            "status": "blocked", "reason": f"market_calendar_unavailable_{type(exc).__name__}",
            "slot": slot, "market_date": slot_date, "anchor": anchor, "read_only": True,
        }
    if obligation == "expected_skip":
        return {
            "status": "expected_skip", "reason": policy_reason, "slot": slot,
            "obligation": obligation, "market_date": slot_date, "anchor": anchor, "read_only": True,
        }
    if obligation == "blocked":
        return {
            "status": "blocked", "reason": policy_reason, "slot": slot,
            "obligation": obligation, "market_date": slot_date, "anchor": anchor, "read_only": True,
        }
    try:
        payload = _load_ledger(ledger_path)
    except (OSError, ValueError, UnicodeError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else f"scheduled_receipt_ledger_unavailable_{type(exc).__name__}"
        return {
            "status": "blocked", "reason": reason, "slot": slot, "obligation": obligation,
            "market_date": slot_date, "anchor": anchor, "read_only": True,
        }
    result = _receipt_result(payload, anchor=anchor, slot_date=slot_date)
    result.update({"slot": slot, "obligation": obligation, "policy_reason": policy_reason})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only audit for scheduled notification receipts")
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--schedule", default=os.getenv("GITHUB_EVENT_SCHEDULE", ""))
    parser.add_argument("--run-created-at", default=os.getenv("RUN_CREATED_AT", ""))
    parser.add_argument("--now", help="UTC timestamp override for deterministic tests")
    args = parser.parse_args()
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(UTC)
    result = audit_slot(
        ledger_path=args.ledger,
        schedule=args.schedule,
        now=now,
        run_created_at=args.run_created_at or None,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    summary_path = os.getenv("GITHUB_STEP_SUMMARY", "")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write("## Scheduled slot recipient receipt audit\n\n")
            for key in ("status", "reason", "slot", "obligation", "market_date", "anchor"):
                summary.write(f"- {key}: {result.get(key, 'not_applicable')}\n")
            summary.write(
                f"- recipient_receipt: {result.get('delivered_count', 0)}/{result.get('recipient_count', 0)}\n"
            )
            summary.write("- mode: read-only; no dispatch, repair, or delivery attempted\n")
    return 1 if result.get("status") in {"blocked", "missing_receipt", "incomplete_receipt"} else 0


__all__ = ["audit_slot"]


if __name__ == "__main__":
    raise SystemExit(main())
