"""Point-in-time fundamental and corporate-action safeguards for research."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Iterable


CORPORATE_ACTION_TYPES = frozenset({
    "dividend", "stock_split", "reverse_split", "rights_issue", "capital_reduction",
    "merger", "delisting", "trading_halt", "share_issuance",
})


def parse_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)


def snapshot_is_usable(snapshot: dict[str, Any], decision_time: datetime) -> tuple[bool, str | None]:
    """Reject snapshots that were not public by the decision timestamp."""
    decision = parse_time(decision_time)
    if decision is None:
        return False, "invalid decision time"
    if snapshot.get("point_in_time") is not True:
        return False, "snapshot is not marked point_in_time"
    as_of = parse_time(snapshot.get("as_of"))
    if as_of is None:
        return False, "snapshot as_of is missing or invalid"
    if as_of > decision:
        return False, "snapshot period is after decision time"
    published = parse_time(snapshot.get("published_at"))
    if snapshot.get("published_at") not in (None, "") and published is None:
        return False, "published_at is invalid"
    if published and published > decision:
        return False, "snapshot was published after decision time"
    return True, None


def latest_fundamental_snapshot(
    snapshots: Iterable[dict[str, Any]], *, market: str, ticker: str, decision_time: datetime,
) -> dict[str, Any] | None:
    """Select the newest eligible snapshot without using future information."""
    eligible: list[tuple[datetime, datetime, dict[str, Any]]] = []
    for snapshot in snapshots:
        if snapshot.get("market") != market or str(snapshot.get("ticker")) != str(ticker):
            continue
        usable, _ = snapshot_is_usable(snapshot, decision_time)
        if not usable:
            continue
        as_of = parse_time(snapshot.get("as_of"))
        published = parse_time(snapshot.get("published_at")) or as_of
        if as_of and published:
            eligible.append((as_of, published, snapshot))
    return max(eligible, key=lambda item: (item[0], item[1]))[2] if eligible else None


def normalize_corporate_action(action: dict[str, Any]) -> dict[str, Any]:
    """Validate a public corporate action; preserve provenance fields."""
    action_type = str(action.get("action_type") or "").strip().lower()
    if action_type not in CORPORATE_ACTION_TYPES:
        raise ValueError("unsupported corporate action type")
    action_date = parse_time(action.get("action_date"))
    if action_date is None:
        raise ValueError("corporate action_date is required")
    announced = parse_time(action.get("announced_at"))
    if action.get("announced_at") not in (None, "") and announced is None:
        raise ValueError("corporate action announced_at is invalid")
    return {
        "ticker": str(action.get("ticker") or ""),
        "action_type": action_type,
        "action_date": action_date.isoformat(),
        "announced_at": announced.isoformat() if announced else None,
        "factor": action.get("factor"),
        "source_url": action.get("source_url"),
        "source_tier": action.get("source_tier"),
        "fetched_at": action.get("fetched_at"),
        "point_in_time": True,
    }


def audit_fundamental_snapshots(
    snapshots: Iterable[dict[str, Any]], *, market: str, decision_time: datetime,
) -> dict[str, Any]:
    """Return an explicit audit instead of silently dropping unusable rows."""
    relevant = [item for item in snapshots if item.get("market") == market]
    reasons: list[dict[str, Any]] = []
    usable = 0
    for item in relevant:
        ok, reason = snapshot_is_usable(item, decision_time)
        if ok:
            usable += 1
        else:
            reasons.append({"ticker": item.get("ticker"), "reason": reason})
    return {
        "market": market,
        "decision_time": parse_time(decision_time).isoformat() if parse_time(decision_time) else None,
        "total": len(relevant),
        "usable": usable,
        "blocked": len(reasons),
        "status": "pass" if relevant and not reasons else "partial" if usable else "failed",
        "reasons": reasons,
        "future_data_rejected": True,
    }