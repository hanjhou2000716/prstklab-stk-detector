"""Deterministic, non-directional consensus for public creator insights.

Creator commentary is a separate evidence lane from market events. This module
only compares explicit, attributed fields from the latest valid episode of each
creator; it never infers a stance from prose and never emits a trading signal.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime, timedelta
from typing import Any

_STANCES = {"risk_on", "risk_off", "neutral"}
_INVALID_PARSE_STATES = {"parse_failed", "unsupported_template", "invalid_source", "duplicate"}
_EVIDENCE_STATES = {"aligned", "partially_aligned", "insufficient_evidence", "stale", "not_verifiable"}
_TOPIC_ALIASES = {
    "nvda": "NVDA", "nvidia": "NVDA", "輝達": "NVDA", "英偉達": "NVDA",
    "tsm": "TSM", "tsmc": "TSM", "台積電": "TSM", "臺積電": "TSM", "taiwan semiconductor": "TSM",
    "ai infrastructure": "AI infrastructure", "ai基建": "AI infrastructure", "ai基礎建設": "AI infrastructure", "算力基礎設施": "AI infrastructure",
    "semiconductor": "semiconductor", "半導體": "semiconductor", "芯片": "semiconductor", "晶片": "semiconductor",
    "oil": "oil", "crude oil": "oil", "原油": "oil", "石油": "oil",
    "gold": "gold", "黃金": "gold", "黄金": "gold",
    "rates": "rates", "interest rates": "rates", "利率": "rates",
    "加密貨幣": "crypto", "加密货币": "crypto", "crypto": "crypto",
}


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


def canonical_topic(value: Any) -> str:
    """Return a stable topic label while preserving unknown topics."""
    text = unicodedata.normalize("NFKC", _text(value)).casefold()
    text = re.sub(r"[\s_\-/]+", " ", text).strip()
    return _TOPIC_ALIASES.get(text, text)


def _topics(record: dict[str, Any]) -> list[str]:
    values = record.get("topics") or []
    if not isinstance(values, list):
        return []
    result = [canonical_topic(value) for value in values]
    return list(dict.fromkeys(value for value in result if value))


def _creator_key(record: dict[str, Any]) -> str:
    return _text(record.get("creator_id") or record.get("content_origin")).casefold()


def _creator_label(record: dict[str, Any]) -> str:
    return _text(record.get("creator_id") or record.get("content_origin"))


def _episode_time(record: dict[str, Any]) -> datetime | None:
    return _time(record.get("updated_at")) or _time(record.get("published_at")) or _time(record.get("received_at"))


def _valid(record: Any) -> bool:
    # Direct callers from older releases may omit episode_key; the normalized
    # pipeline always supplies it.  Keep those records comparable while still
    # requiring an attributed creator and a non-failed parser state.
    if not isinstance(record, dict) or not _creator_key(record):
        return False
    if record.get("public_safe") is False:
        return False
    return _text(record.get("parse_status")).casefold() not in _INVALID_PARSE_STATES


def _latest_valid(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select exactly one deterministic, latest record per creator."""
    selected: dict[str, dict[str, Any]] = {}
    minimum = datetime.min.replace(tzinfo=UTC)
    for record in records:
        if not _valid(record):
            continue
        key = _creator_key(record)
        current = selected.get(key)
        candidate_sort = (_episode_time(record) or minimum, _text(record.get("episode_key")))
        current_sort = ((_episode_time(current) if current else None) or minimum, _text(current.get("episode_key")) if current else "")
        if current is None or candidate_sort > current_sort:
            selected[key] = record
    return [selected[key] for key in sorted(selected)]


def _contributors(records: list[dict[str, Any]]) -> list[str]:
    values = (_creator_label(item) for item in records)
    return sorted({value for value in values if value}, key=str.casefold)


def _explicit_stance(record: dict[str, Any]) -> str:
    value = _text(record.get("consensus_stance")).casefold()
    return value if value in _STANCES else ""


def _risk_tags(record: dict[str, Any]) -> set[str]:
    values = record.get("risk_topics") or record.get("risk_factors") or []
    if not isinstance(values, list):
        return set()
    result = [canonical_topic(value) for value in values]
    return {value for value in result if value}


def _evidence_alignment(records: list[dict[str, Any]]) -> str:
    values: list[str] = []
    for record in records:
        correlation = record.get("prstk_correlation")
        value = correlation.get("evidence_alignment") if isinstance(correlation, dict) else record.get("evidence_alignment")
        value = _text(value).casefold()
        values.append(value if value in _EVIDENCE_STATES else "insufficient_evidence")
    if not values:
        return "insufficient_evidence"
    if "stale" in values:
        return "stale"
    if all(value == "aligned" for value in values):
        return "aligned"
    if any(value == "partially_aligned" for value in values):
        return "partially_aligned"
    return "insufficient_evidence"


def build_creator_consensus(
    records: list[dict[str, Any]],
    *,
    as_of: Any = None,
    max_age_hours: int = 36,
) -> dict[str, Any]:
    """Build a public-safe V2 consensus from latest valid creator episodes."""
    latest = _latest_valid(records)
    contributors = _contributors(latest)
    topic_records: dict[str, list[dict[str, Any]]] = {}
    for record in latest:
        for topic in _topics(record):
            topic_records.setdefault(topic, []).append(record)

    topics: list[dict[str, Any]] = []
    aligned_views: list[dict[str, Any]] = []
    divergent_views: list[dict[str, Any]] = []
    explicit_stances: list[str] = []
    for topic in sorted(topic_records):
        items = topic_records[topic]
        topic_contributors = _contributors(items)
        stance_by_creator = {
            _creator_label(item): _explicit_stance(item)
            for item in items
            if _explicit_stance(item)
        }
        stances = sorted(set(stance_by_creator.values()))
        explicit_stances.extend(stances)
        if len(topic_contributors) < 2:
            state = "insufficient_sources"
        elif not stances:
            state = "pending_verification"
        elif len(stances) == 1:
            state = "aligned"
        else:
            state = "mixed"
        item = {
            "topic": topic,
            "contributors": topic_contributors,
            "contributor_count": len(topic_contributors),
            "episode_count": len(items),
            "stance": stances[0] if len(stances) == 1 else "mixed" if len(stances) > 1 else "unknown",
            "stance_by_creator": stance_by_creator,
            "consensus_state": state,
            "evidence_state": "comparable" if state == "aligned" else "divergent" if state == "mixed" else "insufficient",
        }
        topics.append(item)
        view = {"topic": topic, "contributors": topic_contributors, "stance": item["stance"]}
        if state == "aligned":
            aligned_views.append(view)
        elif state == "mixed":
            divergent_views.append(view)

    if len(contributors) < 2:
        state = "insufficient_sources"
    elif not explicit_stances:
        state = "pending_verification"
    elif len(set(explicit_stances)) == 1:
        state = "aligned"
    else:
        state = "mixed"

    dates = [date for record in latest if (date := _episode_time(record)) is not None]
    latest_as_of = max(dates) if dates else None
    reference_time = _time(as_of)
    freshness = "unknown"
    if reference_time and latest_as_of:
        freshness = "stale" if reference_time - latest_as_of > timedelta(hours=max(1, int(max_age_hours))) else "current"
        if freshness == "stale":
            state = "stale"

    risk_sets = [_risk_tags(record) for record in latest]
    common_risks = sorted(set.intersection(*risk_sets), key=str.casefold) if risk_sets and all(risk_sets) else []
    evidence_alignment = _evidence_alignment(latest)
    return {
        "consensus_state": state,
        "directional_consensus": state,
        "risk_consensus": "aligned" if common_risks and len(contributors) >= 2 else "insufficient_evidence",
        "topic_consensus": topics,
        "consensus_topics": topics,
        "contributors": contributors,
        "coverage": f"{len(contributors)}/{len(latest)}",
        "source_count": len(contributors),
        "aligned_views": aligned_views,
        "divergent_views": divergent_views,
        "common_risks": common_risks,
        "evidence_alignment": evidence_alignment,
        "freshness_state": freshness,
        "as_of": latest_as_of.isoformat() if latest_as_of else None,
        "is_investment_signal": False,
    }


__all__ = ["build_creator_consensus", "canonical_topic"]
