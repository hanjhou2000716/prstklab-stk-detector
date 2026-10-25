"""Shared, bounded notification reservation rules for incident Issues."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

PENDING_CONSUMER = "Alert pending consumer:"
PENDING_SINCE = "Alert pending since:"
NEXT_REMINDER = "Next reminder at:"
REMINDER_INTERVAL = timedelta(minutes=30)


def _timestamp(lines: list[str], prefix: str) -> datetime | None:
    matches = [line[len(prefix):].strip() for line in lines if line.startswith(prefix)]
    if len(matches) != 1:
        return None
    try:
        value = datetime.fromisoformat(matches[0].replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(UTC)


def can_emit_pending_alert(body: object, consumer: str, now: datetime) -> bool:
    """Return true when an old unconfirmed reservation may be retried.

    Reservations from the current reconciliation attempt are never emitted
    twice. A different consumer may retry only after the 30-minute interval.
    Legacy reservations without ``Alert pending since`` use the existing
    reminder timestamp as a conservative migration fallback.
    """
    lines = str(body or "").splitlines()
    owners = [line[len(PENDING_CONSUMER):].strip() for line in lines if line.startswith(PENDING_CONSUMER)]
    since_rows = [line for line in lines if line.startswith(PENDING_SINCE)]
    if not owners:
        return not since_rows
    if len(owners) != 1 or len(since_rows) > 1 or not owners[0]:
        return False
    if owners[0] == consumer:
        return False
    reference = _timestamp(lines, PENDING_SINCE) if since_rows else _timestamp(lines, NEXT_REMINDER)
    if reference is None:
        return False
    return now.astimezone(UTC) - reference >= REMINDER_INTERVAL


def mark_pending_alert(body: str, consumer: str, now: datetime) -> str:
    lines = [
        line for line in body.splitlines()
        if not line.startswith((PENDING_CONSUMER, PENDING_SINCE))
    ]
    lines.extend((f"{PENDING_CONSUMER} {consumer}", f"{PENDING_SINCE} {now.astimezone(UTC).isoformat()}"))
    return "\n".join(lines)[:12000]


def preserve_pending_alert(body: str, prior_body: object) -> str:
    lines = [
        line for line in body.splitlines()
        if not line.startswith((PENDING_CONSUMER, PENDING_SINCE))
    ]
    prior = [
        line for line in str(prior_body or "").splitlines()
        if line.startswith((PENDING_CONSUMER, PENDING_SINCE))
    ]
    return "\n".join([*lines, *prior])[:12000]


def clear_pending_alert(lines: list[str]) -> list[str]:
    return [
        line for line in lines
        if not line.startswith((PENDING_CONSUMER, PENDING_SINCE))
    ]
