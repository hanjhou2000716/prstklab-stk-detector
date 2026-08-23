"""Evidence-only correlation between creator insights and PRStK snapshots.

This module deliberately does not interpret prose or turn a creator opinion
into a market signal.  It only records whether the public market/research
artifacts contain comparable, time-bound evidence for the explicit entities
mentioned by an insight.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

_STALE_HOURS = 36


def _text(value: Any) -> str:
    return str(value or "").strip()


def _time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)


def _snapshot_id(snapshot: dict[str, Any] | None, preferred: str | None = None) -> str:
    if not isinstance(snapshot, dict):
        return ""
    keys = [preferred, "snapshot_id", "market_snapshot_id", "research_snapshot_id", "event_snapshot_id"]
    return next((_text(snapshot.get(key)) for key in keys if key and _text(snapshot.get(key))), "")


def _snapshot_time(snapshot: dict[str, Any] | None) -> datetime | None:
    if not isinstance(snapshot, dict):
        return None
    # Release artifacts use ``generated_at`` as their immutable observation
    # timestamp, while the runtime briefing envelope may expose ``as_of``.
    # Accept both forms so release-time correlation does not incorrectly mark
    # a valid snapshot as missing its observation time.
    return _time(
        snapshot.get("as_of")
        or snapshot.get("generated_at")
        or snapshot.get("fetched_at")
        or snapshot.get("created_at")
    )


def _is_stale(snapshot: dict[str, Any] | None, *, now: datetime, max_age_hours: int) -> bool:
    observed_at = _snapshot_time(snapshot)
    return observed_at is not None and now - observed_at > timedelta(hours=max(1, int(max_age_hours)))


def _strings(value: Any) -> set[str]:
    if not isinstance(value, (list, tuple, set)):
        return set()
    return {_text(item).casefold() for item in value if _text(item)}


def _market_entities(snapshot: dict[str, Any] | None) -> tuple[set[str], set[str]]:
    """Extract only explicit public identifiers and sector labels."""
    if not isinstance(snapshot, dict):
        return set(), set()
    records: list[dict[str, Any]] = []
    for key in (
        "quotes", "indices", "macro_quotes", "items", "markets", "candidates",
        "formal_candidates", "observation_candidates", "events", "event_records",
    ):
        value = snapshot.get(key)
        if isinstance(value, list):
            records.extend(item for item in value if isinstance(item, dict))
        elif isinstance(value, dict):
            records.extend(item for item in value.values() if isinstance(item, dict))
    tickers: set[str] = set()
    sectors: set[str] = set()
    for record in records:
        for key in ("ticker", "symbol", "code", "instrument"):
            if record.get(key):
                tickers.add(_text(record[key]).casefold())
        sectors.update(_strings(record.get("sectors") or record.get("sector") or record.get("affected_sectors")))
        sectors.update(_strings(record.get("topics") or record.get("topic")))
        tickers.update(_strings(record.get("affected_instruments") or record.get("instruments")))
    return tickers, sectors


def correlate_creator_insight(
    insight: dict[str, Any],
    *,
    market_snapshot: dict[str, Any] | None = None,
    research_snapshot: dict[str, Any] | None = None,
    event_snapshot: dict[str, Any] | None = None,
    as_of: Any = None,
    max_age_hours: int = _STALE_HOURS,
) -> dict[str, Any]:
    """Return a conservative, public-safe correlation record.

    ``aligned`` means an explicit ticker/sector appears in a supplied public
    artifact.  It is not a directional or investment conclusion.  Missing or
    stale artifacts remain visible as pending states rather than being guessed.
    """
    now = _time(as_of) or datetime.now(UTC)
    market_id = _snapshot_id(market_snapshot)
    research_id = _snapshot_id(research_snapshot, "research_snapshot_id")
    event_id = _snapshot_id(event_snapshot, "event_snapshot_id")
    creator_tickers = _strings(insight.get("tickers"))
    creator_sectors = _strings(insight.get("sectors"))
    topic_tokens = _strings(insight.get("topics"))
    market_tickers: set[str] = set()
    market_sectors: set[str] = set()
    if not isinstance(market_snapshot, dict) and not isinstance(research_snapshot, dict) and not isinstance(event_snapshot, dict):
        state, reason = "not_comparable", "market_and_research_snapshots_missing"
    elif not isinstance(market_snapshot, dict):
        state, reason = "awaiting_market", "market_snapshot_missing"
    else:
        market_tickers, market_sectors = _market_entities(market_snapshot)
        observed_at = _snapshot_time(market_snapshot)
        if observed_at is None:
            state, reason = "awaiting_market", "market_snapshot_time_missing"
        elif now - observed_at > timedelta(hours=max(1, int(max_age_hours))):
            state, reason = "stale", "market_snapshot_stale"
        else:
            matched_tickers = sorted(creator_tickers & market_tickers)
            matched_sectors = sorted(creator_sectors & market_sectors)
            # Topics are only retained as context; they do not establish
            # correlation without an explicit instrument or sector match.
            state = "aligned" if matched_tickers or matched_sectors else "awaiting_market"
            reason = "explicit_entity_match" if state == "aligned" else "no_explicit_entity_match"
    matched_tickers = sorted(creator_tickers & market_tickers)
    matched_sectors = sorted(creator_sectors & market_sectors)
    normalized_as_of = _time(as_of)
    snapshot_ids = {
        "market": market_id,
        "research": research_id,
        "event": event_id,
    }
    available = [snapshot for snapshot in (market_snapshot, research_snapshot, event_snapshot) if isinstance(snapshot, dict)]
    stale_contexts = [
        label
        for label, snapshot in (("market", market_snapshot), ("research", research_snapshot), ("event", event_snapshot))
        if isinstance(snapshot, dict) and _is_stale(snapshot, now=now, max_age_hours=max_age_hours)
    ]
    research_tickers, research_sectors = _market_entities(research_snapshot)
    event_tickers, event_sectors = _market_entities(event_snapshot)
    matched_research = sorted((creator_tickers & research_tickers) | (creator_sectors & research_sectors))
    matched_event = sorted((creator_tickers & event_tickers) | (creator_sectors & event_sectors))
    matched_entities = sorted(set(matched_tickers + matched_sectors + matched_research + matched_event))
    evidence_sources = [label for label, snapshot in (("market", market_snapshot), ("research", research_snapshot), ("event", event_snapshot)) if isinstance(snapshot, dict)]
    if stale_contexts:
        evidence_alignment = "stale"
    elif not available or not matched_entities:
        evidence_alignment = "insufficient_evidence"
    elif sum(bool(matches) for matches in (matched_tickers, matched_research, matched_event)) >= 2:
        evidence_alignment = "aligned"
    else:
        evidence_alignment = "partially_aligned"
    return {
        "correlation_state": state,
        "reason": reason,
        "matched_tickers": matched_tickers,
        "matched_sectors": matched_sectors,
        "creator_topics": sorted(topic_tokens),
        "market_snapshot_id": market_id,
        "research_snapshot_id": research_id,
        "event_snapshot_id": event_id,
        "snapshot_ids": snapshot_ids,
        "evidence_alignment": evidence_alignment,
        "evidence_sources": evidence_sources,
        "matched_event_entities": matched_event,
        "stale_contexts": stale_contexts,
        "as_of": normalized_as_of.isoformat() if normalized_as_of else now.isoformat(),
        "evidence": [
            item for item in (
                "market_snapshot" if market_id else "",
                "research_snapshot" if research_id else "",
            ) if item
        ],
        "is_investment_signal": False,
    }


__all__ = ["correlate_creator_insight"]
