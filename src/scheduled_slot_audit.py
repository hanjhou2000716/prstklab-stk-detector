"""Read-only audit of the durable receipt for the current US premarket slot."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any

from src.schedule_contract import NEW_YORK, scheduled_anchor_key, us_session_bounds


def _candidate_local_time(cron: str, now: datetime) -> datetime | None:
    fields = str(cron or "").split()
    if len(fields) != 5 or fields[0] != "45" or fields[2:] != ["*", "*", "1-5"]:
        return None
    try:
        hour = int(fields[1])
        if hour not in {13, 14}:
            return None
        current = now.astimezone(UTC)
        candidates = [
            datetime.combine(current.date() - timedelta(days=offset), time(hour, 45), UTC)
            for offset in (0, 1)
        ]
        latest_due = max((candidate for candidate in candidates if candidate <= current), default=None)
        return latest_due.astimezone(NEW_YORK) if latest_due else None
    except (TypeError, ValueError):
        return None


def _load_ledger(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("scheduled_receipt_ledger_invalid") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("delivery_claims"), dict):
        raise ValueError("scheduled_receipt_ledger_invalid")
    return payload


def audit_slot(*, ledger_path: Path, schedule: str, now: datetime) -> dict[str, Any]:
    """Check the exact scheduled-anchor receipt without mutating any data."""
    current = now.astimezone(UTC)
    candidate = _candidate_local_time(schedule, current)
    if candidate is None or candidate.hour != 9 or candidate.minute != 45:
        return {"status": "not_applicable", "reason": "wrong_dst_schedule_candidate", "read_only": True}

    try:
        market_open, _market_close = us_session_bounds(candidate.date())
    except ValueError as exc:
        if str(exc) == "market_closed":
            return {
                "status": "expected_skip", "reason": "nyse_closed_no_us_premarket_report",
                "market_date": candidate.date().isoformat(), "read_only": True,
            }
        return {"status": "blocked", "reason": "nyse_calendar_unavailable", "read_only": True}
    except Exception as exc:
        return {"status": "blocked", "reason": f"nyse_calendar_unavailable_{type(exc).__name__}", "read_only": True}

    audit_after = market_open.replace(second=0, microsecond=0) + timedelta(minutes=15)
    if current.astimezone(NEW_YORK) < audit_after:
        return {"status": "not_due", "reason": "premarket_deadline_not_passed", "read_only": True}

    slot_date = candidate.date().isoformat()
    anchor = scheduled_anchor_key("us_premarket", slot_date)
    claim_key = f"scheduled-anchor:{anchor}"
    try:
        payload = _load_ledger(ledger_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else f"scheduled_receipt_ledger_unavailable_{type(exc).__name__}"
        return {"status": "blocked", "reason": reason, "market_date": slot_date, "anchor": anchor, "read_only": True}
    claims = payload["delivery_claims"]
    claim = claims.get(claim_key)
    if not isinstance(claim, dict):
        return {"status": "missing_receipt", "reason": "scheduled_anchor_claim_missing", "market_date": slot_date, "anchor": anchor, "read_only": True}
    configured = {str(value) for value in claim.get("recipient_hashes", []) if str(value)}
    delivered = {str(value) for value in claim.get("delivered_recipient_hashes", []) if str(value)}
    if claim.get("kind") != "scheduled_brief" or claim.get("anchor_key") != anchor:
        return {"status": "blocked", "reason": "scheduled_anchor_claim_identity_mismatch", "market_date": slot_date, "anchor": anchor, "read_only": True}
    if claim.get("status") != "delivered" or not configured or not configured.issubset(delivered):
        return {
            "status": "incomplete_receipt", "reason": "scheduled_anchor_recipients_not_fully_delivered",
            "market_date": slot_date, "anchor": anchor,
            "recipient_count": len(configured), "delivered_count": len(configured & delivered), "read_only": True,
        }
    return {
        "status": "delivered", "reason": "durable_recipient_receipt_verified",
        "market_date": slot_date, "anchor": anchor,
        "recipient_count": len(configured), "delivered_count": len(configured), "read_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only audit for a scheduled US premarket receipt")
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--schedule", default=os.getenv("GITHUB_EVENT_SCHEDULE", ""))
    parser.add_argument("--now", help="UTC timestamp override for deterministic tests")
    args = parser.parse_args()
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(UTC)
    result = audit_slot(ledger_path=args.ledger, schedule=args.schedule, now=now)
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True)
    print(encoded)
    summary_path = os.getenv("GITHUB_STEP_SUMMARY", "")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write("## US premarket receipt audit\n\n")
            summary.write(f"- status: {result.get('status')}\n")
            summary.write(f"- reason: {result.get('reason')}\n")
            summary.write(f"- market_date: {result.get('market_date', 'not_applicable')}\n")
            summary.write(f"- anchor: {result.get('anchor', 'not_applicable')}\n")
            summary.write(f"- recipient_receipt: {result.get('delivered_count', 0)}/{result.get('recipient_count', 0)}\n")
            summary.write("- mode: read-only; no dispatch, repair, or delivery attempted\n")
    return 1 if result.get("status") in {"blocked", "missing_receipt", "incomplete_receipt"} else 0


__all__ = ["audit_slot"]


if __name__ == "__main__":
    raise SystemExit(main())
