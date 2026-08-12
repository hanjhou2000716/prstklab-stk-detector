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


def _snapshot_id(snapshot: dict[str, Any] | None) -> str:
    if not isinstance(snapshot, dict):
        return ""
    return _text(snapshot.get("snapshot_id") or snapshot.get("market_snapshot_id") or snapshot.get("research_snapshot_id"))


def _snapshot_time(snapshot: dict[str, Any] | None) -> datetime | None:
    if not isinstance(snapshot, dict):
        return None
    return _time(snapshot.get("as_of") or snapshot.get("fetched_at") or snapshot.get("created_at"))


def _strings(value: Any) -> set[str]:
    if not isinstance(value, (list, tuple, set)):
        return set()
    return {_text(item).casefold() for item in value if _text(item)}


def _market_entities(snapshot: dict[str, Any] | None) -> tuple[set[str], set[str]]:
    """Extract only explicit public identifiers and sector labels."""
    if not isinstance(snapshot, dict):
        return set(), set()
    records: list[dict[str, Any]] = []
    for key in ("quotes", "indices", "macro_quotes", "items", "markets"):
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
        sectors.update(_strings(record.get("sectors") or record.get("sector")))
    return tickers, sectors


def correlate_creator_insight(
    insight: dict[str, Any],
    *,
    market_snapshot: dict[str, Any] | None = None,
    research_snapshot: dict[str, Any] | None = None,
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
    research_id = _snapshot_id(research_snapshot)
    creator_tickers = _strings(insight.get("tickers"))
    creator_sectors = _strings(insight.get("sectors"))
    topic_tokens = _strings(insight.get("topics"))
    if not isinstance(market_snapshot, dict) and not isinstance(research_snapshot, dict):
        state, reason = "not_comparable", "market_and_research_snapshots_missing"
        market_tickers, market_sectors = set(), set()
    elif not isinstance(market_snapshot, dict):
        state, reason = "awaiting_market", "market_snapshot_missing"
        market_tickers, market_sectors = set(), set()
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
    return {
        "correlation_state": state,
        "reason": reason,
        "matched_tickers": matched_tickers,
        "matched_sectors": matched_sectors,
        "creator_topics": sorted(topic_tokens),
        "market_snapshot_id": market_id,
        "research_snapshot_id": research_id,
        "as_of": _time(as_of).isoformat() if _time(as_of) else now.isoformat(),
        "evidence": [
            item for item in (
                "market_snapshot" if market_id else "",
                "research_snapshot" if research_id else "",
            ) if item
        ],
        "is_investment_signal": False,
    }


__all__ = ["correlate_creator_insight"]
