"""Cross-source evidence matching for public event records.

News, official releases and discovery feeds can describe one event with very
different wording.  This module keeps the matching deterministic and
auditable: a corroborated event needs two different source domains, a shared
entity/place anchor and a shared action.  It never treats a single headline
as confirmation.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.event_classifier import build_haystack, classify_event_fields, normalize_text
from src.intel_contract import normalize_event_record, source_domain

_KEYWORD_PATH = Path(__file__).resolve().parents[1] / "config" / "event_keywords.json"


def _load_database() -> dict[str, Any]:
    try:
        return json.loads(_KEYWORD_PATH.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}


_DATABASE = _load_database()
_GDELT_VALUE = _DATABASE.get("gdelt")
_GDELT: dict[str, Any] = _GDELT_VALUE if isinstance(_GDELT_VALUE, dict) else {}
_ENTITY_ALIASES = tuple(str(value) for value in (_GDELT.get("entities") or ()) if str(value).strip())
_ACTION_ALIASES = tuple(
    str(value)
    for values in (_GDELT.get("actions") or {}).values()
    for value in (values or ())
    if str(value).strip()
)
_ENTITY_ALIASES += (
    "ecb", "european central bank", "federal reserve", "fed", "bls", "bea", "eia",
    "歐洲央行", "聯準會", "美國聯準會",
)
_ACTION_ALIASES += (
    "monetary policy", "interest rate", "rate decision", "rate cut", "rate hike",
    "liquidity", "financial stability", "貨幣政策", "利率決策", "降息", "升息",
)
# These action aliases are also loaded at runtime so bundled keyword files
# remain compatible with newer policy/energy phrasing.
_ACTION_ALIASES += (
    "steel imports", "imports surge", "urges", "urge", "urged", "calls on",
    "call on", "asks", "asked", "presses", "pressured", "oil prices",
    "lower oil prices", "reduce oil prices", "要求", "呼籲", "敦促", "降低油價",
)
_PLACE_ALIASES = tuple(
    str(value)
    for value in (
        "iran", "iranian", "israel", "persian gulf", "gulf", "hormuz", "ukraine",
        "russia", "japan", "taiwan", "china", "europe", "middle east",
        "伊朗", "以色列", "波斯灣", "荷姆茲海峽", "烏克蘭", "俄羅斯", "日本",
        "台灣", "中國", "歐洲", "中東",
    )
    if str(value).strip()
)
_TRUSTED_DISCOVERY_DOMAINS = {
    "reuters.com", "apnews.com", "bloomberg.com", "ft.com", "wsj.com",
    "bbc.com", "cnbc.com", "cnn.com", "aljazeera.com", "nytimes.com",
}


def _hits(aliases: Iterable[str], text: str) -> set[str]:
    compact = re.sub(r"[\s\-_/|:;,.!?]+", "", text)
    hits: set[str] = set()
    for alias in aliases:
        candidate = normalize_text(alias)
        if not candidate:
            continue
        if candidate in text or (len(candidate) >= 3 and candidate.replace(" ", "") in compact):
            hits.add(candidate)
    return hits


def event_evidence(record: dict[str, Any]) -> dict[str, Any]:
    """Return the category and shared entity/place/action anchors."""
    text = build_haystack(record)
    classification = classify_event_fields(record)
    category = str(record.get("classification") or classification.get("category") or "") or None
    return {
        "category": category,
        "entities": _hits(_ENTITY_ALIASES, text),
        "places": _hits(_PLACE_ALIASES, text),
        "actions": _hits(_ACTION_ALIASES, text),
        "matched_terms": list(classification.get("matched_terms") or []),
    }


def event_cluster_key(record: dict[str, Any]) -> str:
    """Build a source-independent identifier for one event cluster.

    URL and provider are deliberately excluded so syndicated reports can
    converge. This is trace metadata only; it does not satisfy the official
    source or market-synchronization notification gates.
    """
    evidence = event_evidence(record)
    raw_time = str(record.get("event_time") or record.get("released_at") or record.get("published_at") or "")
    try:
        timestamp = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        timestamp = timestamp.replace(tzinfo=timestamp.tzinfo or UTC)
        time_bucket = str(int(timestamp.timestamp()) // (2 * 60 * 60))
    except (TypeError, ValueError):
        time_bucket = "unknown"
    material = "|".join((
        evidence.get("category") or "unclassified",
        ",".join(sorted(evidence.get("entities") or ())),
        ",".join(sorted(evidence.get("places") or ())),
        ",".join(sorted(evidence.get("actions") or ())),
        time_bucket,
    ))
    return "evt-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _source_url(record: dict[str, Any]) -> str:
    trace_value = record.get("source_trace")
    trace: dict[str, Any] = trace_value if isinstance(trace_value, dict) else {}
    return str(record.get("source_url") or record.get("url") or trace.get("source_url") or "").strip()


def _source_domains(record: dict[str, Any]) -> set[str]:
    domains = {source_domain(_source_url(record))}
    trace_value = record.get("source_trace")
    trace: dict[str, Any] = trace_value if isinstance(trace_value, dict) else {}
    domains.update(source_domain(value) for value in trace.get("verified_domains") or ())
    return {value for value in domains if value}


def _credible_sources(records: Iterable[dict[str, Any]]) -> set[str]:
    domains: set[str] = set()
    for record in records:
        for value in _source_domains(record):
            tier = str(record.get("source_tier") or "")
            if tier == "official" or value in _TRUSTED_DISCOVERY_DOMAINS:
                domains.add(value)
    return domains


def _same_topic(left: dict[str, Any], right: dict[str, Any]) -> bool:
    a = event_evidence(left)
    b = event_evidence(right)
    if not a["category"] or a["category"] != b["category"]:
        return False
    shared_context = (a["entities"] | a["places"]) & (b["entities"] | b["places"])
    shared_actions = a["actions"] & b["actions"]
    # Require an entity/place and action intersection.  This prevents generic
    # words such as "market" or "talks" from joining unrelated stories.
    return bool(shared_context and shared_actions)


def _annotate(record: dict[str, Any], *, status: str, sources: Iterable[str]) -> dict[str, Any]:
    item = dict(record)
    urls = list(dict.fromkeys(str(value) for value in sources if str(value).strip()))
    domains = list(dict.fromkeys(source_domain(value) for value in urls if source_domain(value)))
    item["crosscheck_status"] = status
    item["cross_checked"] = status in {"corroborated", "official_confirmed"}
    item["crosscheck_sources"] = urls
    item["crosscheck_domains"] = domains
    item["crosscheck_reason"] = {
        "official_confirmed": "official_and_independent_source",
        "corroborated": "independent_source_same_entity_and_action",
        "pending_second_source": "waiting_second_source",
    }.get(status, status)
    item["event_cluster_key"] = event_cluster_key(item)
    trace = dict(item.get("source_trace") or {}) if isinstance(item.get("source_trace"), dict) else {}
    trace["crosscheck_status"] = status
    trace["event_cluster_key"] = item["event_cluster_key"]
    trace["crosscheck_domains"] = domains
    if urls:
        trace["crosscheck_sources"] = urls
    item["source_trace"] = trace
    return item


def cross_check_event_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Corroborate and collapse duplicate public-event records.

    The first record normally comes from an official feed.  If a later record
    from a different domain matches its entity/place and action, the official
    record is kept as the representative and all source URLs are retained.
    """
    normalized = [normalize_event_record(dict(record)) for record in records]
    output: list[dict[str, Any]] = []
    for current in normalized:
        if current.get("kind") == "market_signal":
            output.append(current)
            continue
        current_sources = {_source_url(current)} - {""}
        merged = False
        for index, existing in enumerate(output):
            if existing.get("kind") == "market_signal" or not _same_topic(existing, current):
                continue
            existing_sources = {_source_url(existing)} | set(existing.get("crosscheck_sources") or ())
            domains = _credible_sources((existing, current))
            if len(domains) < 2:
                continue
            all_sources = list(existing_sources | current_sources)
            existing_tier = str(existing.get("source_tier") or "")
            current_tier = str(current.get("source_tier") or "")
            status = "official_confirmed" if "official" in {existing_tier, current_tier} else "corroborated"
            representative = existing
            if current_tier == "official" and existing_tier != "official":
                representative = current
            output[index] = _annotate(representative, status=status, sources=all_sources)
            merged = True
            break
        if not merged:
            status = "pending_second_source" if str(current.get("source_tier")) == "discovery" else "unverified"
            output.append(_annotate(current, status=status, sources=current_sources))
    return output
