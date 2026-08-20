"""Deterministic 10:30 Asia/Taipei Creator batch selection.

The batch boundary is intentionally separate from parsing and consensus.  It
only decides which already-sanitized, successfully parsed episodes belong to
the current morning publication.  It never infers content or market
direction, and it keeps late arrivals visible instead of silently dropping
them.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from src.creator_provider_registry import creator_providers

_TAIPEI = ZoneInfo("Asia/Taipei")
_FAILED = {"parse_failed", "unsupported_template", "invalid_source", "duplicate"}
_DEFAULT_BATCH_TIME = time(10, 30)


def _parse_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)


def _creator_id(record: dict[str, Any]) -> str:
    return str(record.get("creator_id") or record.get("content_origin") or record.get("source") or "").strip().casefold()


def _episode_key(record: dict[str, Any]) -> str:
    return str(record.get("episode_key") or record.get("episode_id") or "").strip()


def _record_time(record: dict[str, Any]) -> datetime | None:
    return _parse_time(record.get("published_at")) or _parse_time(record.get("received_at"))


def _stable_key(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _expected_creators(expected: Iterable[str] | None) -> tuple[str, ...]:
    if expected is not None:
        return tuple(dict.fromkeys(str(item).strip().casefold() for item in expected if str(item).strip()))
    return tuple(item.creator_id for item in creator_providers(enabled_only=True) if item.consensus_eligible)


def build_creator_morning_batch(
    records: Iterable[dict[str, Any]] | None,
    *,
    as_of: datetime | str,
    expected_creators: Iterable[str] | None = None,
    batch_time: time = _DEFAULT_BATCH_TIME,
    late_grace_minutes: int = 180,
) -> dict[str, Any]:
    """Build a stable morning batch from public-safe Creator records.

    ``published_at`` determines the episode's publication date; ``received_at``
    is used only to classify a post-cutoff late arrival.  Previous-day and
    future-day records are excluded, and one latest episode is kept per
    expected creator.  The result is safe to persist in a release artifact.
    """
    now = _parse_time(as_of) if not isinstance(as_of, datetime) else as_of
    if now is None:
        raise ValueError("as_of must be an ISO timestamp or datetime")
    now = now.replace(tzinfo=now.tzinfo or UTC).astimezone(UTC)
    local_now = now.astimezone(_TAIPEI)
    day = local_now.date()
    cutoff_local = datetime.combine(day, batch_time, tzinfo=_TAIPEI)
    cutoff = cutoff_local.astimezone(UTC)
    late_end = cutoff + timedelta(minutes=max(0, int(late_grace_minutes)))
    expected = _expected_creators(expected_creators)
    candidates: list[tuple[datetime, datetime, dict[str, Any], bool]] = []
    rejected = 0
    for raw in records or []:
        if not isinstance(raw, dict):
            continue
        provider = _creator_id(raw)
        episode = _episode_key(raw)
        published = _parse_time(raw.get("published_at"))
        received = _parse_time(raw.get("received_at")) or published
        if provider not in expected or not episode or not published or not received:
            rejected += 1
            continue
        if str(raw.get("parse_status") or "").strip().casefold() in _FAILED or raw.get("public_safe") is False:
            rejected += 1
            continue
        if published.astimezone(_TAIPEI).date() != day:
            rejected += 1
            continue
        # Point-in-time guard: a batch must never include an episode that was
        # published or received after the snapshot's ``as_of`` boundary.
        # Without this check a delayed export containing future rows could be
        # attached to an earlier release and look like a morning observation.
        if published > now or received > now:
            rejected += 1
            continue
        # A publication after the scheduled cutoff is not a morning item yet,
        # unless it arrived during the bounded late-arrival grace window.
        if published > late_end or received > late_end:
            rejected += 1
            continue
        late = received > cutoff or published > cutoff
        candidates.append((published, received, raw, late))

    latest: dict[str, tuple[datetime, datetime, dict[str, Any], bool]] = {}
    for row in candidates:
        provider = _creator_id(row[2])
        previous = latest.get(provider)
        if previous is None or (row[0], row[1], _episode_key(row[2])) > (previous[0], previous[1], _episode_key(previous[2])):
            latest[provider] = row

    selected: list[dict[str, Any]] = []
    late_arrivals: list[str] = []
    for provider in expected:
        selected_row: tuple[datetime, datetime, dict[str, Any], bool] | None = latest.get(provider)
        if selected_row is None:
            continue
        item = dict(selected_row[2])
        item["batch_late_arrival"] = bool(selected_row[3])
        selected.append(item)
        if selected_row[3]:
            late_arrivals.append(provider)
    selected.sort(key=lambda item: (_creator_id(item), _episode_key(item)))
    missing = [provider for provider in expected if provider not in {_creator_id(item) for item in selected}]
    count = len(selected)
    state = "complete" if count == len(expected) else "partial" if count else "no_new_content"
    episode_keys = [_episode_key(item) for item in selected]
    batch_key = f"creator-morning:{day.isoformat()}:{_stable_key({'creators': expected, 'episodes': sorted(episode_keys)})}"
    return {
        "batch_key": batch_key,
        "batch_date": day.isoformat(),
        "scheduled_at": cutoff_local.isoformat(),
        "as_of": now.isoformat(),
        "timezone": "Asia/Taipei",
        "state": state,
        "expected_count": len(expected),
        "received_count": count,
        "missing_creators": missing,
        "late_arrivals": sorted(late_arrivals),
        "late_arrival_count": len(late_arrivals),
        "rejected_count": rejected,
        "records": selected,
        "idempotency_key": batch_key,
    }


__all__ = ["build_creator_morning_batch"]
